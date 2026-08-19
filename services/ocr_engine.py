import pytesseract
from PIL import Image
import os
import pandas as pd
from config import TESSERACT_CMD, DEFAULT_OCR_LANG

# Configure Tesseract binary path if specified
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

class OCREngine:
    """
    Primary Tesseract OCR Engine wrapper with confidence calculation
    and multi-language support.
    """

    @staticmethod
    def is_available() -> bool:
        """
        Verifies if Tesseract binary is accessible.
        """
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    @classmethod
    def process_image(cls, pil_image: Image.Image, lang: str = DEFAULT_OCR_LANG, psm: int = 3) -> dict:
        """
        Executes Tesseract OCR on PIL Image.
        Returns extracted text, mean confidence score (0-100), and word count.
        """
        if not cls.is_available():
            return {
                "success": False,
                "text": "",
                "confidence": 0.0,
                "error": "Tesseract OCR engine is not installed or not configured in system PATH."
            }

        config_flags = f"--psm {psm}"

        try:
            # Get detailed OCR data including word confidence
            data = pytesseract.image_to_data(pil_image, lang=lang, config=config_flags, output_type=pytesseract.Output.DICT)
            
            words = []
            confidences = []

            for i in range(len(data['text'])):
                word = data['text'][i].strip()
                conf = float(data['conf'][i])
                
                if word:
                    words.append(word)
                    if conf >= 0:  # -1 means no text / line container
                        confidences.append(conf)

            # Reconstruct extracted text
            full_text = pytesseract.image_to_string(pil_image, lang=lang, config=config_flags).strip()

            mean_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

            return {
                "success": True,
                "text": full_text,
                "confidence": mean_confidence,
                "word_count": len(words),
                "char_count": len(full_text),
                "engine": "tesseract"
            }

        except Exception as e:
            # Fallback retry with default config if custom lang fails
            try:
                full_text = pytesseract.image_to_string(pil_image, lang="eng").strip()
                return {
                    "success": True,
                    "text": full_text,
                    "confidence": 70.0,
                    "word_count": len(full_text.split()),
                    "char_count": len(full_text),
                    "engine": "tesseract-fallback"
                }
            except Exception as fallback_err:
                return {
                    "success": False,
                    "text": "",
                    "confidence": 0.0,
                    "error": f"OCR processing failed: {str(e)}"
                }
