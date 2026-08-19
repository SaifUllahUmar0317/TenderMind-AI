import os
import re
import json
from config import TEMP_FOLDER
from documents.equipment_parser import EquipmentScheduleParser

SUMMARIES_DIR = os.path.join(TEMP_FOLDER, "summaries")
os.makedirs(SUMMARIES_DIR, exist_ok=True)

class DocumentSummarizer:
    """
    Builds and stores comprehensive hierarchical document-level, section-level,
    and structured equipment records used for synthesis and high-accuracy technical extraction.
    """

    @staticmethod
    def _extract_clean_sentences(text: str, max_sentences: int = 12) -> list:
        """
        Extracts complete, meaningful sentences and key lines from a block of text.
        Preserves key lines, table rows, and numbers.
        """
        lines = text.split("\n")
        clean_lines = []

        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if re.match(r'^[A-Z\s&]{4,}$', line) and len(line) < 35:  # Heading
                continue
            if 'http' in line or '@' in line:
                continue
            clean_lines.append(line)
            if len(clean_lines) >= max_sentences:
                break

        return clean_lines

    @classmethod
    def generate_hierarchical_summary(cls, adapted_doc: dict) -> dict:
        """
        Extracts key sections, executive headers, page breakdowns, complete document structure,
        and atomic equipment specification records.
        """
        doc_id = adapted_doc.get("document_id", "doc_default")
        filename = adapted_doc.get("filename", "document.pdf")
        pages = adapted_doc.get("pages", [])
        page_count = len(pages)

        section_summaries = []
        metadata_kv = []
        extracted_tables = []
        seen_kv = set()
        all_headings = []

        for p in pages:
            p_num = p.get("page_number", 1)
            headings = p.get("headings", [])
            for h in headings:
                if h not in all_headings:
                    all_headings.append(h)

            # Collect page tables
            p_tables = p.get("tables", [])
            for tbl in p_tables:
                if tbl not in extracted_tables:
                    extracted_tables.append({"page": p_num, "table_md": tbl})

            txt = p.get("text", "").strip()
            if txt:
                sec_title = headings[0] if headings else f"Page {p_num}"
                clean_lines = cls._extract_clean_sentences(txt, max_sentences=12)

                # Robust key-value extraction with multi-line continuation handling
                lines = [l.strip() for l in txt.split("\n") if l.strip()]
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if ":" in line and len(line) < 140 and not line.startswith("|"):
                        parts = line.split(":", 1)
                        k = parts[0].strip()
                        v = parts[1].strip()

                        continuation_triggers = ("ph", "tel", "fax", "contact", "phone", "email", ",", "and", "or", "to", "at")
                        v_lower = v.lower()

                        while (i + 1 < len(lines)):
                            next_line = lines[i + 1].strip()
                            if next_line and ":" not in next_line and not next_line.startswith("|") and len(next_line) < 120:
                                should_append = (
                                    not v or
                                    v_lower.endswith(continuation_triggers) or
                                    next_line[0].isdigit() or
                                    re.match(r'^\d{3,}', next_line) or
                                    len(v) < 15
                                )
                                if should_append:
                                    if v_lower.endswith("ph") or v_lower.endswith("tel"):
                                        v = v + ":"
                                    v = f"{v} {next_line}".strip()
                                    i += 1
                                    v_lower = v.lower()
                                else:
                                    break
                            else:
                                break

                        # Clean up value and key
                        if k and v and len(k) < 50 and len(v) < 150:
                            k_clean = re.sub(r'^\W+|\W+$', '', k).title()
                            key_lower = k_clean.lower()
                            if key_lower not in seen_kv and len(k_clean) > 2:
                                seen_kv.add(key_lower)
                                metadata_kv.append({
                                    "key": k_clean,
                                    "value": v,
                                    "page": p_num
                                })

                    i += 1

                if clean_lines:
                    section_summaries.append({
                        "section": sec_title,
                        "page": p_num,
                        "summary": " ".join(clean_lines[:6]),
                        "lines": clean_lines
                    })

        # Extract structured equipment items via EquipmentScheduleParser
        structured_equipment = EquipmentScheduleParser.stitch_and_extract_items(pages)

        # Overall Comprehensive Document Summary Model
        doc_summary = {
            "document_id": doc_id,
            "filename": filename,
            "page_count": page_count,
            "word_count": adapted_doc.get("word_count", 0),
            "overall_type": adapted_doc.get("overall_type", "Text-Based"),
            "major_headings": all_headings,
            "metadata_kv": metadata_kv,
            "extracted_tables": extracted_tables,
            "section_summaries": section_summaries,
            "structured_equipment": structured_equipment
        }

        # Save summary JSON persistently
        summary_path = os.path.join(SUMMARIES_DIR, f"{doc_id}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(doc_summary, f, indent=2, ensure_ascii=False)

        return doc_summary

    @classmethod
    def get_summary(cls, document_id: str) -> dict:
        """
        Loads precomputed document summary if available.
        """
        summary_path = os.path.join(SUMMARIES_DIR, f"{document_id}.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
