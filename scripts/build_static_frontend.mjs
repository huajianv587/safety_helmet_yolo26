import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, '..');
const frontendDir = join(projectRoot, 'frontend');
const distDir = join(projectRoot, 'dist');
const distAppDir = join(distDir, 'app');
const landingEntryPath = join(projectRoot, 'helmet_safety_landing.html');
const defaultApiBaseUrl = 'http://127.0.0.1:8000';
const apiBaseUrl = String(process.env.HELMET_API_BASE_URL || defaultApiBaseUrl).replace(/\/+$/, '');

const oldFinanceCopy = ['ESG Quant', 'Quant Terminal', 'ALPHA ENGINE', 'portfolio', 'backtest'];
const mojibakeMarkers = ['\uFFFD', '鈥', '鈽', '鎽', '鐧', '閫', '鐘', '寰', '鏆', '璐', '韬'];
const textAuditPatterns = [
  ...oldFinanceCopy.map((token) => ({ token, reason: 'old reference project finance copy' })),
  ...mojibakeMarkers.map((token) => ({ token, reason: 'mojibake marker' })),
];

if (!existsSync(frontendDir)) {
  throw new Error(`frontend directory not found: ${frontendDir}`);
}
if (!existsSync(landingEntryPath)) {
  throw new Error(`landing page not found: ${landingEntryPath}`);
}

rmSync(distDir, { recursive: true, force: true });
mkdirSync(distAppDir, { recursive: true });
copyDirectory(frontendDir, distAppDir);
writeFileSync(
  join(distAppDir, 'app-config.js'),
  `window.__HELMET_API_BASE_URL__ = ${JSON.stringify(apiBaseUrl)};\n`,
  'utf8',
);
writeFileSync(join(distDir, 'index.html'), readText(landingEntryPath), 'utf8');

auditRuntimeText(frontendDir, 'frontend');
auditRuntimeText(distAppDir, 'dist/app');
auditRuntimeText(landingEntryPath, 'landing');

console.log(`Static frontend bundle generated in ${distDir}`);
console.log(`HELMET_API_BASE_URL=${apiBaseUrl}`);

function copyDirectory(sourceDir, targetDir) {
  mkdirSync(targetDir, { recursive: true });
  for (const entry of readdirSync(sourceDir, { withFileTypes: true })) {
    const sourcePath = join(sourceDir, entry.name);
    const targetPath = join(targetDir, entry.name);
    if (entry.isDirectory()) {
      copyDirectory(sourcePath, targetPath);
      continue;
    }
    if (entry.isFile() || statSync(sourcePath).isFile()) copyFileSync(sourcePath, targetPath);
  }
}

function readText(path) {
  return readFileSync(path, 'utf8');
}

function auditRuntimeText(path, label) {
  const failures = [];
  const visit = (filePath) => {
    if (filePath.includes(`${join('vendor', 'echarts')}`)) return;
    const ext = filePath.split('.').pop()?.toLowerCase();
    if (!['js', 'mjs', 'css', 'html'].includes(ext || '')) return;
    const normalized = stripComments(readText(filePath), ext);
    for (const pattern of textAuditPatterns) {
      if (normalized.includes(pattern.token)) {
        failures.push(`${label}: ${filePath} -> ${pattern.reason} (${pattern.token})`);
      }
    }
  };
  if (statSync(path).isDirectory()) walkFiles(path, visit);
  else visit(path);
  if (failures.length) throw new Error(`Static bundle text audit failed:\n${failures.join('\n')}`);
}

function walkFiles(dir, visit) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const nextPath = join(dir, entry.name);
    if (entry.isDirectory()) walkFiles(nextPath, visit);
    else if (entry.isFile()) visit(nextPath);
  }
}

function stripComments(text, ext) {
  if (ext === 'css') return text.replace(/\/\*[\s\S]*?\*\//g, '');
  if (ext === 'html') return text.replace(/<!--[\s\S]*?-->/g, '');
  if (ext === 'js' || ext === 'mjs') {
    return text
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
  }
  return text;
}
