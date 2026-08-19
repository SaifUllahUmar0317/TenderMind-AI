import fitz  # PyMuPDF
import re
import string

class PDFAnalyzer:
    """
    Analyzes PDF document structure and evaluates native text quality per page.
    Determines whether a page should be extracted natively or sent to OCR.
    """

    MIN_CHAR_COUNT = 40        # Minimum characters to consider native text
    MIN_ALPHA_RATIO = 0.60     # Minimum 60% alphabetic characters
    MAX_GARBAGE_SCORE = 0.20   # Max 20% non-printable/strange characters

    @classmethod
    def evaluate_text_quality(cls, text: str) -> dict:
        """
        Calculates quality metrics on extracted text to check if it's meaningful text
        or garbled/gibberish output from bad PDF encoding.
        """
        if not text or not text.strip():
            return {
                "is_meaningful": False,
                "char_count": 0,
                "word_count": 0,
                "alpha_ratio": 0.0,
                "garbage_score": 1.0,
                "reason": "Empty text"
            }

        cleaned_text = text.strip()
        char_count = len(cleaned_text)
        words = re.findall(r'\b\w+\b', cleaned_text)
        word_count = len(words)

        if char_count == 0:
            return {
                "is_meaningful": False,
                "char_count": 0,
                "word_count": 0,
                "alpha_ratio": 0.0,
                "garbage_score": 1.0,
                "reason": "No valid characters"
            }

        # Calculate Alphabetic ratio
        alpha_chars = sum(1 for c in cleaned_text if c.isalpha())
        alpha_ratio = alpha_chars / char_count

        # Calculate Garbage score (unusual symbols, replacement chars like \ufffd, control chars)
        printable_set = set(string.printable)
        garbage_chars = sum(1 for c in cleaned_text if c not in printable_set or c == '\ufffd')
        garbage_score = garbage_chars / char_count

        # Check repeated character ratio for NON-FORMATTING characters (ignore underscores, dots, dashes, spaces)
        formatting_chars = set("_-.*= ~#|/\\:")
        non_format_reps = [
            len(match.group(0))
            for match in re.finditer(r'(.)\1{4,}', cleaned_text)
            if match.group(1) not in formatting_chars
        ]
        max_repeated = max(non_format_reps, default=0)
        has_excessive_repetition = max_repeated > 15

        # Decision heuristic: If page has sufficient readable words and low garbage, it is meaningful native text
        is_meaningful = True
        reasons = []

        if word_count < 10 and char_count < cls.MIN_CHAR_COUNT:
            is_meaningful = False
            reasons.append(f"Character count ({char_count}) and word count ({word_count}) below minimum threshold")

        elif word_count < 15 and alpha_ratio < 0.35:
            is_meaningful = False
            reasons.append(f"Alpha ratio ({alpha_ratio:.2f}) low with few words ({word_count})")

        if garbage_score > cls.MAX_GARBAGE_SCORE:
            is_meaningful = False
            reasons.append(f"Garbage score ({garbage_score:.2f}) exceeds threshold ({cls.MAX_GARBAGE_SCORE:.2f})")

        if has_excessive_repetition:
            is_meaningful = False
            reasons.append(f"Excessive character repetition detected ({max_repeated} repeated chars)")

        return {
            "is_meaningful": is_meaningful,
            "char_count": char_count,
            "word_count": word_count,
            "alpha_ratio": round(alpha_ratio, 3),
            "garbage_score": round(garbage_score, 3),
            "reason": "; ".join(reasons) if reasons else "High quality native text"
        }

    @classmethod
    def analyze_pdf(cls, pdf_path: str) -> dict:
        """
        Opens PDF and produces a per-page preliminary assessment.
        Returns document metadata and recommendation per page (native vs ocr).
        """
        page_analysis = []
        doc = None
        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            native_page_count = 0
            scanned_page_count = 0

            for page_num in range(page_count):
                page = doc[page_num]
                native_text = page.get_text("text") or ""
                images = page.get_images()

                quality = cls.evaluate_text_quality(native_text)

                if quality["is_meaningful"]:
                    recommended_method = "native"
                    native_page_count += 1
                else:
                    recommended_method = "ocr"
                    scanned_page_count += 1

                page_analysis.append({
                    "page_number": page_num + 1,
                    "recommended_method": recommended_method,
                    "has_images": len(images) > 0,
                    "image_count": len(images),
                    "native_text_quality": quality
                })

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
                "native_page_count": native_page_count,
                "scanned_page_count": scanned_page_count,
                "pages": page_analysis
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to analyze PDF: {str(e)}"
            }
        finally:
            if doc:
                doc.close()
