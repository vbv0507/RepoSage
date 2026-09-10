import os
import re
import ast
import json
import logging
import fnmatch
from typing import List, Dict, Any, Set

logger = logging.getLogger("ast_parser")

IGNORED_DIRS = {
    'node_modules', '.git', 'dist', 'build', '.next', '.nuxt',
    'coverage', '.venv', 'venv', 'env', '__pycache__', '.idea',
    '.vscode', 'bin', 'obj', 'target', 'chroma_data', 'cloned_repos',
    'backend-node', 'dist_check'
}

IGNORED_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '.DS_Store', 'Thumbs.db', 'dump.rdb'
}

CODE_EXTENSIONS = {
    '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.py', '.go', '.java', '.cpp', '.c', '.h', '.cs',
    '.rs', '.php', '.rb', '.sql', '.json', '.yaml', '.yml', '.md'
}

def is_ignored_file(filename: str) -> bool:
    if filename in IGNORED_FILES:
        return True
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in [
        '.min.js', '.min.mjs', '.umd.js', '.bundle.js', '.chunk.js',
        '.min.css', '.map', '.lock', '.png', '.jpg', '.jpeg', '.svg',
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.pdf'
    ])

DEFAULT_MAX_SOURCE_FILES = 2000
MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024


def _load_ragignore(repo_path: str) -> List[str]:
    try:
        with open(os.path.join(repo_path, '.ragignore'), encoding='utf-8') as ignore_file:
            return [line.strip().replace('\\', '/') for line in ignore_file if line.strip() and not line.lstrip().startswith('#')]
    except OSError:
        return []


def _matches_ragignore(relative_path: str, patterns: List[str]) -> bool:
    path = relative_path.replace('\\', '/').lstrip('./')
    return any(fnmatch.fnmatch(path, pattern.lstrip('./')) for pattern in patterns)


def scan_directory_with_report(repo_path: str, max_files: int = DEFAULT_MAX_SOURCE_FILES) -> tuple[List[str], Dict[str, Any]]:
    """Discover source files deterministically and record every exclusion.

    The report is deliberately separate from logs: it is returned to the UI so
    an incomplete index can never masquerade as a complete repository view.
    """
    files: List[str] = []
    patterns = _load_ragignore(repo_path)
    report: Dict[str, Any] = {
        "discoveredFiles": [], "skippedFiles": [], "skippedDirectories": [],
        "limits": {"maxSourceFiles": max_files, "maxSourceFileBytes": MAX_SOURCE_FILE_BYTES},
        "truncated": False,
    }
    for root, dirs, filenames in os.walk(repo_path):
        dirs.sort()
        relative_root = os.path.relpath(root, repo_path)
        retained_dirs = []
        for directory in dirs:
            relative_dir = os.path.normpath(os.path.join(relative_root, directory)).replace('\\', '/')
            if directory in IGNORED_DIRS or directory.startswith('.'):
                report["skippedDirectories"].append({"path": relative_dir, "reason": "ignored_directory"})
            elif _matches_ragignore(f"{relative_dir}/", patterns) or _matches_ragignore(relative_dir, patterns):
                report["skippedDirectories"].append({"path": relative_dir, "reason": "ragignore"})
            else:
                retained_dirs.append(directory)
        dirs[:] = retained_dirs

        for fname in sorted(filenames):
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, repo_path).replace('\\', '/')
            if _matches_ragignore(rel_path, patterns):
                report["skippedFiles"].append({"path": rel_path, "reason": "ragignore"})
                continue
            if is_ignored_file(fname):
                report["skippedFiles"].append({"path": rel_path, "reason": "ignored_file_type"})
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in CODE_EXTENSIONS and fname not in {'Dockerfile', 'Makefile'}:
                continue
            try:
                file_size = os.path.getsize(full_path)
            except OSError as exc:
                report["skippedFiles"].append({"path": rel_path, "reason": f"stat_error: {exc}"})
                continue
            if file_size > MAX_SOURCE_FILE_BYTES:
                report["skippedFiles"].append({"path": rel_path, "reason": "file_size_limit"})
                continue
            if len(files) >= max_files:
                report["truncated"] = True
                report["skippedFiles"].append({"path": rel_path, "reason": "source_file_limit"})
                continue
            files.append(full_path)
            report["discoveredFiles"].append(rel_path)
    return files, report


def scan_directory(repo_path: str, max_files: int = DEFAULT_MAX_SOURCE_FILES) -> List[str]:
    """Backward-compatible file-only discovery API."""
    return scan_directory_with_report(repo_path, max_files=max_files)[0]

def _chunk_by_lines(content: str, rel_path: str, chunk_size: int = 50, overlap: int = 10) -> List[Dict[str, Any]]:
    lines = content.split('\n')
    chunks = []
    step = max(1, chunk_size - overlap)
    
    for i in range(0, len(lines), step):
        chunk_lines = lines[i:i + chunk_size]
        start_line = i + 1
        end_line = i + len(chunk_lines)
        code = '\n'.join(chunk_lines).strip()
        if not code:
            continue
        chunks.append({
            "name": f"{os.path.basename(rel_path)}:L{start_line}-L{end_line}",
            "type": "block",
            "startLine": start_line,
            "endLine": end_line,
            "code": code,
            "filePath": rel_path,
            "summary": f"Lines {start_line}-{end_line} of {rel_path}"
        })
    return chunks

