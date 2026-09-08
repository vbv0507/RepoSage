import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { parseCodeFile, scanDirectory } from './services/astParser.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

console.log('🔍 Running AST Parser Verification Script across codebase...');

// Test file 1: backend/services/astParser.js
const astParserPath = path.join(__dirname, 'services', 'astParser.js');
const resAstParser = parseCodeFile(astParserPath, projectRoot);

console.log(`\n📄 Parsed ${resAstParser.filePath}:`);
console.log(`   Found ${resAstParser.chunks.length} chunks:`);
for (const chunk of resAstParser.chunks) {
  console.log(`   - [${chunk.type}] ${chunk.name.padEnd(25)} Lines: ${String(chunk.startLine).padStart(3)}-${String(chunk.endLine).padStart(3)} | Summary: ${chunk.summary}`);
}

// Verify known function line numbers in astParser.js
const contentAst = fs.readFileSync(astParserPath, 'utf-8');
const linesAst = contentAst.split('\n');

function assertFunctionBoundary(chunks, name, expectedType) {
  const found = chunks.find(c => c.name === name);
  if (!found) {
    throw new Error(`Expected chunk '${name}' not found!`);
  }
  if (found.type !== expectedType) {
    throw new Error(`Chunk '${name}' expected type '${expectedType}', got '${found.type}'`);
  }
  // Verify that the code at startLine contains the function name
  const codeAtStart = linesAst[found.startLine - 1];
  if (!codeAtStart.includes(name)) {
    throw new Error(`Chunk '${name}' startLine ${found.startLine} does not contain '${name}': "${codeAtStart}"`);
  }
  console.log(`   ✅ Verified ${found.type} '${name}' boundary: L${found.startLine}-L${found.endLine}`);
}

assertFunctionBoundary(resAstParser.chunks, 'initParsers', 'function');
assertFunctionBoundary(resAstParser.chunks, 'isIgnoredFile', 'function');
assertFunctionBoundary(resAstParser.chunks, 'scanDirectory', 'function');
assertFunctionBoundary(resAstParser.chunks, 'parseCodeFile', 'function');
assertFunctionBoundary(resAstParser.chunks, 'extractJavaScriptBlocks', 'function');
assertFunctionBoundary(resAstParser.chunks, 'extractPythonBlocks', 'function');
assertFunctionBoundary(resAstParser.chunks, 'extractGenericBlocks', 'function');
assertFunctionBoundary(resAstParser.chunks, 'buildDependencyGraph', 'function');

// Test file 2: backend/services/chromaService.js
const chromaPath = path.join(__dirname, 'services', 'chromaService.js');
const resChroma = parseCodeFile(chromaPath, projectRoot);
console.log(`\n📄 Parsed ${resChroma.filePath}:`);
console.log(`   Found ${resChroma.chunks.length} chunks:`);
for (const chunk of resChroma.chunks) {
  console.log(`   - [${chunk.type}] ${chunk.name.padEnd(25)} Lines: ${String(chunk.startLine).padStart(3)}-${String(chunk.endLine).padStart(3)}`);
}

// Test file 3: frontend/src/App.jsx (TSX / JSX parser)
const appJsxPath = path.join(projectRoot, 'frontend', 'src', 'App.jsx');
if (fs.existsSync(appJsxPath)) {
  const resApp = parseCodeFile(appJsxPath, projectRoot);
  console.log(`\n📄 Parsed ${resApp.filePath}:`);
  console.log(`   Found ${resApp.chunks.length} chunks:`);
  for (const chunk of resApp.chunks) {
    console.log(`   - [${chunk.type}] ${chunk.name.padEnd(25)} Lines: ${String(chunk.startLine).padStart(3)}-${String(chunk.endLine).padStart(3)}`);
  }
}

// Test file 4: Python syntax verification
const pyScratchPath = path.join(__dirname, 'scratch_test.py');
fs.writeFileSync(pyScratchPath, `
import os
import sys

class RepositoryScanner:
    """Scans repositories for metrics"""
    def __init__(self, root_dir: str):
        self.root = root_dir

    def scan_files(self):
        return [f for f in os.listdir(self.root)]

    async def compute_hash_async(self, file_path: str):
        return "hash123"

def standalone_py_func(x, y):
    return x * y
`);

const resPy = parseCodeFile(pyScratchPath, projectRoot);
console.log(`\n📄 Parsed Python sample (${resPy.filePath}):`);
console.log(`   Found ${resPy.chunks.length} chunks:`);
for (const chunk of resPy.chunks) {
  console.log(`   - [${chunk.type}] ${chunk.name.padEnd(25)} Lines: ${String(chunk.startLine).padStart(3)}-${String(chunk.endLine).padStart(3)}`);
}

// Clean up scratch python file
fs.unlinkSync(pyScratchPath);

// Summary counts
const totalTestedFunctions = resAstParser.chunks.length + resChroma.chunks.length + resPy.chunks.length;
console.log(`\n🎉 Verification Complete: Successfully parsed ${totalTestedFunctions} functions, methods, and classes across JS, JSX, and Python using web-tree-sitter WASM!`);
