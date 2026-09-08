export function cleanMermaidCode(rawCode) {
  if (!rawCode) return '';

  let code = rawCode
    .replace(/\r\n/g, '\n')
    // Remove wrapping fences if accidentally included
    .replace(/^```mermaid\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/```\s*$/i, '')
    // Replace smart/curly quotes with standard quotes
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2018\u2019]/g, "'")
    // Replace backslashes in paths with forward slashes
    .replace(/\\/g, '/');

  const lines = code.split('\n');
  let subgraphCounter = 1;
  const cleanedLines = [];

  for (let line of lines) {
    let l = line;

    // 1. Remove trailing semicolons
    l = l.replace(/;\s*$/, '');

    // 2. Convert // or # comments to %%
    if (/^\s*\/\//.test(l)) {
      l = l.replace(/^\s*\/\//, '%%');
    } else if (/^\s*#(?!\!)/.test(l)) {
      l = l.replace(/^\s*#/, '%%');
    }

    // 3. Fix subgraph with spaces in ID: e.g. "subgraph Business Logic Services ["Services Layer"]"
    const subgraphWithSpacesMatch = l.match(/^(\s*subgraph\s+)([^"\[\n]+?)(\s*\[.*\])/i);
    if (subgraphWithSpacesMatch) {
      const prefix = subgraphWithSpacesMatch[1];
      const rawId = subgraphWithSpacesMatch[2].trim();
      const bracketPart = subgraphWithSpacesMatch[3];
      if (rawId.includes(' ')) {
        const safeId = rawId.replace(/[^a-zA-Z0-9_]/g, '_');
        l = `${prefix}${safeId}${bracketPart}`;
      }
    }

    // 4. Fix subgraph with quoted title and no ID: e.g. "subgraph "Repository Root: jobfinder/""
    const subgraphQuotedMatch = l.match(/^(\s*subgraph\s+)"([^"]+)"/i);
    if (subgraphQuotedMatch) {
      const prefix = subgraphQuotedMatch[1];
      const title = subgraphQuotedMatch[2];
      const safeId = `sub_${subgraphCounter++}_${title.replace(/[^a-zA-Z0-9_]/g, '_').slice(0, 16)}`;
      l = `${prefix}${safeId} ["${title}"]`;
    }

    // 5. Fix unquoted node labels with special characters like (, ), :, /, & inside [...]
    // Avoid double quoting if already quoted
    l = l.replace(/([a-zA-Z0-9_-]+)\[([^"\]\n]*[\(\):/&][^"\]\n]*)\]/g, '$1["$2"]');

    // 6. Fix unquoted cylinder labels e.g. DB[(MongoDB (Mongoose Models))] -> DB[("MongoDB (Mongoose Models)")]
    l = l.replace(/([a-zA-Z0-9_-]+)\[\(([^"\)\n]+)\)\]/g, '$1[("$2")]');

    // 7. Fix unquoted decision/rhombus labels e.g. Check{Is Score >= Target?} -> Check{"Is Score >= Target?"}
    l = l.replace(/([a-zA-Z0-9_-]+)\{([^"\}\n]*[\(\):/?&><=][^"\}\n]*)\}/g, '$1{"$2"}');

    // 8. Fix unquoted rounded/pill nodes e.g. Start(Process (Init)) -> Start("Process (Init)")
    l = l.replace(/([a-zA-Z0-9_-]+)\(([^"\)\n]*[\(\):/&][^"\)\n]*)\)/g, '$1("$2")');

    cleanedLines.push(l);
  }

  return cleanedLines.join('\n').trim();
}
