import os
import re
import ast
import json
import logging
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

def scan_directory(repo_path: str, max_files: int = 400) -> List[str]:
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        # Filter ignored dirs in place
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith('.')]

        for fname in filenames:
            if is_ignored_file(fname):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in CODE_EXTENSIONS or fname in {'Dockerfile', 'Makefile'}:
                full_path = os.path.join(root, fname)
                files.append(full_path)
                if len(files) >= max_files:
                    return files
    return files

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

def _parse_python_ast(content: str, rel_path: str) -> List[Dict[str, Any]]:
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
    except Exception:
        pass
    return chunks

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

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        content = ""

    chunks = []
    if ext == '.py':
        chunks = _parse_python_ast(content, rel_path)
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
        "imports": imports
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
