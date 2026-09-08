import PDFDocument from 'pdfkit';
import { renderMermaidToPng, extractMermaidBlocks } from '../utils/mermaidRenderer.js';
import { cleanMermaidCode } from '../utils/mermaidCleaner.js';

// A4 usable page height with margins (842pt page - 50pt top - 50pt bottom)
const PAGE_HEIGHT = 742;
const PAGE_MARGIN = 50;
const PAGE_WIDTH_USABLE = 495; // 595pt A4 width - 50pt left - 50pt right

/**
 * Sanitize text for 100% compatibility with standard PDF Type 1 fonts
 */
function sanitizePdfText(text) {
  if (!text) return '';
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/\u2026/g, '...')
    .replace(/[\u2022\u25CF\u25CB]/g, '*')
    .replace(/\u2192/g, '->')
    .replace(/\u2190/g, '<-')
    .replace(/\u21D2/g, '=>')
    .replace(/[\u2713\u2714]/g, '[x]')
    .replace(/[^\x20-\x7E\n\t]/g, '');
}

function cleanMarkdownText(text) {
  return sanitizePdfText(
    (text || '')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
  );
}

/**
 * Read PNG image dimensions from its binary header (bytes 16-23)
 * Returns { width, height } or null if parsing fails
 */
function getPngDimensions(buffer) {
  try {
    if (!buffer || buffer.length < 24) return null;
    // PNG signature is 8 bytes, IHDR chunk is next: 4 len + 4 type + 4 width + 4 height
    const width = buffer.readUInt32BE(16);
    const height = buffer.readUInt32BE(20);
    if (width > 0 && height > 0) return { width, height };
  } catch {}
  return null;
}

/**
 * Check if the current doc.y is near the top of a fresh page
 * (less than 100pt from page start = page is effectively empty)
 */
function isNearPageStart(doc) {
  return doc.y <= PAGE_MARGIN + 100;
}

/**
 * Add a new page only if we're NOT already at the start of a fresh page
 */
function addPageIfNeeded(doc) {
  if (!isNearPageStart(doc)) {
    doc.addPage();
  }
}

/**
 * Guard: if too close to bottom, add a new page.
 * Only fires if there's meaningful content below the threshold.
 */
function checkPageOverflow(doc, neededHeight = 60) {
  if (doc.y + neededHeight > PAGE_HEIGHT) {
    doc.addPage();
  }
}

/**
 * Pre-render all Mermaid diagrams in all chapters to PNG buffers.
 * Returns a Map<cleanedCode, Buffer|null>
 */
async function prerenderAllDiagrams(chapters) {
  const diagramMap = new Map();
  console.log('[PDF] Pre-rendering Mermaid diagrams to PNG images...');

  for (const chapter of chapters) {
    const blocks = extractMermaidBlocks(chapter.content || '');
    for (const rawCode of blocks) {
      const cleanedCode = cleanMermaidCode(rawCode);
      if (cleanedCode && !diagramMap.has(cleanedCode)) {
        try {
          const pngBuffer = await renderMermaidToPng(rawCode, {
            theme: 'default',
            backgroundColor: '#ffffff',
            width: 900,
            scale: 2
          });
          diagramMap.set(cleanedCode, pngBuffer || null);
          console.log(pngBuffer
            ? `[PDF] ✅ Diagram rendered (${pngBuffer.length} bytes)`
            : '[PDF] ⚠️  Diagram render returned null (will show code callout)'
          );
        } catch (err) {
          diagramMap.set(cleanedCode, null);
          console.warn(`[PDF] ⚠️  Diagram render error: ${err.message}`);
        }
      }
    }
  }

  console.log(`[PDF] Pre-render complete: ${diagramMap.size} unique diagrams`);
  return diagramMap;
}

/**
 * Generate a production-grade PDF with actual rendered Mermaid diagram images.
 */
