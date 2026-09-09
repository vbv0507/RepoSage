import re

def clean_mermaid_code(raw_code: str) -> str:
    if not raw_code:
        return ""

    code = raw_code.replace("\r\n", "\n")
    code = re.sub(r"^```mermaid\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"^```\s*", "", code)
    code = re.sub(r"```\s*$", "", code)
    code = code.replace("\u201c", '"').replace("\u201d", '"')
    code = code.replace("\u2018", "'").replace("\u2019", "'")
    code = code.replace("\\", "/")

    lines = code.split("\n")
    cleaned_lines = []
    subgraph_counter = 1

    for line in lines:
        l = line

        # 1. Remove trailing semicolons
        l = re.sub(r";\s*$", "", l)

        # 2. Convert // or # comments to %%
        if re.match(r"^\s*//", l):
            l = re.sub(r"^\s*//", "%%", l)
        elif re.match(r"^\s*#(?!\!)", l):
            l = re.sub(r"^\s*#", "%%", l)

        # 3. Fix subgraph with spaces in ID
        subgraph_spaces = re.match(r"^(\s*subgraph\s+)([^\"\[\n]+?)(\s*\[.*\])", l, re.IGNORECASE)
        if subgraph_spaces:
            prefix = subgraph_spaces.group(1)
            raw_id = subgraph_spaces.group(2).strip()
            bracket_part = subgraph_spaces.group(3)
            if " " in raw_id:
                safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)
                l = f"{prefix}{safe_id}{bracket_part}"

        # 4. Fix subgraph with quoted title and no ID
        subgraph_quoted = re.match(r"^(\s*subgraph\s+)\"([^\"]+)\"", l, re.IGNORECASE)
        if subgraph_quoted:
            prefix = subgraph_quoted.group(1)
            title = subgraph_quoted.group(2)
            safe_id = f"sub_{subgraph_counter}_{re.sub(r'[^a-zA-Z0-9_]', '_', title)[:16]}"
            subgraph_counter += 1
            l = f'{prefix}{safe_id} ["{title}"]'

        # 5. Fix unquoted node labels with special characters
        l = re.sub(r'([a-zA-Z0-9_-]+)\[([^"\]\n]*[\(\):/&][^"\]\n]*)\]', r'\1["\2"]', l)

        # 6. Fix unquoted cylinder labels
        l = re.sub(r'([a-zA-Z0-9_-]+)\[\(([^"\)\n]+)\)\]', r'\1[("\2")]', l)

        # 7. Fix unquoted decision/rhombus labels
        l = re.sub(r'([a-zA-Z0-9_-]+)\{([^"\}\n]*[\(\):/?&><=][^"\}\n]*)\}', r'\1{"\2"}', l)

        # 8. Fix unquoted rounded/pill nodes
        l = re.sub(r'([a-zA-Z0-9_-]+)\(([^"\)\n]*[\(\):/&][^"\)\n]*)\)', r'\1("\2")', l)

        cleaned_lines.append(l)

    return "\n".join(cleaned_lines).strip()

def clean_mermaid_in_markdown(markdown_content: str) -> str:
    if not markdown_content:
        return ""
    
    def replacer(match):
        code = match.group(1)
        cleaned = clean_mermaid_code(code)
        return f"```mermaid\n{cleaned}\n```"

    return re.sub(r"```mermaid\s*([\s\S]*?)```", replacer, markdown_content, flags=re.IGNORECASE)
