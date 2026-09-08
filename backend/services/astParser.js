import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import { Parser, Language } from 'web-tree-sitter';

const require = createRequire(import.meta.url);

const IGNORED_DIRS = new Set([
  'node_modules', '.git', 'dist', 'build', '.next', '.nuxt',
  'coverage', '.venv', 'venv', 'env', '__pycache__', '.idea',
  '.vscode', 'bin', 'obj', 'target', 'chroma_data', 'cloned_repos'
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

// Tree-sitter WASM parsers cache
let parsers = null;
let initPromise = null;

/**
 * Initialize WebAssembly Tree-sitter parsers for JavaScript, TypeScript, TSX, and Python.
 * Zero native compilation (no node-gyp, no C++ toolchain).
 */
export async function initParsers() {
  if (parsers) return parsers;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    try {
      await Parser.init();

      const jsWasm = require.resolve('@repomix/tree-sitter-wasms/out/tree-sitter-javascript.wasm');
      const tsWasm = require.resolve('@repomix/tree-sitter-wasms/out/tree-sitter-typescript.wasm');
      const tsxWasm = require.resolve('@repomix/tree-sitter-wasms/out/tree-sitter-tsx.wasm');
      const pyWasm = require.resolve('@repomix/tree-sitter-wasms/out/tree-sitter-python.wasm');

      const [jsLang, tsLang, tsxLang, pyLang] = await Promise.all([
        Language.load(jsWasm),
        Language.load(tsWasm),
        Language.load(tsxWasm),
        Language.load(pyWasm)
      ]);

      const jsParser = new Parser();
      jsParser.setLanguage(jsLang);

      const tsParser = new Parser();
      tsParser.setLanguage(tsLang);

      const tsxParser = new Parser();
      tsxParser.setLanguage(tsxLang);

      const pyParser = new Parser();
      pyParser.setLanguage(pyLang);

      parsers = {
        '.js': jsParser,
        '.mjs': jsParser,
        '.cjs': jsParser,
        '.jsx': tsxParser,
        '.ts': tsParser,
        '.tsx': tsxParser,
        '.py': pyParser
      };
      return parsers;
    } catch (err) {
      console.warn('⚠️ Tree-sitter WASM initialization warning (will use line-based chunking fallback):', err.message);
      parsers = null;
      return null;
    }
  })();

  return initPromise;
}

// Top-level await guarantees parsers are loaded as soon as astParser module is imported
await initParsers();

/**
 * Check if a file should be ignored (e.g. minified or bundled files)
 */
function isIgnoredFile(filename) {
  if (IGNORED_FILES.has(filename)) return true;
  const lower = filename.toLowerCase();
  return (
    lower.endsWith('.min.js') ||
    lower.endsWith('.min.mjs') ||
    lower.endsWith('.umd.js') ||
    lower.endsWith('.bundle.js') ||
    lower.endsWith('.chunk.js') ||
    lower.endsWith('.min.css') ||
    lower.endsWith('.map') ||
    lower.endsWith('.lock')
  );
}

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
        if (!isIgnoredFile(entry.name) && CODE_EXTENSIONS.has(ext)) {
          // Skip files > 350KB (vendor bundles, compiled libraries, large data dumps)
          try {
            const stat = fs.statSync(fullPath);
            if (stat.size <= 350 * 1024) {
              fileList.push(fullPath);
            }
          } catch (e) {
            fileList.push(fullPath);
          }
        }
      }
    }
  }

  walk(dirPath);
  return fileList;
}

/**
 * Parse a source file into logical AST code blocks (functions, classes, methods, imports)
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

  // Quick check for minified file (any line > 1000 chars)
  const hasMinifiedLines = lines.some(l => l.length > 1000);
  if (hasMinifiedLines) {
    return {
      filePath: relativePath,
      imports: [],
      chunks: [{
        filePath: relativePath,
        name: path.basename(relativePath),
        type: 'module',
        startLine: 1,
        endLine: Math.min(lines.length, 50),
        code: content.slice(0, 1500),
        summary: `Minified module: ${relativePath}`
      }]
    };
  }

  // Extract imports
  for (let i = 0; i < Math.min(lines.length, 200); i++) {
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

  // Language-specific block extractor with graceful fallback
  const parser = parsers ? parsers[ext] : null;

  if (parser) {
    try {
      if (['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'].includes(ext)) {
        extractJavaScriptBlocks(content, relativePath, chunks, parser);
      } else if (ext === '.py') {
        extractPythonBlocks(content, relativePath, chunks, parser);
      }
    } catch (parseErr) {
      console.warn(`⚠️ Tree-sitter parse error in ${relativePath}, falling back to generic blocks:`, parseErr.message);
      chunks.length = 0;
      extractGenericBlocks(content, lines, relativePath, chunks);
    }
  } else {
    // Generic fallback: chunk by paragraph / block
    extractGenericBlocks(content, lines, relativePath, chunks);
  }

  // If no functions/classes were detected (e.g. config file, short module), index the file as whole
  if (chunks.length === 0 && content.trim().length > 0) {
    chunks.push({
      filePath: relativePath,
      name: path.basename(relativePath),
      type: 'module',
      startLine: 1,
      endLine: lines.length,
      code: content.slice(0, 2000), // Cap for token budget
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
 * Extract functions, classes, methods, and arrow functions from JS/TS code using Tree-sitter AST
 */