export async function generateTutorialPdf(tutorial) {
  const chapters = tutorial.chapters || [];

  // Step 1: Pre-render all diagrams to PNG
  const diagramMap = await prerenderAllDiagrams(chapters);

  // Step 2: Build PDF
  return new Promise((resolve, reject) => {
    try {
      const doc = new PDFDocument({
        margin: PAGE_MARGIN,
        size: 'A4',
        bufferPages: true,
        info: {
          Title: `RepoSage Architecture: ${tutorial.repoName || 'Codebase'}`,
          Author: 'RepoSage Architectural Intelligence',
          Subject: 'Software Architecture Blueprint & Documentation'
        }
      });

      const buffers = [];
      doc.on('data', chunk => buffers.push(chunk));
      doc.on('end', () => resolve(Buffer.concat(buffers)));
      doc.on('error', err => reject(err));

      const repoName = cleanMarkdownText(tutorial.repoName || 'Codebase');

      // ── COVER PAGE ────────────────────────────────────────────────────────
      doc.rect(0, 0, doc.page.width, 130).fill('#09090b');

      doc.fillColor('#3b82f6').fontSize(11).font('Helvetica-Bold')
        .text('REPOSAGE ARCHITECTURAL INTELLIGENCE', 50, 35, { characterSpacing: 1 });

      doc.fillColor('#ffffff').fontSize(20).font('Helvetica-Bold')
        .text(`Architecture Blueprint: ${repoName}`, 50, 55);

      const renderedCount = [...diagramMap.values()].filter(Boolean).length;
      doc.fillColor('#a1a1aa').fontSize(9.5).font('Helvetica')
        .text(
          `Generated on ${new Date(tutorial.generatedAt || Date.now()).toLocaleDateString()}  •  ${chapters.length} Chapters  •  ${diagramMap.size} Diagrams (${renderedCount} rendered as images)`,
          50, 88
        );

      doc.y = 155;

      // ── TABLE OF CONTENTS ────────────────────────────────────────────────
      doc.fillColor('#09090b').fontSize(13).font('Helvetica-Bold')
        .text('Table of Contents', 50, 155);
      doc.moveDown(0.6);

      chapters.forEach((ch, idx) => {
        doc.fillColor('#3b82f6').fontSize(10).font('Helvetica-Bold')
          .text(`${idx + 1}. `, { continued: true })
          .fillColor('#27272a').font('Helvetica')
          .text(cleanMarkdownText(ch.title));
        doc.moveDown(0.3);
      });

      doc.moveDown(1.2);
      doc.strokeColor('#e4e4e7').lineWidth(1).moveTo(50, doc.y).lineTo(545, doc.y).stroke();

      // ── CHAPTERS ─────────────────────────────────────────────────────────
      chapters.forEach((ch, idx) => {
        // Start each chapter on a fresh page (skip addPage if already at top)
        addPageIfNeeded(doc);

        // Chapter accent bar
        doc.rect(50, doc.y, 495, 2).fill('#3b82f6');
        doc.moveDown(0.5);

        doc.fillColor('#3b82f6').fontSize(10).font('Helvetica-Bold')
          .text(`CHAPTER ${idx + 1}`, { characterSpacing: 1 });

        doc.fillColor('#09090b').fontSize(16).font('Helvetica-Bold')
          .text(cleanMarkdownText(ch.title));

        if (ch.subtitle) {
          doc.fillColor('#71717a').fontSize(10).font('Helvetica-Oblique')
            .text(cleanMarkdownText(ch.subtitle));
        }

        doc.moveDown(0.8);
        doc.strokeColor('#e4e4e7').lineWidth(0.5).moveTo(50, doc.y).lineTo(545, doc.y).stroke();
        doc.moveDown(0.8);

        renderChapterContent(doc, ch.content || '', diagramMap);
      });

      // ── FOOTERS ───────────────────────────────────────────────────────────
      const range = doc.bufferedPageRange();
      for (let i = range.start; i < range.start + range.count; i++) {
        doc.switchToPage(i);
        if (i > 0) {
          doc.fillColor('#a1a1aa').fontSize(8).font('Helvetica')
            .text(
              `RepoSage Blueprint  •  ${repoName}  •  Page ${i + 1} of ${range.count}`,
              50, 785, { align: 'center', width: 495 }
            );
        }
      }

      doc.end();
    } catch (err) {
      reject(err);
    }
  });
}

/**
 * Render chapter markdown content into PDFKit.
 * Mermaid blocks → PNG images (or code fallback).
 */
function renderChapterContent(doc, rawContent, diagramMap) {
  // Collect original mermaid blocks in order for lookup
  const mermaidOriginals = [];
  {
    const regex = /```mermaid\s*([\s\S]*?)```/gi;
    let m;
    while ((m = regex.exec(rawContent)) !== null) {
      mermaidOriginals.push(m[1].trim());
    }
  }

  const sanitized = sanitizePdfText(rawContent);
  const lines = sanitized.split('\n');
  let inCodeBlock = false;
  let codeBlockType = '';
  let codeBuffer = [];
  let mermaidBlockIdx = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // ── Code/Mermaid block fence ─────────────────────────────────────────
    if (trimmed.startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeBlockType = trimmed.replace('```', '').toLowerCase();
        codeBuffer = [];
      } else {
        inCodeBlock = false;
        const isMermaid = codeBlockType === 'mermaid';

        if (isMermaid) {
          const originalCode = mermaidOriginals[mermaidBlockIdx] || codeBuffer.join('\n');
          const cleanedCode = cleanMermaidCode(originalCode);
          const pngBuffer = diagramMap.get(cleanedCode) ?? null;
          mermaidBlockIdx++;
          renderDiagramBlock(doc, codeBuffer, cleanedCode, pngBuffer);
        } else {
          renderCodeBlock(doc, codeBuffer);
        }
        codeBuffer = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    // ── Regular markdown content ─────────────────────────────────────────
    // Only check overflow before content that needs space; NOT at every line
    if (trimmed.length > 0) {
      checkPageOverflow(doc, 40);
    }

    if (trimmed.startsWith('### ')) {
      doc.moveDown(0.5);
      checkPageOverflow(doc, 50);
      doc.fillColor('#18181b').fontSize(11.5).font('Helvetica-Bold')
        .text(cleanMarkdownText(trimmed.replace('### ', '')));
      doc.moveDown(0.3);
      doc.font('Helvetica');
    } else if (trimmed.startsWith('## ')) {
      doc.moveDown(0.7);
      checkPageOverflow(doc, 60);
      doc.fillColor('#09090b').fontSize(13).font('Helvetica-Bold')
        .text(cleanMarkdownText(trimmed.replace('## ', '')));
      doc.moveDown(0.4);
      doc.font('Helvetica');
    } else if (trimmed.startsWith('# ')) {
      doc.moveDown(1);
      checkPageOverflow(doc, 70);
      doc.fillColor('#000000').fontSize(14).font('Helvetica-Bold')
        .text(cleanMarkdownText(trimmed.replace('# ', '')));
      doc.moveDown(0.4);
      doc.font('Helvetica');
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      doc.fillColor('#27272a').fontSize(9).font('Helvetica')
        .text(`•  ${cleanMarkdownText(trimmed.slice(2))}`, 60, doc.y, { width: 485 });
      doc.moveDown(0.2);
    } else if (trimmed.length > 0) {
      doc.fillColor('#27272a').fontSize(9).font('Helvetica')
        .text(cleanMarkdownText(trimmed), 50, doc.y, { width: 495, lineGap: 1.5 });
      doc.moveDown(0.3);
    }
  }
}

