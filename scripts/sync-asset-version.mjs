import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const checkOnly = process.argv.includes('--check');
const VERSIONED_EXTENSIONS = new Set(['.css', '.js', '.webmanifest']);
const STATIC_SHELL_ENTRIES = ['./', './index.html'];
const SHELL_BLOCK_PATTERN = /(?:\/\/ Generated from index\.html, imported JS modules, and manifest\.webmanifest\.\n)?const SHELL = \[[\s\S]*?\];/;

function read(path) {
  return readFileSync(join(root, path));
}

function localAssetPath(value) {
  if (!value.startsWith('./')) return null;
  const path = value.slice(2).split(/[?#]/, 1)[0];
  return path && !path.includes('..') ? path : null;
}

function requiresVersion(asset) {
  return [...VERSIONED_EXTENSIONS].some(extension => asset.endsWith(extension));
}

function unique(items) {
  return [...new Set(items)];
}

function localAssetsFromHtml(html) {
  const assets = [];
  for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
    const value = match[1];
    const asset = localAssetPath(value);
    if (asset && !assets.includes(asset)) assets.push(asset);
  }
  return assets;
}

function versionedAssetsFromHtml(html) {
  const missingVersion = [];
  for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
    const value = match[1];
    const asset = localAssetPath(value);
    if (asset && requiresVersion(asset) && !/[?&]v=[^&#"]+/.test(value)) missingVersion.push(asset);
  }
  if (missingVersion.length) throw new Error(`index.html local shell assets need ?v=: ${missingVersion.join(', ')}`);
  return localAssetsFromHtml(html).filter(requiresVersion);
}

function resolveImportAsset(specifier, fromAsset) {
  if (!specifier.startsWith('./') && !specifier.startsWith('../')) return null;
  const asset = normalize(join(dirname(fromAsset), specifier)).replaceAll('\\', '/');
  return asset && !asset.startsWith('../') && requiresVersion(asset) ? asset : null;
}

function importedAssets(asset, seen = new Set()) {
  if (seen.has(asset) || !asset.endsWith('.js')) return [];
  seen.add(asset);
  const source = read(asset).toString();
  const direct = [];
  for (const match of source.matchAll(/\bimport\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]/g)) {
    const imported = resolveImportAsset(match[1], asset);
    if (imported && !direct.includes(imported)) direct.push(imported);
  }
  return unique(direct.flatMap(imported => [imported, ...importedAssets(imported, seen)]));
}

function versionedAssetGraph(html) {
  const roots = versionedAssetsFromHtml(html);
  return unique(roots.flatMap(asset => [asset, ...importedAssets(asset)]));
}

function manifestAssets(manifestAsset) {
  if (!manifestAsset || !manifestAsset.endsWith('.webmanifest')) return [];
  const manifest = JSON.parse(read(manifestAsset).toString());
  const assetValues = [];
  for (const collectionName of ['icons', 'screenshots', 'shortcuts']) {
    const collection = Array.isArray(manifest[collectionName]) ? manifest[collectionName] : [];
    for (const item of collection) {
      if (item?.src) assetValues.push(item.src);
      if (Array.isArray(item?.icons)) assetValues.push(...item.icons.map(icon => icon?.src).filter(Boolean));
    }
  }
  return unique(assetValues.map(localAssetPath).filter(Boolean));
}

function shellAssetGraph(html) {
  const htmlAssets = localAssetsFromHtml(html);
  const imported = htmlAssets.flatMap(asset => importedAssets(asset));
  const manifestReferenced = htmlAssets.flatMap(asset => manifestAssets(asset));
  const assets = unique([...htmlAssets, ...imported, ...manifestReferenced]);
  const missing = assets.filter(asset => !existsSync(join(root, asset)));
  if (missing.length) throw new Error(`Local shell assets do not exist: ${missing.join(', ')}`);
  return assets;
}

function assetVersion(shellAssets) {
  const hash = createHash('sha256');
  for (const asset of shellAssets) {
    hash.update(asset);
    hash.update('\0');
    hash.update(read(asset));
    hash.update('\0');
  }
  return hash.digest('hex').slice(0, 12);
}

function replaceAssetVersions(html, version, versionedAssets) {
  let next = html;
  for (const asset of versionedAssets) {
    const name = asset.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    next = next.replace(new RegExp(`(href|src)="(\\./${name})\\?v=[^"]+"`, 'g'), `$1="$2?v=${version}"`);
  }
  return next;
}

function replaceCacheVersion(worker, version) {
  return worker.replace(/const CACHE = 'lifey-shell-v[^']+';/, `const CACHE = 'lifey-shell-v${version}';`);
}

function shellEntries(shellAssets) {
  return unique([...STATIC_SHELL_ENTRIES, ...shellAssets.map(asset => `./${asset}`)]);
}

function replaceShellAssets(worker, shellAssets) {
  const rendered = `// Generated from index.html, imported JS modules, and manifest.webmanifest.\nconst SHELL = [\n${shellEntries(shellAssets).map(entry => `  '${entry}'`).join(',\n')}\n];`;
  if (!SHELL_BLOCK_PATTERN.test(worker)) throw new Error('service-worker.js SHELL list was not found.');
  return worker.replace(SHELL_BLOCK_PATTERN, rendered);
}

function assertShellAssets(worker, shellAssets) {
  const missing = shellEntries(shellAssets).filter(entry => !worker.includes(`'${entry}'`));
  if (missing.length) throw new Error(`service-worker.js SHELL is missing: ${missing.join(', ')}`);
}

const html = read('index.html').toString();
const worker = read('service-worker.js').toString();
const versionedAssets = versionedAssetGraph(html);
const shellAssets = shellAssetGraph(html);
const version = assetVersion(shellAssets);
const nextWorker = replaceShellAssets(replaceCacheVersion(worker, version), shellAssets);
const files = [
  ['index.html', replaceAssetVersions(html, version, versionedAssets)],
  ['service-worker.js', nextWorker]
];

assertShellAssets(files[1][1], shellAssets);

const changed = files.filter(([path, next]) => read(path).toString() !== next);

if (checkOnly) {
  if (changed.length) {
    console.error(`Asset version is stale (${version}): ${changed.map(([path]) => basename(path)).join(', ')}`);
    process.exit(1);
  }
  console.log(`Asset version is current (${version}).`);
} else {
  for (const [path, next] of changed) writeFileSync(join(root, path), next);
  console.log(changed.length ? `Updated asset version to ${version}.` : `Asset version already current (${version}).`);
}
