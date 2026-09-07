import fs from 'fs';
import path from 'path';

const IGNORED_DIRS = new Set([
  'node_modules', '.git', 'dist', 'build', '.next', '.nuxt',
  'coverage', '.venv', 'venv', 'env', '__pycache__', '.idea',
  '.vscode', 'bin', 'obj', 'target', 'chroma_data'
]);

const IGNORED_FILES = new Set([
  'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
  '.DS_Store', 'Thumbs.db'
]);

const CODE_EXTENSIONS = new Set([
  '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
  '.py', '.go', '.java', '.cpp', '.c', '.h', '.cs',
  '.rs', '.php', '.rb', '.sql', '.json', '.yaml', '.yml', '.md'
]);

/**
 * Scan directory recursively for source files
 */
export function scanDirectory(dirPath, maxFiles = 200) {
  const fileList = [];

  function walk(currentDir) {
    if (fileList.length >= maxFiles) return;

    let entries = [];
    try {
      entries = fs.readdirSync(currentDir, { withFileTypes: true });
    } catch (e) {
      return;
    }

    for (const entry of entries) {
      if (fileList.length >= maxFiles) break;

      const fullPath = path.join(currentDir, entry.name);

      if (entry.isDirectory()) {
        if (!IGNORED_DIRS.has(entry.name) && !entry.name.startsWith('.')) {
          walk(fullPath);
        }
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name).toLowerCase();
        if (!IGNORED_FILES.has(entry.name) && CODE_EXTENSIONS.has(ext)) {
          fileList.push(fullPath);
        }
      }
    }
  }

  walk(dirPath);
  return fileList;
}

/**
 * Parse a source file into logical AST-like code blocks (functions, classes, imports)
 */
export function parseCodeFile(filePath, repoRoot) {
  let content = '';
  try {
    content = fs.readFileSync(filePath, 'utf-8');
  } catch (e) {
    return { filePath, chunks: [], imports: [], exports: [] };
  }

  const relativePath = path.relative(repoRoot, filePath).replace(/\\/g, '/');
  const ext = path.extname(filePath).toLowerCase();
  const lines = content.split('\n');

  const chunks = [];
  const imports = [];
  const exports = [];

  // Extract imports
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    // JS/TS: import ... from '...' or require('...')
    const jsImportMatch = line.match(/(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))/);
    if (jsImportMatch) {
      imports.push(jsImportMatch[1] || jsImportMatch[2]);
    }
    // Python: import ... or from ... import ...
    const pyImportMatch = line.match(/(?:from\s+([a-zA-Z0-9_.]+)\s+import|import\s+([a-zA-Z0-9_.]+))/);
    if (pyImportMatch) {
      imports.push(pyImportMatch[1] || pyImportMatch[2]);
    }
  }

  // Language-specific block extractor
  if (['.js', '.jsx', '.ts', '.tsx', '.mjs'].includes(ext)) {
    extractJavaScriptBlocks(content, lines, relativePath, chunks);
  } else if (ext === '.py') {
    extractPythonBlocks(content, lines, relativePath, chunks);
  } else {
    // Generic fallback: chunk by paragraph / block
    extractGenericBlocks(content, lines, relativePath, chunks);
  }

  // If no functions were detected (e.g. config file, short module), index the file as whole
  if (chunks.length === 0 && content.trim().length > 0) {
    chunks.push({
      filePath: relativePath,
      name: path.basename(relativePath),
      type: 'module',
      startLine: 1,
      endLine: lines.length,
      code: content.slice(0, 3000), // Cap for token budget
      summary: `File: ${relativePath}`
    });
  }

  return {
    filePath: relativePath,
    imports,
    chunks
  };
}

/**
 * Extract functions, classes, and methods from JS/TS code
 */
