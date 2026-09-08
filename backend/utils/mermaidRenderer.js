import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import { cleanMermaidCode } from './mermaidCleaner.js';

const execAsync = promisify(exec);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_DIR = path.resolve(__dirname, '..');

// On Windows use .cmd wrapper, on Unix use the shell script directly
const IS_WIN = process.platform === 'win32';
const MMDC_NAME = IS_WIN ? 'mmdc.cmd' : 'mmdc';
const MMDC_PATH = path.join(BACKEND_DIR, 'node_modules', '.bin', MMDC_NAME);

/**
 * Render a Mermaid diagram code string to a PNG buffer.
 * Uses @mermaid-js/mermaid-cli (mmdc) via temp files.
 *
 * @param {string} mermaidCode  - Raw Mermaid code (without fence markers)
 * @param {object} opts
 * @param {string} [opts.theme='default']
 * @param {string} [opts.backgroundColor='#ffffff']
 * @param {number} [opts.width=900]
 * @param {number} [opts.scale=2]
 * @returns {Promise<Buffer|null>}
 */
export async function renderMermaidToPng(mermaidCode, opts = {}) {
  const {
    theme = 'default',
    backgroundColor = '#ffffff',
    width = 900,
    scale = 2
  } = opts;

  const cleanedCode = cleanMermaidCode(mermaidCode);
  if (!cleanedCode) return null;

  // Guard: mmdc binary must exist
  if (!fs.existsSync(MMDC_PATH)) {
    console.warn('[MermaidRenderer] mmdc not found at:', MMDC_PATH);
    return null;
  }

  const tmpDir = os.tmpdir();
  const uid = `reposage_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
  const inputFile = path.join(tmpDir, `${uid}.mmd`);
  const outputFile = path.join(tmpDir, `${uid}.png`);

  try {
    fs.writeFileSync(inputFile, cleanedCode, 'utf-8');

    // Use quoted paths to handle spaces; shell:true via exec handles .cmd on Windows
    const cmd = `"${MMDC_PATH}" -i "${inputFile}" -o "${outputFile}" -t ${theme} -b "${backgroundColor}" -w ${width} -s ${scale}`;

    await execAsync(cmd, { timeout: 45000 });

    if (!fs.existsSync(outputFile)) {
      console.warn('[MermaidRenderer] mmdc ran but no output file produced');
      return null;
    }

    const buffer = fs.readFileSync(outputFile);
    return buffer;
  } catch (err) {
    console.warn('[MermaidRenderer] Render failed:', err.message?.slice(0, 200));
    return null;
  } finally {
    try { fs.unlinkSync(inputFile); } catch {}
    try { fs.unlinkSync(outputFile); } catch {}
  }
}

/**
 * Extract all Mermaid code blocks from markdown content.
 * @param {string} markdown
 * @returns {string[]}
 */
export function extractMermaidBlocks(markdown) {
  if (!markdown) return [];
  const regex = /```mermaid\s*([\s\S]*?)```/gi;
  const blocks = [];
  let m;
  while ((m = regex.exec(markdown)) !== null) {
    const code = m[1].trim();
    if (code) blocks.push(code);
  }
  return blocks;
}
