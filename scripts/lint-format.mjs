import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const mode = process.argv[2] || 'lint';
const SOURCE_EXTENSIONS = new Set(['.js', '.mjs', '.css', '.py']);
const JS_EXTENSIONS = new Set(['.js', '.mjs']);
const PYTHON_EXTENSIONS = new Set(['.py']);
const CSS_EXTENSIONS = new Set(['.css']);
const IGNORED_DIRECTORIES = new Set([
  '.git',
  '.npm-cache',
  '.playwright-browsers',
  '__pycache__',
  'DerivedData',
  'derived-data',
  'derived_data',
  'node_modules',
  'playwright-report',
  'test-results'
]);

function sourceFiles(directory = root) {
  const files = [];
  for (const entry of readdirSync(directory)) {
    if (IGNORED_DIRECTORIES.has(entry)) continue;
    const path = join(directory, entry);
    const stats = statSync(path);
    if (stats.isDirectory()) {
      files.push(...sourceFiles(path));
    } else if (SOURCE_EXTENSIONS.has(extname(entry))) {
      files.push(path);
    }
  }
  return files.sort();
}

function label(path) {
  return relative(root, path);
}

function normalizedSource(source) {
  return source
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map(line => line.replace(/[ \t]+$/u, ''))
    .join('\n')
    .replace(/\n*$/u, '\n');
}

function checkFormat(files) {
  const dirty = files.filter(path => readFileSync(path, 'utf8') !== normalizedSource(readFileSync(path, 'utf8')));
  if (dirty.length) {
    throw new Error(`Format check failed:\n${dirty.map(path => `  ${label(path)}`).join('\n')}\nRun npm run format.`);
  }
}

function format(files) {
  let changed = 0;
  for (const path of files) {
    const current = readFileSync(path, 'utf8');
    const next = normalizedSource(current);
    if (current !== next) {
      writeFileSync(path, next);
      changed += 1;
    }
  }
  console.log(changed ? `Formatted ${changed} file(s).` : 'All source files already match lightweight formatting.');
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function lintJavaScript(files) {
  for (const path of files.filter(file => JS_EXTENSIONS.has(extname(file)))) {
    run('node', ['--check', path]);
  }
}

function lintPython(files) {
  const pythonFiles = files.filter(file => PYTHON_EXTENSIONS.has(extname(file)));
  if (pythonFiles.length) run('python3', ['-m', 'py_compile', ...pythonFiles]);
}

function lintCss(files) {
  for (const path of files.filter(file => CSS_EXTENSIONS.has(extname(file)))) {
    const source = readFileSync(path, 'utf8');
    let depth = 0;
    let line = 1;
    for (const char of source) {
      if (char === '\n') line += 1;
      if (char === '{') depth += 1;
      if (char === '}') depth -= 1;
      if (depth < 0) throw new Error(`${label(path)}:${line} has an extra closing brace.`);
    }
    if (depth !== 0) throw new Error(`${label(path)} has ${depth} unclosed brace(s).`);
  }
}

function lint(files) {
  lintJavaScript(files);
  lintPython(files);
  lintCss(files);
  console.log(`Linted ${files.length} JS/CSS/Python file(s).`);
}

try {
  const files = sourceFiles();
  if (mode === 'format') {
    format(files);
  } else if (mode === 'format:check') {
    checkFormat(files);
    console.log(`Format check passed for ${files.length} JS/CSS/Python file(s).`);
  } else if (mode === 'lint') {
    lint(files);
  } else {
    throw new Error(`Unknown mode: ${mode}`);
  }
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
