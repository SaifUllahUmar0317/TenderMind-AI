import uuid
import re

class SemanticChunker:
    """
    Structure-aware semantic chunker that splits document text into contextual chunks
    respecting section headings, annexures, specification tables, lists, and page boundaries while preserving metadata.
    """

    def __init__(self, target_chunk_size: int = 1200, chunk_overlap: int = 200):
        self.target_chunk_size = target_chunk_size
        self.chunk_overlap = chunk_overlap

    def create_chunks(self, adapted_doc: dict) -> list:
        """
        Creates metadata-rich semantic chunks from adapted document pages.
        Each chunk format:
        {
            "chunk_id": "...",
            "document_id": "...",
            "text": "...",
            "page_start": 1,
            "page_end": 1,
            "section": "...",
            "content_type": "technical_specification_table" | "paragraph" | "table",
            "source": "filename.pdf",
            "is_table": False
        }
        """
        document_id = adapted_doc.get("document_id", "doc_default")
        source_file = adapted_doc.get("filename", "document.pdf")
        pages = adapted_doc.get("pages", [])

        chunks = []
        current_chunk_text = ""
        current_page_start = 1
        current_page_end = 1
        current_section = "General"

        for page in pages:
            page_num = page.get("page_number", 1)
            raw_text = page.get("text", "").strip()

            if not raw_text:
                continue

            # Detect section from page text or headings
            detected_sec = self._detect_section_title(raw_text, page.get("headings", []))
            if detected_sec:
                current_section = detected_sec

            # Process tables separately to keep tables intact in single chunks
            for table_md in page.get("tables", []):
                if table_md.strip():
                    chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
                    
                    # Identify content type of table
                    is_spec_table = any(k in table_md.lower() for k in ["specification", "description", "total quantity", "item name", "boq", "s#"])
                    content_type = "technical_specification_table" if is_spec_table else "table"
                    
                    chunks.append({
                        "chunk_id": chunk_id,
                        "document_id": document_id,
                        "text": f"Table (Page {page_num} | Section: {current_section}):\n{table_md}",
                        "page_start": page_num,
                        "page_end": page_num,
                        "section": f"{current_section} (Table)",
                        "content_type": content_type,
                        "source": source_file,
                        "is_table": True
                    })

            # Process paragraph blocks
            paragraphs = page.get("paragraphs", [])
            if not paragraphs:
                paragraphs = [p for p in raw_text.split("\n\n") if p.strip()]

            for para in paragraphs:
                para_clean = para.strip()
                if not para_clean:
                    continue

                # Check if paragraph contains a major section marker (e.g. Annexure-II, Technical Specifications)
                para_sec = self._detect_section_title(para_clean, [])
                if para_sec:
                    current_section = para_sec

                if not current_chunk_text:
                    current_page_start = page_num
                    current_page_end = page_num
                    current_chunk_text = para_clean
                else:
                    # Check if adding paragraph exceeds target chunk size
                    if len(current_chunk_text) + len(para_clean) + 2 > self.target_chunk_size:
                        # Finalize current chunk
                        chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
                        chunks.append({
                            "chunk_id": chunk_id,
                            "document_id": document_id,
                            "text": current_chunk_text,
                            "page_start": current_page_start,
                            "page_end": current_page_end,
                            "section": current_section,
                            "content_type": "paragraph",
                            "source": source_file,
                            "is_table": False
                        })

                        # Overlap carryover
                        overlap_text = current_chunk_text[-self.chunk_overlap:] if len(current_chunk_text) > self.chunk_overlap else current_chunk_text
                        current_chunk_text = overlap_text + "\n\n" + para_clean
                        current_page_start = page_num
                        current_page_end = page_num
                    else:
                        current_chunk_text += "\n\n" + para_clean
                        current_page_end = page_num

        # Flush remaining text
        if current_chunk_text.strip():
            chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
            chunks.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": current_chunk_text.strip(),
                "page_start": current_page_start,
                "page_end": current_page_end,
                "section": current_section,
                "content_type": "paragraph",
                "source": source_file,
                "is_table": False
            })

        return chunks

    def _detect_section_title(self, text: str, page_headings: list) -> str:
        """Identifies prominent tender sections like Annexure-II, Technical Specifications, Bid Security, etc."""
        # 1. Check for specific Annexure or Section patterns
        annex_match = re.search(r'\b(annexure\s*[-–]\s*[A-Z0-9IVX]+|annex\s*[-–]\s*[A-Z0-9IVX]+|section\s*[-–]\s*[A-Z0-9IVX]+|schedule\s+of\s+requirements|technical\s+specifications?|financial\s+proposal|evaluation\s+criteria|tender\s+notice)\b[^\n]{0,60}', text, re.IGNORECASE)
        if annex_match:
            return annex_match.group(0).strip().title()

        # 2. Check uppercase headings
        for h in page_headings:
            if any(k in h.lower() for k in ["technical", "specification", "annexure", "schedule", "proposal", "criteria", "terms", "condition", "notice"]):
                return h.strip().title()

        return ""
