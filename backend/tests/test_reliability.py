import asyncio
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from git import Repo

from services import (
    chroma_service,
    rag_service,
    git_archaeology,
    tutorial_generator,
    pdf_service,
    mail_service,
    queue_service,
)
from services.ast_parser import (
    scan_directory_with_report,
    parse_code_file,
    _parse_js_ts_functions,
)
from main import app, _safe_uploaded_file_path
from fastapi.testclient import TestClient


class FakeQueryCollection:
    def __init__(self, distance):
        self.distance = distance

    def query(self, **_kwargs):
        return {
            "documents": [["cached question"]],
            "metadatas": [[{"question": "cached question", "answer": "cached answer"}]],
            "distances": [[self.distance]],
        }


class FakeResponse:
    content = "Grounded answer"


class FakeResponseText:
    def __init__(self, text):
        self.content = text
        self.text = text


class CapturingModel:
    def __init__(self):
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return FakeResponse()


class ReliabilityTests(unittest.TestCase):
    def test_retrieval_module_is_discovered_and_limit_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(401):
                target = root / "src" / "bulk" / f"file_{index:03}.py"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("def placeholder():\n    return 1\n", encoding="utf-8")
            retrieval = root / "src" / "retrieval" / "retriever.py"
            retrieval.parent.mkdir(parents=True, exist_ok=True)
            retrieval.write_text("def similarity_search(query):\n    return query\n", encoding="utf-8")

            files, complete = scan_directory_with_report(directory)
            self.assertIn("src/retrieval/retriever.py", complete["discoveredFiles"])
            self.assertEqual(len(files), 402)

            _, capped = scan_directory_with_report(directory, max_files=400)
            self.assertTrue(capped["truncated"])
            self.assertIn(
                {"path": "src/retrieval/retriever.py", "reason": "source_file_limit"},
                capped["skippedFiles"],
            )

    def test_coverage_context_exposes_retrieval_module_to_answer_generation(self):
        context = rag_service._build_coverage_context({
            "parsedFiles": ["src/agent/main.py", "src/retrieval/retriever.py", "src/retrieval/corpus_builder.py"],
            "summary": {"parsed": 3, "skipped": 0},
            "limits": {"maxSourceFiles": 2000},
            "truncated": False,
        })
        self.assertIn("src/retrieval/", context)
        self.assertIn("retriever.py", context)

    def test_ragignore_and_python_ast_fallback_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".ragignore").write_text("src/retrieval/*.py\n", encoding="utf-8")
            ignored = root / "src" / "retrieval" / "retriever.py"
            ignored.parent.mkdir(parents=True, exist_ok=True)
            ignored.write_text("def search(): pass\n", encoding="utf-8")
            malformed = root / "src" / "broken.py"
            malformed.write_text("def broken(:\n", encoding="utf-8")

            files, report = scan_directory_with_report(directory)
            self.assertNotIn(str(ignored), files)
            self.assertIn({"path": "src/retrieval/retriever.py", "reason": "ragignore"}, report["skippedFiles"])
            parsed = parse_code_file(str(malformed), directory)
            self.assertEqual(parsed["parseStatus"], "fallback")
            self.assertTrue(parsed["warnings"])
            self.assertTrue(parsed["chunks"])

    def test_semantic_similarity_thresholds_reject_low_match(self):
        with patch.object(chroma_service, "get_queries_collection", return_value=FakeQueryCollection(0.08)):
            strong = asyncio.run(chroma_service.find_semantic_query_match("repo", "question", threshold=0.88))
        with patch.object(chroma_service, "get_queries_collection", return_value=FakeQueryCollection(0.67)):
            weak = asyncio.run(chroma_service.find_semantic_query_match("repo", "question", threshold=0.80))
        self.assertTrue(strong["matched"])
        self.assertFalse(weak["matched"])
        self.assertAlmostEqual(weak["similarity"], 0.33)

    def test_source_change_produces_a_new_index_id(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "README.md"
            source.write_text("Escalation F1: 0.283", encoding="utf-8")
            first = rag_service._index_id([str(source)], directory)
            source.write_text("Escalation F1: 0.273", encoding="utf-8")
            second = rag_service._index_id([str(source)], directory)
        self.assertNotEqual(first, second)

    def test_missing_structural_retrieval_refuses_to_invent_signature(self):
        report = {"indexId": "current-index", "parsedFiles": ["src/retrieval/retriever.py"], "summary": {"parsed": 1, "skipped": 0}, "limits": {"maxSourceFiles": 2000}, "truncated": False}
        plain_file_chunk = {"type": "code", "content": "retrieval module overview", "metadata": {"filePath": "src/retrieval/retriever.py", "type": "block", "startLine": 1, "endLine": 2}}
        with patch.object(rag_service.cache_service, "get", new=AsyncMock(side_effect=[report, None, None])), \
             patch.object(rag_service, "find_semantic_query_match", new=AsyncMock(return_value=None)), \
             patch.object(rag_service, "search_codebase", new=AsyncMock(return_value={"codeMatches": [plain_file_chunk], "diffMatches": []})):
            result = asyncio.run(rag_service.query_codebase("repo", "What is the exact signature in retriever.py?"))
        self.assertTrue(result["signatureEvidenceMissing"])
        self.assertIn("can't state its actual function signatures", result["answer"])
        self.assertNotIn("retrieve(", result["answer"])

    def test_indirect_role_questions_route_to_structural_chunks(self):
        report = {"indexId": "current-index", "parsedFiles": ["src/policy/escalation_policy.py", "src/retrieval/retriever.py", "src/retrieval/corpus_builder.py", "src/evaluation/metrics.py"], "summary": {"parsed": 4, "skipped": 0}, "limits": {"maxSourceFiles": 2000}, "truncated": False}
        cases = [
            ("What component decides whether to auto-handle or escalate a request?", "src/policy/escalation_policy.py", "def evaluate(customer_text, classification, retrieved_evidence):"),
            ("Where does the system figure out how relevant historical evidence is before responding?", "src/retrieval/retriever.py", "def search(query, top_k, intent_filter, evaluation_mode):"),
            ("What part of the code prevents test data from leaking into training retrieval?", "src/retrieval/corpus_builder.py", "def build_corpus(exclude_test_data):"),
            ("How does the system score how similar two pieces of text are?", "src/evaluation/metrics.py", "def cosine_similarity(left, right):"),
        ]
        model = CapturingModel()

        async def route(_repo, _index, question):
            for known_question, file_path, _declaration in cases:
                if question == known_question:
                    return [{"filePath": file_path, "similarity": 0.91}]
            return []

        async def retrieve(**kwargs):
            path = kwargs["file_path_hints"][0]
            declaration = next(item[2] for item in cases if item[1] == path)
            return {"codeMatches": [{"type": "code", "content": declaration + "\n    return True", "metadata": {"filePath": path, "type": "function", "name": declaration.split("(")[0].replace("def ", ""), "startLine": 1, "endLine": 2}}], "diffMatches": []}

        with patch.object(rag_service.cache_service, "get", new=AsyncMock(return_value=report)), \
             patch.object(rag_service.cache_service, "set", new=AsyncMock(return_value=True)), \
             patch.object(rag_service, "find_semantic_query_match", new=AsyncMock(return_value=None)), \
             patch.object(rag_service, "find_relevant_files", side_effect=route), \
             patch.object(rag_service, "search_codebase", side_effect=retrieve), \
             patch.object(rag_service, "get_chat_model", return_value=model), \
             patch.object(rag_service, "store_query_cache", new=AsyncMock(return_value={"stored": True})):
            results = [asyncio.run(rag_service.query_codebase("repo", question)) for question, _, _ in cases]

        for result, (_, expected_file, declaration), prompt in zip(results, cases, model.prompts):
            self.assertEqual(result["codeCitations"][0]["filePath"], expected_file)
            self.assertIn(declaration, prompt)
            self.assertNotIn("I can't state its actual function signatures", result["answer"])

    def test_offline_low_similarity_returns_no_confident_answer(self):
        low_match = {"matched": False, "similarity": 0.33, "matchedQuestion": "unrelated", "answer": "unrelated answer"}
        with patch.object(rag_service.cache_service, "get", new=AsyncMock(return_value=None)), \
             patch.object(rag_service, "find_semantic_query_match", new=AsyncMock(return_value=low_match)), \
             patch.object(rag_service, "search_codebase", new=AsyncMock(return_value={"codeMatches": [], "diffMatches": []})), \
             patch.object(rag_service, "get_chat_model", side_effect=RuntimeError("offline")):
            result = asyncio.run(rag_service.query_codebase("repo", "new question"))
        self.assertTrue(result["offlineNoConfidentAnswer"])
        self.assertIn("No confident answer", result["answer"])
        self.assertNotIn("unrelated answer", result["answer"])

    def test_incremental_indexing_only_touches_modified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            f1 = root / "file1.py"
            f2 = root / "file2.py"
            f1.write_text("def fn1(): pass\n", encoding="utf-8")
            f2.write_text("def fn2(): pass\n", encoding="utf-8")

            # Round 1: Fresh ingest of both files
            with patch.object(rag_service, "store_code_chunks", new=AsyncMock(return_value={"storedCount": 2, "failedFiles": []})) as mock_store, \
                 patch.object(chroma_service, "store_diff_summaries", new=AsyncMock(return_value={"storedCount": 0})):
                res1 = asyncio.run(rag_service.ingest_codebase(directory))
                self.assertEqual(res1["filesCount"], 2)
                inc1 = res1["ingestionReport"]["incremental"]
                self.assertEqual(inc1["added"], 2)
                self.assertEqual(inc1["modified"], 0)
                self.assertEqual(inc1["unchanged"], 0)
                self.assertEqual(mock_store.call_count, 1)

            # Round 2: Modify only file2.py, leave file1.py unchanged
            f2.write_text("def fn2_modified(): pass\n", encoding="utf-8")

            with patch.object(rag_service, "store_code_chunks", new=AsyncMock(return_value={"storedCount": 1, "failedFiles": []})) as mock_store, \
                 patch.object(rag_service, "delete_repo_file_vectors", new=AsyncMock(return_value=1)) as mock_delete, \
                 patch.object(chroma_service, "store_diff_summaries", new=AsyncMock(return_value={"storedCount": 0})):
                res2 = asyncio.run(rag_service.ingest_codebase(directory))
                self.assertEqual(res2["filesCount"], 2)
                inc2 = res2["ingestionReport"]["incremental"]
                self.assertEqual(inc2["modified"], 1)
                self.assertEqual(inc2["unchanged"], 1)

                # Assert delete_repo_file_vectors was called for file2.py
                mock_delete.assert_called_once_with(directory, ["file2.py"])

                # Assert store_code_chunks was only called with chunks from file2.py
                mock_store.assert_called_once()
                chunks_stored = mock_store.call_args[0][1]
                stored_files = {c["filePath"] for c in chunks_stored}
                self.assertEqual(stored_files, {"file2.py"})

    def test_ssrf_protection_rejects_private_and_loopback_urls(self):
        with patch("git.Repo.clone_from") as mock_clone:
            with self.assertRaises(ValueError) as ctx1:
                rag_service.resolve_repo_path("http://localhost/evil.git")
            self.assertIn("https://", str(ctx1.exception))

            with self.assertRaises(ValueError) as ctx2:
                rag_service.resolve_repo_path("https://127.0.0.1/evil.git")
            self.assertIn("restricted IP", str(ctx2.exception))

            with self.assertRaises(ValueError) as ctx3:
                rag_service.resolve_repo_path("git@github.com:evil/repo.git")
            self.assertIn("https://", str(ctx3.exception))

            mock_clone.assert_not_called()

    def test_treesitter_and_regex_js_ts_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            ts_code = (
                "export class OrderManager {\n"
                "    async processOrder(orderId: string) {\n"
                "        return orderId;\n"
                "    }\n"
                "    static getStatus() {\n"
                "        return 'active';\n"
                "    }\n"
                "}\n"
                "export const calculateTax = (amount: number) => {\n"
                "    return amount * 0.1;\n"
                "};\n"
            )
            target = Path(directory) / "order.ts"
            target.write_text(ts_code, encoding="utf-8")

            parsed = parse_code_file(str(target), directory)
            self.assertEqual(parsed["parseStatus"], "parsed")
            chunk_names = [c["name"] for c in parsed["chunks"]]
            chunk_types = [c["type"] for c in parsed["chunks"]]

            self.assertIn("OrderManager", chunk_names)
            self.assertIn("class", chunk_types)
            self.assertTrue(any("processOrder" in n for n in chunk_names))
            self.assertTrue(any("calculateTax" in n for n in chunk_names))

            # Test regex fallback directly
            fallback_chunks = _parse_js_ts_functions(ts_code, "order.ts")
            fb_names = [c["name"] for c in fallback_chunks]
            self.assertIn("OrderManager", fb_names)
            self.assertIn("calculateTax", fb_names)

    def test_chroma_service_batching_and_dedup_and_delete(self):
        fake_coll = MagicMock()
        fake_coll.get.return_value = {"ids": ["chunk_1", "chunk_2"]}

        with patch.object(chroma_service, "get_code_collection", return_value=fake_coll):
            chunks = [
                {"name": "fn1", "type": "function", "startLine": 1, "endLine": 5, "code": "def fn1(): pass", "filePath": "src/a.py", "summary": "fn1"},
                {"name": "fn1", "type": "function", "startLine": 1, "endLine": 5, "code": "def fn1(): pass", "filePath": "src/a.py", "summary": "fn1"},
                {"name": "fn2", "type": "function", "startLine": 6, "endLine": 10, "code": "def fn2(): pass", "filePath": "src/b.py", "summary": "fn2"},
            ]
            res = asyncio.run(chroma_service.store_code_chunks("my_repo", chunks, "test_idx"))
            self.assertEqual(res["storedCount"], 2)
            fake_profile_coll = MagicMock()
            with patch.object(chroma_service, "get_file_profiles_collection", return_value=fake_profile_coll):
                del_res = asyncio.run(chroma_service.delete_repo_file_vectors("my_repo", ["src/a.py"]))
                self.assertEqual(del_res["deleted"], 1)
                fake_coll.delete.assert_called_with(where={"$and": [{"repoPath": "my_repo"}, {"filePath": "src/a.py"}]})
                fake_profile_coll.delete.assert_called_with(where={"$and": [{"repoPath": "my_repo"}, {"filePath": "src/a.py"}]})

    def test_git_archaeology_extraction_without_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repo.init(directory)
            file_path = Path(directory) / "test.txt"
            file_path.write_text("v1\n", encoding="utf-8")
            repo.index.add(["test.txt"])
            repo.index.commit("Initial commit")

            file_path.write_text("v2\n", encoding="utf-8")
            repo.index.add(["test.txt"])
            repo.index.commit("Feature update")

            with patch.dict(os.environ, {"GIT_ARCHAEOLOGY_LLM_SUMMARIES": "false"}):
                commits = asyncio.run(git_archaeology.analyze_git_archaeology(directory, max_commits=5))

            repo.close()

            self.assertEqual(len(commits), 2)
            self.assertEqual(commits[0]["rawMessage"], "Feature update")
            self.assertTrue(commits[0]["hash"])
            self.assertIn("v2", commits[0]["diffSnippet"])
            self.assertIn("Feature update", commits[0]["intentSummary"])

    def test_tutorial_generator_chapters_config_and_cache(self):
        self.assertEqual(len(tutorial_generator.CHAPTERS_CONFIG), 10)
        cached_data = {
            "repoName": "test-repo",
            "repoPath": "some/path",
            "totalChapters": 10,
            "chapters": [{"chapterIndex": i, "title": f"Ch {i}", "subtitle": "sub", "content": "body"} for i in range(1, 11)],
            "fullMarkdown": "# Blueprint"
        }
        events = []
        with patch.object(tutorial_generator, "get_cached_tutorial", new=AsyncMock(return_value=cached_data)), \
             patch.object(tutorial_generator, "get_chat_model") as mock_chat:
            result = asyncio.run(tutorial_generator.stream_full_tutorial("some/path", on_event=events.append))
            self.assertEqual(result["totalChapters"], 10)
            mock_chat.assert_not_called()
            self.assertEqual(events[0]["step"], "cached")

    def test_pdf_service_generation_and_text_sanitizer(self):
        raw = "Hello & <World> \x00\x1f\u2603"
        clean = pdf_service.sanitize_text(raw)
        self.assertIn("&amp;", clean)
        self.assertIn("&lt;", clean)
        self.assertIn("&gt;", clean)
        self.assertNotIn("\x00", clean)
        self.assertNotIn("\u2603", clean)

        dummy_tutorial = {
            "repoName": "SampleRepo",
            "chapters": [
                {
                    "chapterIndex": 1,
                    "title": "1. System Overview",
                    "subtitle": "Architecture Topology",
                    "content": "### Architecture\nThis is a test blueprint.\n```mermaid\ngraph TD\nA-->B\n```"
                }
            ]
        }
        pdf_bytes = pdf_service.generate_tutorial_pdf(dummy_tutorial)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_mail_service_simulated_delivery_when_unconfigured(self):
        with patch.dict(os.environ, {"EMAIL_USER": "", "SMTP_USER": ""}, clear=False):
            res = asyncio.run(mail_service.send_tutorial_email("developer@example.com", "TestRepo", b"%PDF-mock"))
            self.assertTrue(res["delivered"])
            self.assertTrue(res["simulated"])
            self.assertTrue(res["messageId"].startswith("sim_"))

    def test_queue_service_lifecycle_transitions(self):
        dummy_tut = {"repoName": "DemoRepo", "chapters": [{"chapterIndex": 1, "title": "Ch1", "content": "body"}]}
        with patch.object(queue_service, "get_cached_tutorial", new=AsyncMock(return_value=dummy_tut)), \
             patch.object(queue_service, "generate_tutorial_pdf", return_value=b"%PDF-demo"), \
             patch.object(queue_service, "send_tutorial_email", new=AsyncMock(return_value={"delivered": True, "messageId": "msg_123"})):

            async def run_queue_flow():
                queued = await queue_service.add_email_pdf_job("repo/path", "user@example.com")
                job_id = queued["jobId"]
                self.assertTrue(job_id.startswith("mem_"))

                # Poll until background worker completes execution
                status = None
                for _ in range(25):
                    status = await queue_service.get_job_status(job_id)
                    if status["state"] in ("completed", "failed"):
                        break
                    await asyncio.sleep(0.02)

                self.assertIsNotNone(status)
                self.assertEqual(status["state"], "completed")
                self.assertEqual(status["progress"], 100)
                self.assertEqual(status["result"]["messageId"], "msg_123")

            asyncio.run(run_queue_flow())

    def test_main_routes_and_security(self):
        # 1. Test _safe_uploaded_file_path security
        self.assertIsNone(_safe_uploaded_file_path("../../evil.py"))
        self.assertIsNone(_safe_uploaded_file_path("../secret.txt"))
        self.assertIsNone(_safe_uploaded_file_path("/etc/passwd"))
        self.assertIsNone(_safe_uploaded_file_path(".git/config"))
        self.assertIsNone(_safe_uploaded_file_path("app.exe"))
        self.assertIsNotNone(_safe_uploaded_file_path("src/index.js"))
        self.assertIsNotNone(_safe_uploaded_file_path("README.md"))
        self.assertIsNotNone(_safe_uploaded_file_path("Dockerfile"))

        # 2. Test /api/health and /api/chat via TestClient
        client = TestClient(app)
        health_resp = client.get("/api/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["status"], "ok")

        mock_chat_result = {
            "answer": "This is a mocked answer",
            "citations": [],
            "codeCitations": [],
            "gitCitations": [],
            "fromCache": False,
            "cacheType": "none",
            "repoPath": "test-repo"
        }
        with patch("main.resolve_repo_path", return_value="test-repo"), \
             patch("main.query_codebase", new=AsyncMock(return_value=mock_chat_result)):
            chat_resp = client.post("/api/chat", json={"repoPath": "test-repo", "question": "Explain architecture"})
            self.assertEqual(chat_resp.status_code, 200)
            self.assertEqual(chat_resp.json()["answer"], "This is a mocked answer")

    def test_incremental_indexing_unchanged_files_remain_retrievable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Two source files
            auth_file = root / "auth_module.py"
            payment_file = root / "payment_module.py"

            auth_file.write_text(
                "def authenticate_token(token_string):\n"
                "    \"\"\"Validates JWT authorization tokens.\"\"\"\n"
                "    return token_string.startswith('Bearer ')\n",
                encoding="utf-8"
            )
            payment_file.write_text(
                "def process_transaction(amount_cents):\n"
                "    \"\"\"Processes financial transaction charge.\"\"\"\n"
                "    return amount_cents > 0\n",
                encoding="utf-8"
            )

            # Ensure clean state in ChromaDB for this repo path
            asyncio.run(chroma_service.clear_repo_vectors(directory))

            try:
                # Round 1: Full ingestion with real ChromaDB vector storage (no mocks on store_code_chunks)
                res1 = asyncio.run(rag_service.ingest_codebase(directory))
                self.assertEqual(res1["filesCount"], 2)
                index_id_1 = res1["indexId"]
                self.assertTrue(index_id_1)

                # Round 2: Modify payment_module.py only; auth_module.py remains unchanged
                payment_file.write_text(
                    "def process_transaction_v2(amount_cents, gateway_token):\n"
                    "    \"\"\"Processes transaction through updated gateway.\"\"\"\n"
                    "    return amount_cents > 0 and bool(gateway_token)\n",
                    encoding="utf-8"
                )

                res2 = asyncio.run(rag_service.ingest_codebase(directory))
                self.assertEqual(res2["filesCount"], 2)
                self.assertEqual(res2["ingestionReport"]["incremental"]["modified"], 1)
                self.assertEqual(res2["ingestionReport"]["incremental"]["unchanged"], 1)
                index_id_2 = res2["indexId"]
                self.assertNotEqual(index_id_1, index_id_2)

                # Query for functionality in the UNCHANGED file (auth_module.py)
                retrieval = asyncio.run(chroma_service.search_codebase(
                    repo_path=directory,
                    question="How does authenticate_token validate the JWT authorization token?",
                    top_k=5,
                    index_id=index_id_2
                ))

                code_matches = retrieval.get("codeMatches", [])
                self.assertTrue(len(code_matches) > 0, "Retrieval should return matching code chunks")
                retrieved_files = {m.get("metadata", {}).get("filePath") for m in code_matches}
                self.assertIn("auth_module.py", retrieved_files, "Unchanged file must remain retrievable after incremental re-indexing")

                auth_chunks = [m for m in code_matches if m.get("metadata", {}).get("filePath") == "auth_module.py"]
                chunk_names = [c.get("metadata", {}).get("name") for c in auth_chunks]
                self.assertTrue(any("authenticate_token" in n for n in chunk_names))

            finally:
                asyncio.run(chroma_service.clear_repo_vectors(directory))

    def test_streaming_and_non_streaming_chat_share_cache_key_and_invalidate_on_reindex(self):
        repo_dir = "virtual/cached_repo"
        question = "How does the system handle user sessions?"

        report_v1 = {
            "indexId": "idx_run_001",
            "parsedFiles": ["session.py"],
            "summary": {"parsed": 1, "skipped": 0},
            "limits": {"maxSourceFiles": 2000},
            "truncated": False
        }
        chunk = {
            "type": "code",
            "content": "def manage_session(): return 'active'",
            "metadata": {"filePath": "session.py", "type": "function", "name": "manage_session", "startLine": 1, "endLine": 5}
        }

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=FakeResponse())
        
        async def fake_stream(_prompt):
            yield FakeResponse()
        mock_llm.astream = MagicMock(side_effect=fake_stream)

        with patch.object(rag_service, "get_chat_model", return_value=mock_llm), \
             patch.object(rag_service, "search_codebase", new=AsyncMock(return_value={"codeMatches": [chunk], "diffMatches": []})), \
             patch.object(rag_service, "find_semantic_query_match", new=AsyncMock(return_value=None)), \
             patch.object(rag_service, "find_relevant_files", new=AsyncMock(return_value=[])):

            # Clean cache state for test keys
            cache_k1 = rag_service._build_cache_key(repo_dir, "idx_run_001", question)
            asyncio.run(rag_service.cache_service.delete(cache_k1))
            asyncio.run(rag_service.cache_service.set(f"ingestion_report:{repo_dir}", report_v1))

            # Step 1: Call non-streaming query_codebase - populates the exact Redis cache
            res1 = asyncio.run(rag_service.query_codebase(repo_dir, question))
            self.assertEqual(res1["answer"], "Grounded answer")
            self.assertFalse(res1.get("fromCache", False))
            self.assertEqual(mock_llm.ainvoke.call_count, 1)
            self.assertEqual(mock_llm.astream.call_count, 0)

            # Step 2: Call streaming stream_query_codebase with identical inputs
            # It MUST hit the cache populated by query_codebase and NOT invoke LLM stream
            async def collect_stream():
                events = []
                async for event in rag_service.stream_query_codebase(repo_dir, question):
                    events.append(event)
                return events

            stream_events = asyncio.run(collect_stream())
            meta_event = next((e for e in stream_events if e.get("type") == "meta"), None)
            done_event = next((e for e in stream_events if e.get("type") == "done"), None)

            self.assertIsNotNone(meta_event, "Streaming should yield meta event")
            self.assertIsNotNone(done_event, "Streaming should yield done event")
            self.assertTrue(meta_event.get("fromCache"), "Streaming must return fromCache=True on shared cache hit")
            self.assertEqual(meta_event.get("cacheType"), "exact_redis")
            self.assertEqual(done_event.get("answer"), "Grounded answer")
            # LLM was NOT invoked again!
            self.assertEqual(mock_llm.ainvoke.call_count, 1)
            self.assertEqual(mock_llm.astream.call_count, 0)

            # Step 3: Simulate re-indexing (new indexId) -> cache invalidation
            report_v2 = {
                "indexId": "idx_run_002",
                "parsedFiles": ["session.py"],
                "summary": {"parsed": 1, "skipped": 0},
                "limits": {"maxSourceFiles": 2000},
                "truncated": False
            }
            asyncio.run(rag_service.cache_service.set(f"ingestion_report:{repo_dir}", report_v2))

            # Query via streaming again: must NOT serve the stale cached answer from idx_run_001
            stream_events_v2 = asyncio.run(collect_stream())
            meta_v2 = next((e for e in stream_events_v2 if e.get("type") == "meta"), None)
            self.assertFalse(meta_v2.get("fromCache", False), "After re-index, streaming must not serve stale cached answer")
            # LLM stream was invoked because cache key was for idx_run_002
            self.assertEqual(mock_llm.astream.call_count, 1)

            # Step 4: Simulate another re-indexing (idx_run_003) -> test non-streaming path
            report_v3 = {
                "indexId": "idx_run_003",
                "parsedFiles": ["session.py"],
                "summary": {"parsed": 1, "skipped": 0},
                "limits": {"maxSourceFiles": 2000},
                "truncated": False
            }
            asyncio.run(rag_service.cache_service.set(f"ingestion_report:{repo_dir}", report_v3))

            # Query via non-streaming again: must also NOT serve stale cache
            res_v3 = asyncio.run(rag_service.query_codebase(repo_dir, question))
            self.assertFalse(res_v3.get("fromCache", False), "After re-index, non-streaming must not serve stale cached answer")
            self.assertEqual(mock_llm.ainvoke.call_count, 2)

    def test_end_to_end_pipeline_multi_file_incremental_chat_stream_and_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Mix of Python and TypeScript files
            py_file = root / "service.py"
            ts_file = root / "handler.ts"

            py_file.write_text(
                "def calculate_tax(subtotal, tax_rate):\n"
                "    \"\"\"Calculates sales tax on order subtotal.\"\"\"\n"
                "    return subtotal * tax_rate\n",
                encoding="utf-8"
            )
            ts_file.write_text(
                "export class OrderHandler {\n"
                "    processPayment(orderId: string, amount: number) {\n"
                "        return { id: orderId, paid: amount };\n"
                "    }\n"
                "}\n",
                encoding="utf-8"
            )

            # Ensure clean vector store for directory
            asyncio.run(chroma_service.clear_repo_vectors(directory))

            try:
                # Step 1: Fresh ingest of multi-file repo (Python + TS)
                ingest1 = asyncio.run(rag_service.ingest_codebase(directory))
                self.assertEqual(ingest1["filesCount"], 2)
                index_id_1 = ingest1["indexId"]
                self.assertTrue(index_id_1)

                stats1 = asyncio.run(chroma_service.get_repo_vector_stats(directory))
                self.assertEqual(stats1["filesCount"], 2)
                self.assertGreaterEqual(stats1["count"], 2)

                # Set up dynamic mock LLM
                class DynamicChatModel:
                    def __init__(self):
                        self.ainvoke_calls = 0
                        self.astream_calls = 0

                    def _respond(self, prompt):
                        dev_q = prompt.split("Developer Question:")[-1] if "Developer Question:" in prompt else prompt
                        if "calculate_tax" in dev_q:
                            return FakeResponseText("The calculate_tax function computes tax using subtotal and rate.")
                        return FakeResponseText("The OrderHandler processes payment via processPayment.")

                    async def ainvoke(self, prompt):
                        self.ainvoke_calls += 1
                        return self._respond(prompt)

                    async def astream(self, prompt):
                        self.astream_calls += 1
                        yield self._respond(prompt)

                chat_model = DynamicChatModel()

                with patch.object(rag_service, "get_chat_model", return_value=chat_model):
                    # Step 2: Ask question via non-streaming query_codebase (/api/chat)
                    q1 = "How does calculate_tax work?"
                    res_chat1 = asyncio.run(rag_service.query_codebase(directory, q1))
                    self.assertIn("calculate_tax", res_chat1["answer"])
                    self.assertFalse(res_chat1.get("fromCache", False))
                    self.assertEqual(chat_model.ainvoke_calls, 1)
                    self.assertEqual(chat_model.astream_calls, 0)

                    # Step 3: Ask the SAME question via streaming stream_query_codebase (/api/chat-stream)
                    # Must return cached answer with SSE events without invoking LLM
                    stream_events = []
                    async def run_stream(q):
                        async for evt in rag_service.stream_query_codebase(directory, q):
                            stream_events.append(evt)
                    asyncio.run(run_stream(q1))

                    meta_evt = next((e for e in stream_events if e.get("type") == "meta"), None)
                    done_evt = next((e for e in stream_events if e.get("type") == "done"), None)
                    self.assertIsNotNone(meta_evt)
                    self.assertIsNotNone(done_evt)
                    self.assertTrue(meta_evt.get("fromCache"))
                    self.assertEqual(meta_evt.get("cacheType"), "exact_redis")
                    self.assertIn("calculate_tax", done_evt["answer"])
                    # Confirmed: no second LLM call!
                    self.assertEqual(chat_model.ainvoke_calls, 1)
                    self.assertEqual(chat_model.astream_calls, 0)

                    # Step 4: Modify ONE file (handler.ts), re-ingest (incremental)
                    ts_file.write_text(
                        "export class OrderHandler {\n"
                        "    processPaymentV2(orderId: string, amount: number, currency: string) {\n"
                        "        return { id: orderId, paid: amount, curr: currency, version: 2 };\n"
                        "    }\n"
                        "}\n",
                        encoding="utf-8"
                    )
                    ingest2 = asyncio.run(rag_service.ingest_codebase(directory))
                    self.assertEqual(ingest2["filesCount"], 2)
                    self.assertEqual(ingest2["ingestionReport"]["incremental"]["modified"], 1)
                    self.assertEqual(ingest2["ingestionReport"]["incremental"]["unchanged"], 1)
                    index_id_2 = ingest2["indexId"]
                    self.assertNotEqual(index_id_1, index_id_2)

                    # Step 5: Ask question about UNCHANGED file (service.py)
                    # Must still be retrieved with real citations!
                    res_unchanged = asyncio.run(rag_service.query_codebase(directory, "What are the arguments for calculate_tax?"))
                    citations_files = [c.get("filePath") for c in res_unchanged.get("codeCitations", [])]
                    self.assertTrue(any("service.py" in str(f) for f in citations_files), "Unchanged service.py must be cited")

                    # Step 6: Ask question about MODIFIED file (handler.ts)
                    # Answer must reflect new content and not old cache
                    res_modified = asyncio.run(rag_service.query_codebase(directory, "What methods does OrderHandler have?"))
                    self.assertFalse(res_modified.get("fromCache", False))
                    retrieved_chunks = [c.get("snippet", "") for c in res_modified.get("codeCitations", [])]
                    self.assertTrue(
                        any("processPaymentV2" in snip for snip in retrieved_chunks),
                        "Retrieval must return new processPaymentV2 from modified file"
                    )

                    # Step 7: Check get_repo_vector_stats reflects full current repo state accurately
                    stats2 = asyncio.run(chroma_service.get_repo_vector_stats(directory))
                    self.assertEqual(stats2["filesCount"], 2)
                    self.assertGreaterEqual(stats2["count"], 2)
                    self.assertFalse(stats2.get("truncated", False))

            finally:
                asyncio.run(chroma_service.clear_repo_vectors(directory))

    def test_concurrent_search_codebase_embedding_fallback_no_cross_talk(self):
        """
        Gap 2 verification test:
        Force Gemini offline, fire 10 concurrent search_codebase calls sharing
        ResilientEmbeddingFunction across asyncio.gather, verify zero exceptions,
        zero cross-talk between queries/results, and verify concurrent execution overlap.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            test_repo = os.path.abspath(temp_dir).replace("\\", "/")
            chunks = [
                {
                    "filePath": f"src/module_{i}.py",
                    "type": "function",
                    "startLine": 1,
                    "endLine": 10,
                    "code": f"def handle_feature_{i}():\n    return 'feature_{i}_payload'\n",
                    "summary": f"Implementation for feature {i}"
                }
                for i in range(10)
            ]

            async def run_test():
                with patch("requests.post", side_effect=Exception("Gemini Offline Force Fallback")):
                    # Index the 10 distinct chunks using local ONNX fallback
                    await chroma_service.store_code_chunks(test_repo, chunks, "idx_concur_test", clear_prior=True)

                    async def query_worker(i):
                        t_start = time.perf_counter()
                        res = await chroma_service.search_codebase(
                            repo_path=test_repo,
                            question=f"handle_feature_{i}",
                            top_k=1
                        )
                        t_end = time.perf_counter()
                        code_matches = res.get("codeMatches", [])
                        top_file = code_matches[0]["metadata"]["filePath"] if code_matches else None
                        top_code = code_matches[0].get("content", "") if code_matches else ""
                        return i, top_file, top_code, t_start, t_end

                    t0 = time.perf_counter()
                    results = await asyncio.gather(*[query_worker(i) for i in range(10)])
                    total_duration = time.perf_counter() - t0

                    # 1. Assert all 10 calls completed
                    self.assertEqual(len(results), 10)

                    # 2. Assert zero cross-talk: every query matched ONLY its own specific file & payload
                    for i, top_file, top_code, t_start, t_end in results:
                        self.assertEqual(top_file, f"src/module_{i}.py", f"Cross-talk detected on worker {i}: got {top_file}")
                        self.assertIn(f"feature_{i}_payload", top_code, f"Cross-talk in payload for worker {i}")

                    # 3. Assert execution was concurrent (overlapping time windows)
                    overlapping_pairs = sum(
                        1 for a in results for b in results
                        if a[0] < b[0] and max(a[3], b[3]) < min(a[4], b[4])
                    )
                    self.assertGreater(
                        overlapping_pairs, 0,
                        f"Queries must execute concurrently with overlapping time windows (total time: {total_duration:.3f}s)"
                    )
                    print(f"\n[GAP 2 CONCURRENCY TEST] 10 concurrent search_codebase queries finished in {total_duration:.3f}s with {overlapping_pairs} overlapping execution pairs. Zero cross-talk.")

            try:
                asyncio.run(run_test())
            finally:
                asyncio.run(chroma_service.clear_repo_vectors(test_repo))


if __name__ == "__main__":
    unittest.main()