def _parse_python_ast(content: str, rel_path: str) -> tuple[List[Dict[str, Any]], str | None]:
    chunks = []
    try:
        tree = ast.parse(content)
        lines = content.split('\n')
        
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = getattr(node, 'end_lineno', start + 10)
                code_snippet = '\n'.join(lines[start - 1:end]).strip()
                node_type = "class" if isinstance(node, ast.ClassDef) else "function"
                docstring = ast.get_docstring(node) or ""
                
                chunks.append({
                    "name": node.name,
                    "type": node_type,
                    "startLine": start,
                    "endLine": end,
                    "code": code_snippet,
                    "filePath": rel_path,
                    "summary": f"{node_type.capitalize()} `{node.name}`. {docstring[:150]}"
                })
    except (SyntaxError, ValueError, TypeError) as exc:
        return [], f"python_ast_error: {exc.msg if isinstance(exc, SyntaxError) else str(exc)}"
    return chunks, None

def _parse_js_ts_functions(content: str, rel_path: str) -> List[Dict[str, Any]]:
    chunks = []
    lines = content.split('\n')
    
    # Regex patterns for JS/TS functions and classes
    fn_pattern = re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(', re.MULTILINE)
    arrow_pattern = re.compile(r'^(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>', re.MULTILINE)
    class_pattern = re.compile(r'^(?:export\s+)?class\s+([a-zA-Z0-9_$]+)', re.MULTILINE)

    matched_indices = []
    for m in fn_pattern.finditer(content):
        matched_indices.append((m.start(), m.group(1), "function"))
    for m in arrow_pattern.finditer(content):
        matched_indices.append((m.start(), m.group(1), "arrow_function"))
    for m in class_pattern.finditer(content):
        matched_indices.append((m.start(), m.group(1), "class"))

    matched_indices.sort(key=lambda x: x[0])

    for start_pos, name, node_type in matched_indices[:20]:
        line_no = content[:start_pos].count('\n') + 1
        end_line = min(len(lines), line_no + 45)
        snippet = '\n'.join(lines[line_no - 1:end_line]).strip()
        chunks.append({
            "name": name,
            "type": node_type,
            "startLine": line_no,
            "endLine": end_line,
            "code": snippet,
            "filePath": rel_path,
            "summary": f"{node_type} `{name}` in {rel_path}"
        })

    return chunks

def parse_code_file(file_path: str, repo_path: str) -> Dict[str, Any]:
    rel_path = os.path.relpath(file_path, repo_path).replace('\\', '/')
    ext = os.path.splitext(file_path)[1].lower()

    read_error = None
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except OSError as exc:
        content = ""
        read_error = str(exc)

    chunks = []
    warnings = []
    if ext == '.py':
        chunks, ast_warning = _parse_python_ast(content, rel_path)
        if ast_warning:
            warnings.append(ast_warning)
    elif ext in {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'}:
        chunks = _parse_js_ts_functions(content, rel_path)

    # If no structural symbols were found, use standard line-based chunks
    if not chunks:
        chunks = _chunk_by_lines(content, rel_path)

    # Extract imports / dependencies for graph linking
    imports = []
    import_matches = re.findall(r'(?:import|from|require)\s*\(?[\'\"]([^\'\"]+)[\'\"]', content)
    for imp in import_matches:
        if imp.startswith('.'):
            # Resolve relative import to relative file path
            curr_dir = os.path.dirname(rel_path)
            resolved = os.path.normpath(os.path.join(curr_dir, imp)).replace('\\', '/')
            imports.append(resolved)
        else:
            imports.append(imp)

    return {
        "filePath": rel_path,
        "extension": ext,
        "size": len(content),
        "chunks": chunks,
        "imports": imports,
        "parseStatus": "read_error" if read_error else ("fallback" if warnings else "parsed"),
        "warnings": ([f"read_error: {read_error}"] if read_error else []) + warnings
    }

def build_dependency_graph(parsed_files: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    nodes = []
    links = []
    file_map = {f["filePath"]: f for f in parsed_files}

    for f in parsed_files:
        rel = f["filePath"]
        chunks = f.get("chunks", [])
        fn_count = sum(1 for c in chunks if c.get("type") in {"function", "arrow_function"})
        class_count = sum(1 for c in chunks if c.get("type") == "class")

        node_type = "code"
        if rel.endswith(('.json', '.yaml', '.yml', '.env')):
            node_type = "config"
        elif rel.endswith(('.md', '.txt')):
            node_type = "doc"

        nodes.append({
            "id": rel,
            "name": os.path.basename(rel),
            "path": rel,
            "type": node_type,
            "val": min(40, max(5, len(chunks) * 2)),
            "metrics": {
                "chunks": len(chunks),
                "functions": fn_count,
                "classes": class_count
            }
        })

    # Link extraction
    for f in parsed_files:
        src = f["filePath"]
        for imp in f.get("imports", []):
            # Try to match to an existing node
            matched_target = None
            for candidate in file_map.keys():
                candidate_no_ext = os.path.splitext(candidate)[0]
                if imp == candidate or imp == candidate_no_ext:
                    matched_target = candidate
                    break
                if imp.endswith(candidate) or candidate.endswith(imp):
                    matched_target = candidate
                    break

            if matched_target and matched_target != src:
                links.append({
                    "source": src,
                    "target": matched_target,
                    "type": "imports"
                })

    return {
        "nodes": nodes,
        "links": links
    }