/**
 * Embed a rendered Mermaid PNG image into the PDF.
 * Falls back to a code callout if image is unavailable.
 */
function renderDiagramBlock(doc, codeBuffer, cleanedCode, pngBuffer) {
  doc.moveDown(0.5);

  if (pngBuffer && pngBuffer.length > 0) {
    // ── Compute actual rendered image height based on PNG dimensions ──────
    const dims = getPngDimensions(pngBuffer);
    const maxW = PAGE_WIDTH_USABLE;   // 495pt
    const maxH = 280;                 // cap at 280pt to prevent page overflow

    let actualH = maxH;
    if (dims) {
      const scale = Math.min(maxW / dims.width, maxH / dims.height);
      actualH = Math.round(dims.height * scale);
    }

    const totalBlockH = 22 + actualH + 16; // label bar + image + spacing

    // Ensure there's room for the entire diagram block on this page
    checkPageOverflow(doc, totalBlockH);

    const blockY = doc.y;

    // Blue label bar
    doc.rect(50, blockY, 495, 18).fill('#1e3a5f');
    doc.fillColor('#60a5fa').fontSize(7.5).font('Helvetica-Bold')
      .text('ARCHITECTURAL DIAGRAM', 58, blockY + 5, { characterSpacing: 0.5 });

    const imgY = blockY + 22;

    try {
      doc.image(pngBuffer, 50, imgY, { fit: [maxW, maxH], align: 'center' });
      // Advance doc.y by actual rendered height (not maxH)
      doc.y = imgY + actualH + 14;
    } catch (imgErr) {
      console.warn('[PDF] Image embed failed:', imgErr.message);
      doc.y = blockY; // reset and fall through to code callout
      renderDiagramCodeFallback(doc, codeBuffer, cleanedCode);
      return;
    }
  } else {
    renderDiagramCodeFallback(doc, codeBuffer, cleanedCode);
  }

  doc.font('Helvetica');
  doc.moveDown(0.5);
}

/**
 * Styled code callout when Mermaid image render is unavailable
 */
function renderDiagramCodeFallback(doc, codeBuffer, cleanedCode) {
  const codeText = sanitizePdfText(cleanedCode || codeBuffer.join('\n'));
  const lineCount = Math.min((codeText.match(/\n/g) || []).length + 1, 16);
  const boxH = Math.min(lineCount * 10.5 + 22, 190);

  checkPageOverflow(doc, boxH + 40);
  const boxY = doc.y;

  doc.rect(50, boxY, 495, 18).fill('#1e293b');
  doc.fillColor('#38bdf8').fontSize(7.5).font('Helvetica-Bold')
    .text('ARCHITECTURAL DIAGRAM — Mermaid Source', 58, boxY + 5, { characterSpacing: 0.3 });

  doc.rect(50, boxY + 18, 495, boxH).fill('#0f172a');
  doc.fillColor('#94a3b8').fontSize(7).font('Courier')
    .text(codeText.slice(0, 1800), 58, boxY + 24, { width: 479, height: boxH - 8 });

  doc.y = boxY + boxH + 22;
}

/**
 * Standard non-Mermaid code block (light background)
 */
function renderCodeBlock(doc, codeBuffer) {
  const codeText = sanitizePdfText(codeBuffer.join('\n'));
  const lineCount = Math.min(codeBuffer.length, 14);
  const boxH = Math.min(lineCount * 11 + 18, 180);

  checkPageOverflow(doc, boxH + 30);
  doc.moveDown(0.3);
  const boxY = doc.y;

  doc.rect(50, boxY, 495, boxH).fill('#f4f4f5');
  doc.fillColor('#18181b').fontSize(7.5).font('Courier')
    .text(codeText.slice(0, 1400), 58, boxY + 6, { width: 479, height: boxH - 8 });

  doc.y = boxY + boxH + 10;
  doc.font('Helvetica');
}
