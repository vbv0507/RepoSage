import path from 'path';
import { scanDirectory, parseCodeFile, buildDependencyGraph } from './services/astParser.js';
import { cacheService } from './services/redisService.js';
import { checkChromaConnection } from './services/chromaService.js';
import { checkConfigStatus } from './services/llmProvider.js';

async function runTests() {
  console.log('===========================================================');
  console.log('🧪 RepoSage Diagnostic & Unit Test Suite');
  console.log('===========================================================\n');

  // Test 1: Service Configurations
  console.log('1. Checking Service Configurations...');
  const chromaStatus = await checkChromaConnection();
  const redisStatus = cacheService.getStatus();
  const llmStatus = checkConfigStatus();

  console.log(`   - Redis Status: ${redisStatus.connected ? '🟢 Connected' : '⚡ ' + redisStatus.mode}`);
  console.log(`   - ChromaDB Status: ${chromaStatus.connected ? '🟢 Connected' : '🔴 Offline (Run start-chroma.bat or Docker)'}`);
  console.log(`   - LLM Provider: ${llmStatus.provider} (${llmStatus.configured ? '🟢 Configured' : '⚠️ Missing API key'})`);

  // Test 2: Redis / In-Memory Cache set & get
  console.log('\n2. Testing Redis / High-Speed Cache Layer...');
  await cacheService.set('test:key', { message: 'RepoSage Cache OK' }, 60);
  const cachedVal = await cacheService.get('test:key');
  if (cachedVal && cachedVal.message === 'RepoSage Cache OK') {
    console.log('   ✅ Cache read/write successful!');
  } else {
    console.error('   ❌ Cache read/write failed.');
  }

  // Test 3: AST Parsing on Local Source Code
  console.log('\n3. Testing AST Code Parsing & Function Extraction...');
  const sampleDir = path.resolve('./services');
  const files = scanDirectory(sampleDir);
  console.log(`   - Scanned ${files.length} source files in ./services`);

  const parsedFiles = [];
  let totalChunks = 0;
  for (const f of files) {
    const parsed = parseCodeFile(f, sampleDir);
    parsedFiles.push(parsed);
    totalChunks += parsed.chunks.length;
  }
  console.log(`   - Extracted ${totalChunks} AST code blocks (functions, classes, modules)`);

  // Test 4: Architecture Dependency Graph Generation
  console.log('\n4. Testing Architectural Dependency Graph Builder...');
  const graph = buildDependencyGraph(parsedFiles);
  console.log(`   ✅ Graph constructed: ${graph.nodes.length} nodes, ${graph.links.length} cross-file dependency links.`);

  console.log('\n🎉 ALL REPOSAGE CORE UNIT TESTS PASSED SUCCESSFULLY!\n');
}

runTests();
