import fitz  # PyMuPDF
import cv2
import numpy as np
from PIL import Image
import io
from config import DEFAULT_DPI

class ImagePreprocessor:
    """
    Renders PDF pages at high DPI (300+) and applies OpenCV computer vision filters
    to maximize OCR accuracy on scanned/fuzzy PDF pages.
    """

    @staticmethod
    def render_page_to_numpy(pdf_path: str, page_number_1indexed: int, dpi: int = DEFAULT_DPI) -> np.ndarray:
        """
        Renders a PDF page to an OpenCV BGR numpy array image at high DPI.
        """
        page_idx = page_number_1indexed - 1
        with fitz.open(pdf_path) as doc:
            page = doc[page_idx]
            pix = page.get_pixmap(dpi=dpi)
            
            # Convert pixmap bytes to PIL Image, then to numpy array (RGB to BGR)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            numpy_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            return numpy_img

    @staticmethod
    def deskew_image(image: np.ndarray) -> np.ndarray:
        """
        Detects text skew angle and rotates the image to align horizontally.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            # Invert colors so text is white on black background
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

            coords = np.column_stack(np.where(thresh > 0))
            if len(coords) < 100:
                return image

            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle

            # Ignore slight angles (< 0.5 degrees) or extreme false rotations (> 25 degrees)
            if abs(angle) < 0.5 or abs(angle) > 25.0:
                return image

            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return rotated
        except Exception:
            return image

    @classmethod
    def preprocess_for_ocr(cls, image: np.ndarray) -> np.ndarray:
        """
        Full OpenCV Preprocessing Pipeline:
        1. Grayscale Conversion
        2. Deskewing
        3. Contrast Enhancement (CLAHE)
        4. Noise Reduction
        5. Otsu Thresholding / Binarization
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 1. Deskewing first
        deskewed = cls.deskew_image(gray)

        # 2. Contrast enhancement via CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(deskewed)

        # 3. Noise reduction
        denoised = cv2.GaussianBlur(enhanced, (3, 3), 0)

        # 4. Otsu Binarization for crisp text separation
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return binary

    @classmethod
    def get_preprocessed_pil_image(cls, pdf_path: str, page_number_1indexed: int, dpi: int = DEFAULT_DPI) -> Image.Image:
        """
        Renders page, runs preprocessing pipeline, and returns PIL Image ready for Tesseract.
        """
        raw_img = cls.render_page_to_numpy(pdf_path, page_number_1indexed, dpi=dpi)
        processed_numpy = cls.preprocess_for_ocr(raw_img)
        pil_img = Image.fromarray(processed_numpy)
        return pil_img