function extractJavaScriptBlocks(content, relativePath, chunks, parser) {
  const tree = parser.parse(content);
  const handledNodeIds = new Set();

  function traverse(node) {
    // 1. Function declaration: function foo() {}
    if (node.type === 'function_declaration') {
      const name = node.childForFieldName('name')?.text || 'anonymous';
      const startLine = node.startPosition.row + 1;
      const endLine = node.endPosition.row + 1;
      chunks.push({
        filePath: relativePath,
        name,
        type: 'function',
        startLine,
        endLine,
        code: node.text.slice(0, 2000),
        summary: `Function ${name} in ${relativePath}`
      });
      handledNodeIds.add(node.id);
    }
    // 2. Class declaration: class Foo {}
    else if (node.type === 'class_declaration') {
      const name = node.childForFieldName('name')?.text || 'anonymous';
      const startLine = node.startPosition.row + 1;
      const endLine = node.endPosition.row + 1;
      chunks.push({
        filePath: relativePath,
        name,
        type: 'class',
        startLine,
        endLine,
        code: node.text.slice(0, 2000),
        summary: `Class ${name} in ${relativePath}`
      });
      handledNodeIds.add(node.id);
    }
    // 3. Method definition in class or object shorthand: method() {}
    else if (node.type === 'method_definition') {
      const name = node.childForFieldName('name')?.text || 'anonymous';
      const startLine = node.startPosition.row + 1;
      const endLine = node.endPosition.row + 1;
      chunks.push({
        filePath: relativePath,
        name,
        type: 'method',
        startLine,
        endLine,
        code: node.text.slice(0, 2000),
        summary: `Method ${name} in ${relativePath}`
      });
      handledNodeIds.add(node.id);
    }
    // 4. Variable declarator: const foo = () => {} or const foo = function() {}
    else if (node.type === 'variable_declarator') {
      const name = node.childForFieldName('name')?.text;
      const value = node.childForFieldName('value');
      if (name && value) {
        if (value.type === 'arrow_function' || value.type === 'function' || value.type === 'function_expression') {
          const isArrow = value.type === 'arrow_function';
          const enclosingDecl = (node.parent?.type === 'lexical_declaration' || node.parent?.type === 'variable_declaration') ? node.parent : null;
          const targetNode = enclosingDecl || node;
          const startLine = targetNode.startPosition.row + 1;
          const endLine = targetNode.endPosition.row + 1;
          const type = isArrow ? 'arrow_function' : 'function';
          const typeLabel = isArrow ? 'Arrow function' : 'Function';

          chunks.push({
            filePath: relativePath,
            name,
            type,
            startLine,
            endLine,
            code: targetNode.text.slice(0, 2000),
            summary: `${typeLabel} ${name} in ${relativePath}`
          });
          handledNodeIds.add(value.id);
        }
      }
    }
    // 5. Object property pair: { foo: () => {} }
    else if (node.type === 'pair') {
      const key = node.childForFieldName('key')?.text;
      const value = node.childForFieldName('value');
      if (key && value) {
        if (value.type === 'arrow_function' || value.type === 'function' || value.type === 'function_expression') {
          const isArrow = value.type === 'arrow_function';
          const startLine = node.startPosition.row + 1;
          const endLine = node.endPosition.row + 1;
          const type = isArrow ? 'arrow_function' : 'method';
          const typeLabel = isArrow ? 'Arrow function' : 'Method';

          chunks.push({
            filePath: relativePath,
            name: key,
            type,
            startLine,
            endLine,
            code: node.text.slice(0, 2000),
            summary: `${typeLabel} ${key} in ${relativePath}`
          });
          handledNodeIds.add(value.id);
        }
      }
    }

    // Traverse children, skipping values already handled as named entities
    for (let i = 0; i < node.namedChildCount; i++) {
      const child = node.namedChild(i);
      if (!handledNodeIds.has(child.id)) {
        traverse(child);
      }
    }
  }

  traverse(tree.rootNode);
}

/**
 * Extract functions and classes from Python code using Tree-sitter AST
 */
function extractPythonBlocks(content, relativePath, chunks, parser) {
  const tree = parser.parse(content);

  function traverse(node) {
    if (node.type === 'class_definition') {
      const name = node.childForFieldName('name')?.text || 'anonymous';
      const startLine = node.startPosition.row + 1;
      const endLine = node.endPosition.row + 1;
      chunks.push({
        filePath: relativePath,
        name,
        type: 'class',
        startLine,
        endLine,
        code: node.text.slice(0, 2000),
        summary: `Class ${name} in ${relativePath}`
      });
    } else if (node.type === 'function_definition') {
      const name = node.childForFieldName('name')?.text || 'anonymous';
      const isMethod = node.parent?.type === 'block' && node.parent?.parent?.type === 'class_definition';
      const type = isMethod ? 'method' : 'function';
      const typeLabel = isMethod ? 'Method' : 'Function';
      const startLine = node.startPosition.row + 1;
      const endLine = node.endPosition.row + 1;

      chunks.push({
        filePath: relativePath,
        name,
        type,
        startLine,
        endLine,
        code: node.text.slice(0, 2000),
        summary: `${typeLabel} ${name} in ${relativePath}`
      });
    }

    for (let i = 0; i < node.namedChildCount; i++) {
      traverse(node.namedChild(i));
    }
  }

  traverse(tree.rootNode);
}

/**
 * Generic block chunking fallback (50-line blocks)
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
      code: slice.join('\n').slice(0, 2000),
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