function extractJavaScriptBlocks(content, lines, relativePath, chunks) {
  // Regex patterns for function declarations, arrow functions, and classes
  const functionRegex = /(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)|(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>|class\s+([a-zA-Z0-9_$]+)/g;

  let match;
  while ((match = functionRegex.exec(content)) !== null) {
    const name = match[1] || match[3] || match[5];
    const isClass = Boolean(match[5]);
    const startIndex = match.index;

    // Find line number
    const lineNum = content.substring(0, startIndex).split('\n').length;
    // Extract snippet (up to 40 lines or closing block)
    const blockLines = lines.slice(lineNum - 1, lineNum + 45);
    const codeSnippet = blockLines.join('\n');

    chunks.push({
      filePath: relativePath,
      name: name,
      type: isClass ? 'class' : 'function',
      startLine: lineNum,
      endLine: Math.min(lineNum + blockLines.length, lines.length),
      code: codeSnippet,
      summary: `${isClass ? 'Class' : 'Function'} ${name} in ${relativePath}`
    });
  }
}

/**
 * Extract functions and classes from Python code
 */
function extractPythonBlocks(content, lines, relativePath, chunks) {
  const pyRegex = /^(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\):|^class\s+([a-zA-Z0-9_]+)(?:\(([^)]*)\))?:/gm;

  let match;
  while ((match = pyRegex.exec(content)) !== null) {
    const name = match[1] || match[3];
    const isClass = Boolean(match[3]);
    const startIndex = match.index;

    const lineNum = content.substring(0, startIndex).split('\n').length;
    const blockLines = lines.slice(lineNum - 1, lineNum + 40);
    const codeSnippet = blockLines.join('\n');

    chunks.push({
      filePath: relativePath,
      name: name,
      type: isClass ? 'class' : 'function',
      startLine: lineNum,
      endLine: Math.min(lineNum + blockLines.length, lines.length),
      code: codeSnippet,
      summary: `${isClass ? 'Python class' : 'Python function'} ${name} in ${relativePath}`
    });
  }
}

/**
 * Generic block chunking
 */
function extractGenericBlocks(content, lines, relativePath, chunks) {
  const chunkSize = 50;
  for (let i = 0; i < lines.length; i += chunkSize) {
    const slice = lines.slice(i, i + chunkSize);
    chunks.push({
      filePath: relativePath,
      name: `${path.basename(relativePath)}:L${i + 1}`,
      type: 'block',
      startLine: i + 1,
      endLine: Math.min(i + chunkSize, lines.length),
      code: slice.join('\n'),
      summary: `Section of ${relativePath} (lines ${i + 1}-${Math.min(i + chunkSize, lines.length)})`
    });
  }
}

/**
 * Construct an architectural dependency graph across all parsed files
 */
export function buildDependencyGraph(parsedFiles) {
  const nodes = [];
  const links = [];
  const fileSet = new Set();

  // Create nodes
  for (const file of parsedFiles) {
    fileSet.add(file.filePath);
    let category = 'other';
    const lower = file.filePath.toLowerCase();

    if (lower.includes('route') || lower.includes('api') || lower.includes('controller') || lower.includes('endpoint')) {
      category = 'api';
    } else if (lower.includes('service') || lower.includes('business') || lower.includes('manager')) {
      category = 'service';
    } else if (lower.includes('model') || lower.includes('schema') || lower.includes('entity') || lower.includes('db')) {
      category = 'data';
    } else if (lower.includes('util') || lower.includes('helper') || lower.includes('lib')) {
      category = 'utility';
    } else if (lower.includes('test') || lower.includes('spec')) {
      category = 'test';
    } else if (lower.includes('config') || lower.includes('env')) {
      category = 'config';
    }

    nodes.push({
      id: file.filePath,
      name: path.basename(file.filePath),
      category,
      chunksCount: file.chunks.length
    });
  }

  // Create links by matching imports to local files
  for (const file of parsedFiles) {
    for (const imp of file.imports) {
      const cleanImp = imp.replace(/^[./]+/, '');
      for (const targetFile of fileSet) {
        if (targetFile.includes(cleanImp) && targetFile !== file.filePath) {
          links.push({
            source: file.filePath,
            target: targetFile
          });
          break;
        }
      }
    }
  }

  return { nodes, links };
}
