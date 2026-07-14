"""Document parser — extract text from PDF and DOCX, split into clauses."""

import re
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from .db import get_db


def get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".docx", ".doc"):
        return "docx"
    else:
        return "unknown"


def extract_text_pdf(filepath: str) -> tuple[str, int]:
    """Extract text from PDF. Returns (full_text, page_count)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages.append(f"--- 第 {i+1} 页 ---\n{text}")
        return "\n\n".join(pages), len(reader.pages)
    except ImportError:
        raise RuntimeError("pypdf not installed")


def extract_text_docx(filepath: str) -> tuple[str, int]:
    """Extract text from DOCX. Returns (full_text, paragraph_count as page_estimate)."""
    try:
        from docx import Document
        doc = Document(filepath)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        # Rough page estimate: ~40 paragraphs per page
        return text, max(1, len(paragraphs) // 40 + 1)
    except ImportError:
        raise RuntimeError("python-docx not installed")


def extract_text(filepath: str, file_type: str) -> tuple[str, int]:
    """Extract text from any supported file type."""
    if file_type == "pdf":
        return extract_text_pdf(filepath)
    elif file_type == "docx":
        return extract_text_docx(filepath)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def split_into_clauses(text: str) -> list[tuple[str, int, str]]:
    """
    Split contract text into individual clauses.
    Returns list of (clause_text, page_number, section_title).
    """
    clauses = []

    # Track current page
    current_page = 1
    current_section = ""

    # Remove page markers and track pages
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        page_m = re.match(r"^--- 第 (\d+) 页 ---$", line.strip())
        if page_m:
            current_page = int(page_m.group(1))
            continue

        # Detect section titles (all-caps or numbered headings)
        section_m = re.match(
            r"^(第[一二三四五六七八九十]+[章节条]|第\d+[章节条]|[一二三四五六七八九十]+[、\.].{2,20}|"
            r"\d+[\.、].{2,30}|[A-Z\s]{4,})$",
            line.strip(),
        )
        if section_m and len(line.strip()) < 60:
            current_section = line.strip()
            clean_lines.append(line)
            continue

        clean_lines.append(line)

    full_text = "\n".join(clean_lines)

    # Try to split by clause markers: 第X条, X., X、
    # Pattern 1: Chinese "第X条" style
    pattern1 = re.split(r"(\n第[一二三四五六七八九十百千\d]+条[^，。\n]*)", full_text)

    if len(pattern1) > 1:
        # Reconstruct: each clause starts with its header
        i = 1
        while i < len(pattern1) - 1:
            header = pattern1[i].strip()
            body = pattern1[i + 1].strip() if i + 1 < len(pattern1) else ""
            clause_text = f"{header}\n{body}" if body else header
            if len(clause_text) > 10:
                clauses.append((clause_text.strip(), current_page, current_section))
            i += 2
    else:
        # Pattern 2: numbered items (1., 2. etc) or paragraph splits
        pattern2 = re.split(r"(\n\d+[、\.][^。\n]*)", full_text)
        if len(pattern2) > 1:
            i = 1
            while i < len(pattern2) - 1:
                header = pattern2[i].strip()
                body = pattern2[i + 1].strip() if i + 1 < len(pattern2) else ""
                clause_text = f"{header}\n{body}" if body else header
                if len(clause_text) > 10:
                    clauses.append((clause_text.strip(), current_page, current_section))
                i += 2
        else:
            # Fallback: split by double newline (paragraphs)
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            for para in paragraphs:
                if len(para) > 20:
                    clauses.append((para, current_page, current_section))

    # If too few clauses or too many, fallback to paragraph split
    if len(clauses) < 3:
        paragraphs = [p.strip() for p in full_text.split("\n") if p.strip()]
        clauses = []
        for para in paragraphs:
            if len(para) > 20:
                clauses.append((para, current_page, current_section))

    return clauses


def parse_and_store(filepath: str, doc_id: int) -> int:
    """Parse a document and store clauses in DB. Returns clause count."""
    file_type = get_file_type(filepath)
    text, page_count = extract_text(filepath, file_type)

    clauses = split_into_clauses(text)

    db = get_db()
    db.execute("UPDATE documents SET page_count = ?, status = 'parsed' WHERE id = ?",
               (page_count, doc_id))

    for idx, (clause_text, page_num, section_title) in enumerate(clauses):
        db.execute(
            "INSERT INTO clauses (doc_id, clause_index, content, page_number, section_title) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc_id, idx + 1, clause_text[:5000], page_num, section_title[:100]),
        )

    db.execute("UPDATE documents SET clause_count = ? WHERE id = ?", (len(clauses), doc_id))
    db.commit()
    return len(clauses)
