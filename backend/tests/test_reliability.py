import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import chroma_service, rag_service
from services.ast_parser import scan_directory_with_report, parse_code_file


class FakeQueryCollection:
    def __init__(self, distance):
        self.distance = distance

    def query(self, **_kwargs):
        return {
            "documents": [["cached question"]],
            "metadatas": [[{"question": "cached question", "answer": "cached answer"}]],
            "distances": [[self.distance]],
        }


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


if __name__ == "__main__":
    unittest.main()
