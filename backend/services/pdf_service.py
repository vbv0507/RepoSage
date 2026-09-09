import io
import re
from typing import Dict, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle, KeepTogether

def sanitize_text(text: str) -> str:
    if not text:
        return ""
    # XML entity escaping for ReportLab Paragraphs
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Strip non-ascii or non-printable
    return re.sub(r'[^\x20-\x7E\n\t]', '', t)

def generate_tutorial_pdf(tutorial: Dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#0F172A'),
        alignment=1 # Center
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#64748B'),
        alignment=1
    )

    h1_style = ParagraphStyle(
        'ChapterH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=14,
        spaceAfter=6
    )

    h2_style = ParagraphStyle(
        'ChapterH2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#334155'),
        spaceBefore=10,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )

    code_style = ParagraphStyle(
        'CodeSnippet',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#0F172A')
    )

    story = []

    repo_name = tutorial.get('repoName', 'Repository')
    chapters = tutorial.get('chapters', [])

    # Header / Title Page
    story.append(Spacer(1, 20))
    story.append(Paragraph("RepoSage Architectural Blueprint", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Codebase Engineering Textbook for: <b>{sanitize_text(repo_name)}</b>", subtitle_style))
    story.append(Paragraph(f"Publication-grade documentation | {len(chapters)} Chapters", subtitle_style))
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#3B82F6'), spaceAfter=20))

    # Table of contents
    story.append(Paragraph("Table of Contents", h1_style))
    for ch in chapters:
        toc_entry = f"<b>Chapter {ch.get('chapterIndex', '')}:</b> {sanitize_text(ch.get('title', ''))}"
        story.append(Paragraph(toc_entry, body_style))
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceAfter=20))

    # Chapters content
    for ch in chapters:
        story.append(Paragraph(sanitize_text(ch.get('title', '')), h1_style))
        if ch.get('subtitle'):
            story.append(Paragraph(f"<i>{sanitize_text(ch.get('subtitle', ''))}</i>", subtitle_style))
        story.append(Spacer(1, 6))

        content = ch.get('content', '')
        # Simple Markdown line processing
        lines = content.split('\n')
        in_code_block = False
        code_lines = []

        for line in lines:
            trimmed = line.strip()

            if trimmed.startswith('```'):
                if in_code_block:
                    # End code block
                    in_code_block = False
                    code_text = sanitize_text('\n'.join(code_lines[:25]))
                    if code_text:
                        p_code = Paragraph(code_text.replace('\n', '<br/>'), code_style)
                        t = Table([[p_code]], colWidths=[515])
                        t.setStyle(TableStyle([
                            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
                            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
                            ('LEFTPADDING', (0,0), (-1,-1), 8),
                            ('RIGHTPADDING', (0,0), (-1,-1), 8),
                            ('TOPPADDING', (0,0), (-1,-1), 6),
                            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                        ]))
                        story.append(t)
                        story.append(Spacer(1, 6))
                    code_lines = []
                else:
                    in_code_block = True
                    code_lines = []
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            if not trimmed:
                story.append(Spacer(1, 4))
                continue

            if trimmed.startswith('### '):
                story.append(Paragraph(sanitize_text(trimmed[4:]), h2_style))
            elif trimmed.startswith('## '):
                story.append(Paragraph(sanitize_text(trimmed[3:]), h1_style))
            elif trimmed.startswith('# '):
                story.append(Paragraph(sanitize_text(trimmed[2:]), h1_style))
            elif trimmed.startswith('- ') or trimmed.startswith('* '):
                bullet_text = f"&bull; {sanitize_text(trimmed[2:])}"
                story.append(Paragraph(bullet_text, body_style))
            else:
                story.append(Paragraph(sanitize_text(trimmed), body_style))

        story.append(Spacer(1, 15))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceAfter=15))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
