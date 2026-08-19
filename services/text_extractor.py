import fitz  # PyMuPDF
import io
from PIL import Image
from services.pdf_analyzer import PDFAnalyzer
from services.ocr_engine import OCREngine
from services.image_preprocessor import ImagePreprocessor
import config

class TextExtractor:
    """
    High-Performance Text & Table Extractor.
    Extracts text, structured blocks, and tables from PDFs using PyMuPDF's C++ engine,
    with seamless in-memory OCR fallback only for scanned pages.
    """

    @staticmethod
    def _format_table_as_markdown(table: list) -> str:
        """
        Converts a 2D matrix table into a clean Markdown table.
        """
        if not table or not any(table):
            return ""

        cleaned_table = []
        for row in table:
            if not row:
                continue
            cleaned_row = [str(cell).replace('\n', ' ').strip() if cell is not None else "" for cell in row]
            if any(cleaned_row):
                cleaned_table.append(cleaned_row)

        if not cleaned_table:
            return ""

        col_count = max(len(row) for row in cleaned_table)
        if col_count == 0:
            return ""

        padded_table = [row + [""] * (col_count - len(row)) for row in cleaned_table]

        header = padded_table[0]
        md_lines = []
        md_lines.append("| " + " | ".join(header) + " |")
        md_lines.append("| " + " | ".join(["---"] * col_count) + " |")

        for row in padded_table[1:]:
            md_lines.append("| " + " | ".join(row) + " |")

        return "\n" + "\n".join(md_lines) + "\n\n"

    @classmethod
    def extract_document_fast(cls, pdf_path: str, progress_callback=None, lang: str = "eng") -> dict:
        """
        High-speed single-pass document extractor.
        Opens the PDF exactly ONCE and extracts all pages in milliseconds.
        """
        doc = None
        extracted_pages = []
        full_text_parts = []
        total_word_count = 0
        total_char_count = 0
        native_page_count = 0
        scanned_page_count = 0

        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)

            TABLE_CUE_KEYWORDS = (
                "|", "\t", "s#", "s.", "sr.", "qty", "quantity", "specification",
                "description", "item", "unit", "total", "price", "rate", "amount",
                "schedule", "annexure", "boq", "bill of"
            )

            for page_idx in range(page_count):
                page = doc[page_idx]
                page_num = page_idx + 1

                if progress_callback and (page_num % 5 == 0 or page_num == page_count or page_num == 1):
                    progress_callback(page_num, page_count)

                # 1. High-speed PyMuPDF Block Extraction
                blocks = page.get_text("blocks", sort=True)
                block_texts = []
                headings = []
                for b in blocks:
                    if len(b) >= 5 and b[6] == 0:
                        txt = b[4].strip()
                        if txt:
                            block_texts.append(txt)
                            if len(txt) < 80 and txt.isupper():
                                headings.append(txt)

                pymupdf_text = "\n\n".join(block_texts)
                char_count = len(pymupdf_text)
                text_lower = pymupdf_text.lower()

                # 2. Smart table extraction — only run table finder when page text suggests tabular content
                table_markdown = ""
                raw_tables_list = []
                has_table_cues = any(cue in text_lower for cue in TABLE_CUE_KEYWORDS)

                if has_table_cues:
                    try:
                        table_finder = page.find_tables()
                        if table_finder and table_finder.tables:
                            for tab in table_finder.tables:
                                tab_data = tab.extract()
                                if tab_data:
                                    raw_tables_list.append(tab_data)
                                    tbl_md = cls._format_table_as_markdown(tab_data)
                                    if tbl_md:
                                        table_markdown += tbl_md
                    except Exception:
                        pass

                # 3. Direct Digital Text Acceptance (Instant path for digital PDFs)
                if char_count >= 20:
                    final_text = pymupdf_text
                    if table_markdown and table_markdown not in final_text:
                        final_text += "\n\n### Extracted Table Data:\n" + table_markdown

                    page_result = {
                        "page_number": page_num,
                        "text": final_text,
                        "method": "native",
                        "confidence": 100.0,
                        "source": "pymupdf_fast",
                        "quality": {"is_meaningful": True, "char_count": char_count, "word_count": len(pymupdf_text.split())},
                        "headings": headings[:3],
                        "tables": [table_markdown] if table_markdown else [],
                        "tables_data": raw_tables_list
                    }
                    native_page_count += 1

                else:
                    # 4. Fallback to OCR ONLY for truly scanned/empty image pages (char_count < 20)
                    page_result = None
                    try:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        pil_img = Image.open(io.BytesIO(img_bytes))

                        ocr_res = OCREngine.process_image(pil_img, lang=lang)
                        if ocr_res["success"] and ocr_res["text"].strip():
                            page_result = {
                                "page_number": page_num,
                                "text": ocr_res["text"],
                                "method": "ocr",
                                "confidence": ocr_res["confidence"],
                                "source": ocr_res["engine"],
                                "quality": {
                                    "is_meaningful": True,
                                    "char_count": ocr_res["char_count"],
                                    "word_count": ocr_res["word_count"],
                                    "reason": "OCR fallback"
                                },
                                "headings": [],
                                "tables": []
                            }
                            scanned_page_count += 1
                    except Exception:
                        pass

                    if not page_result:
                        page_result = {
                            "page_number": page_num,
                            "text": pymupdf_text or f"[Page {page_num}]",
                            "method": "native_low_quality",
                            "confidence": 50.0,
                            "source": "pymupdf_fallback",
                            "quality": {"is_meaningful": False, "char_count": char_count, "word_count": 0},
                            "headings": [],
                            "tables": []
                        }
                        native_page_count += 1

                extracted_pages.append(page_result)
                page_text = page_result.get("text", "")
                full_text_parts.append(f"--- Page {page_num} ---\n{page_text}")

                words_in_page = len(page_text.split())
                chars_in_page = len(page_text)
                total_word_count += words_in_page
                total_char_count += chars_in_page

            if native_page_count == page_count:
                overall_type = "text-based"
            elif scanned_page_count == page_count:
                overall_type = "scanned"
            else:
                overall_type = "mixed"

            return {
                "success": True,
                "page_count": page_count,
                "overall_type": overall_type,
                "word_count": total_word_count,
                "character_count": total_char_count,
                "pages": extracted_pages,
                "full_text": "\n\n".join(full_text_parts)
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Extraction error: {str(e)}"
            }
        finally:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

    @classmethod
    def extract_page_natively(cls, pdf_path: str, page_number_1indexed: int) -> dict:
        """Legacy single page helper."""
        res = cls.extract_document_fast(pdf_path)
        if res.get("success") and res.get("pages"):
            for p in res["pages"]:
                if p.get("page_number") == page_number_1indexed:
                    return {
                        "success": True,
                        "text": p.get("text", ""),
                        "source": p.get("source", "pymupdf"),
                        "quality": p.get("quality", {}),
                        "page_number": page_number_1indexed
                    }
        return {"success": False, "text": "", "source": "error", "quality": {}, "page_number": page_number_1indexed}
