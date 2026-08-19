import re

class ExtractionAdapter:
    """
    Adapter that receives structured extraction output from the existing PDF extraction pipeline
    (PyMuPDF, pdfplumber, OpenCV, Tesseract OCR) and formats it into a normalized document structure
    for semantic chunking and RAG indexing.
    """

    @classmethod
    def adapt_extraction_payload(cls, extraction_result: dict, document_id: str, filename: str) -> dict:
        """
        Converts raw extraction payload into a structured document model with pages,
        sections, headers, and metadata.
        """
        raw_pages = extraction_result.get("pages", [])
        adapted_pages = []

        for p in raw_pages:
            page_num = p.get("page_number", 1)
            raw_text = p.get("text", "") or ""
            method = p.get("method", "native")
            confidence = p.get("confidence", 100.0)

            # Parse lines for sections/headings on this page
            lines = raw_text.split("\n")
            headings = []
            paragraphs = []
            tables = []

            in_table = False
            table_lines = []

            for line in lines:
                l_str = line.strip()
                if not l_str:
                    continue

                if l_str.startswith("|") and "|" in l_str[1:]:
                    in_table = True
                    table_lines.append(l_str)
                    continue
                else:
                    if in_table and table_lines:
                        tables.append("\n".join(table_lines))
                        table_lines = []
                        in_table = False

                # Detect heading
                if l_str.startswith("#"):
                    clean_h = l_str.lstrip("#").strip()
                    headings.append(clean_h)
                elif len(l_str) <= 60 and l_str.isupper() and len(l_str) > 3:
                    headings.append(l_str)
                else:
                    paragraphs.append(l_str)

            if in_table and table_lines:
                tables.append("\n".join(table_lines))

            adapted_pages.append({
                "page_number": page_num,
                "text": raw_text,
                "method": method,
                "confidence": confidence,
                "headings": headings,
                "paragraphs": paragraphs,
                "tables": tables,
                "tables_data": p.get("tables_data", [])
            })

        return {
            "document_id": document_id,
            "filename": filename,
            "page_count": extraction_result.get("page_count", len(raw_pages)),
            "word_count": extraction_result.get("word_count", 0),
            "character_count": extraction_result.get("character_count", 0),
            "overall_type": extraction_result.get("overall_type", "Text-Based"),
            "full_text": extraction_result.get("full_text", ""),
            "pages": adapted_pages
        }
