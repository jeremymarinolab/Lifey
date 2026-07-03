import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const checkOnly = process.argv.includes('--check');
const VERSIONED_EXTENSIONS = new Set(['.css', '.js', '.webmanifest']);

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

function versionedAssetsFromHtml(html) {
  const assets = [];
  const missingVersion = [];
  for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
    const value = match[1];
    const asset = localAssetPath(value);
    if (!asset || !requiresVersion(asset)) continue;
    if (!/[?&]v=[^&#"]+/.test(value)) missingVersion.push(asset);
    if (!assets.includes(asset)) assets.push(asset);
  }
  if (missingVersion.length) {
    throw new Error(`index.html local shell assets need ?v=: ${missingVersion.join(', ')}`);
  }
  return assets;
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
  return direct.flatMap(imported => [imported, ...importedAssets(imported, seen)]).filter((item, index, list) => list.indexOf(item) === index);
}

function versionedAssetGraph(html) {
  const roots = versionedAssetsFromHtml(html);
  return roots.flatMap(asset => [asset, ...importedAssets(asset)]).filter((item, index, list) => list.indexOf(item) === index);
}

function assetVersion(versionedAssets) {
  const hash = createHash('sha256');
  for (const asset of versionedAssets) {
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

function shellEntriesFromWorker(worker) {
  const match = worker.match(/const SHELL = \[([\s\S]*?)\];/);
  if (!match) throw new Error('service-worker.js SHELL list was not found.');
  return [...match[1].matchAll(/'([^']+)'/g)].map(item => item[1]);
}

function shellAssetsFromWorker(worker) {
  return shellEntriesFromWorker(worker).map(item => localAssetPath(item)).filter(Boolean);
}

function replaceShellAssets(worker, versionedAssets) {
  const existingEntries = shellEntriesFromWorker(worker);
  const fixedEntries = ['./', './index.html'];
  const versionedEntries = versionedAssets.map(asset => `./${asset}`);
  const unversionedEntries = existingEntries.filter(entry => {
    const asset = localAssetPath(entry);
    return asset && asset !== 'index.html' && !requiresVersion(asset);
  });
  const nextEntries = [...new Set([...fixedEntries, ...versionedEntries, ...unversionedEntries])];
  const rendered = `const SHELL = [\n${nextEntries.map(entry => `  '${entry}'`).join(',\n')}\n];`;
  return worker.replace(/const SHELL = \[[\s\S]*?\];/, rendered);
}

function assertShellAssets(worker, versionedAssets) {
  const shellAssets = shellAssetsFromWorker(worker);
  const missing = versionedAssets.filter(asset => !worker.includes(`'./${asset}'`));
  if (missing.length) throw new Error(`service-worker.js SHELL is missing: ${missing.join(', ')}`);
  const unreferenced = shellAssets.filter(asset => requiresVersion(asset) && asset !== 'index.html' && !versionedAssets.includes(asset));
  if (unreferenced.length) throw new Error(`service-worker.js SHELL has versioned assets not referenced by index.html: ${unreferenced.join(', ')}`);
}

const html = read('index.html').toString();
const worker = read('service-worker.js').toString();
const versionedAssets = versionedAssetGraph(html);
const version = assetVersion(versionedAssets);
const nextWorker = replaceShellAssets(replaceCacheVersion(worker, version), versionedAssets);
const files = [
  ['index.html', replaceAssetVersions(html, version, versionedAssets)],
  ['service-worker.js', nextWorker]
];

assertShellAssets(files[1][1], versionedAssets);

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
