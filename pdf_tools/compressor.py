"""
PDF Compressor Engine powered by PyMuPDF (fitz) & Pillow (PIL).
Intelligently analyzes PDF structure and compresses images & streams while preserving
vector geometry, fonts, selectable text, links, and page layouts without black borders.
"""

import os
import io
import time
import fitz  # PyMuPDF
from PIL import Image
from typing import Dict, Any

def analyze_pdf(pdf_path: str) -> Dict[str, Any]:
    """Analyzes PDF structure, images, page count, fonts, metadata, and estimates potential compression."""
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    file_size = os.path.getsize(pdf_path)
    
    total_images = 0
    image_formats = set()
    has_selectable_text = False
    font_names = set()
    
    # Fast sampling step for multi-hundred page documents to ensure instant response
    step = 1 if page_count <= 100 else max(1, page_count // 50)
    unique_image_xrefs = set()
    
    for i in range(0, page_count, step):
        page = doc[i]
        text = page.get_text()
        if text and len(text.strip()) > 20:
            has_selectable_text = True
            
        try:
            font_list = page.get_fonts()
            for font in font_list:
                if len(font) > 3 and font[3]:
                    font_names.add(font[3])
        except Exception:
            pass
                
        try:
            image_list = page.get_images(full=False)
            for img_info in image_list:
                xref = img_info[0]
                unique_image_xrefs.add(xref)
                if len(img_info) > 8 and img_info[8]:
                    fmt = str(img_info[8])
                    if 'DCT' in fmt:
                        image_formats.add('JPEG')
                    elif 'Flate' in fmt:
                        image_formats.add('PNG')
                    elif 'JPX' in fmt:
                        image_formats.add('JP2')
        except Exception:
            pass
            
    total_images = len(unique_image_xrefs) if unique_image_xrefs else 0
    if page_count > 100 and step > 1 and unique_image_xrefs:
        total_images = len(unique_image_xrefs) * step

    metadata = doc.metadata or {}
    doc.close()
    
    if total_images > 0:
        est_reduction = "30% – 65%"
    elif file_size > 2 * 1024 * 1024:
        est_reduction = "15% – 35%"
    else:
        est_reduction = "5% – 20%"
        
    return {
        "page_count": page_count,
        "original_size": file_size,
        "total_images": total_images,
        "image_formats": list(image_formats) if image_formats else ["Embedded"],
        "has_selectable_text": has_selectable_text,
        "font_count": len(font_names),
        "is_scanned": not has_selectable_text and total_images > 0,
        "metadata_title": metadata.get("title") or "Untitled PDF",
        "producer": metadata.get("producer") or "PDF Document",
        "est_reduction": est_reduction
    }

def _process_single_image(doc, xref, smask_xref, max_dim, quality):
    """Worker function to compress an individual PDF image xref."""
    try:
        # Check if already a small image or small stream
        img_dict = doc.extract_image(xref)
        if not img_dict:
            return None, None

        img_bytes = img_dict.get("image")
        width = img_dict.get("width", 0)
        height = img_dict.get("height", 0)
        ext = img_dict.get("ext", "").lower()

        # If already small JPEG and dimensions are within max_dim, skip expensive re-encoding
        if ext in ("jpeg", "jpg") and max(width, height) <= max_dim and len(img_bytes) < 80 * 1024:
            return None, None

        # Extract pixmap from PyMuPDF
        if smask_xref > 0:
            try:
                pix = fitz.Pixmap(doc, xref)
                mask_pix = fitz.Pixmap(doc, smask_xref)
                pix = fitz.Pixmap(pix, mask_pix)
                png_bytes = pix.tobytes("png")
                pil_img = Image.open(io.BytesIO(png_bytes))
            except Exception:
                pil_img = Image.open(io.BytesIO(img_bytes))
        else:
            pil_img = Image.open(io.BytesIO(img_bytes))

        orig_w, orig_h = pil_img.size

        # Fast Box/Bilinear downscale for large images
        if max(orig_w, orig_h) > max_dim:
            pil_img.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)

        # Handle alpha channel cleanly onto white background
        if pil_img.mode in ("RGBA", "LA") or (pil_img.mode == "P" and "transparency" in pil_img.info):
            if pil_img.mode != "RGBA":
                pil_img = pil_img.convert("RGBA")
            bg = Image.new("RGB", pil_img.size, (255, 255, 255))
            bg.paste(pil_img, mask=pil_img.split()[3])
            pil_img = bg
        elif pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        # Fast JPEG encoding with sub-sampling for maximum speed
        buffer = io.BytesIO()
        pil_img.save(buffer, format="JPEG", quality=quality, optimize=False, subsampling=1)
        new_bytes = buffer.getvalue()

        # Only replace if new bytes are actually smaller
        if len(new_bytes) < len(img_bytes) * 0.95:
            return xref, new_bytes

        return None, None
    except Exception:
        return None, None

def compress_pdf(input_path: str, output_path: str, mode: str = "recommended") -> Dict[str, Any]:
    """
    High-performance multi-threaded PDF compression.
    Preserves text selectability, vector drawings, links, and eliminates black borders.
    """
    start_time = time.time()
    doc = fitz.open(input_path)
    original_size = os.path.getsize(input_path)
    
    # Configure compression parameters based on mode
    if mode == "maximum":
        max_dim = 1000
        quality = 50
    elif mode == "balanced":
        max_dim = 1400
        quality = 65
    elif mode == "high_quality":
        max_dim = 2000
        quality = 82
    else:  # 'recommended'
        max_dim = 1500
        quality = 72
        
    # Collect all unique image xrefs across document
    unique_images = {}
    for page in doc:
        for img_info in page.get_images(full=False):
            xref = img_info[0]
            smask = img_info[1] if len(img_info) > 1 else 0
            if xref not in unique_images:
                unique_images[xref] = smask

    # Process images with ThreadPoolExecutor for fast parallel compression on multi-core CPUs
    from concurrent.futures import ThreadPoolExecutor
    workers = min(8, max(2, (os.cpu_count() or 4)))
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_process_single_image, doc, xref, smask, max_dim, quality)
            for xref, smask in unique_images.items()
        ]
        for f in futures:
            try:
                res_xref, new_bytes = f.result()
                if res_xref and new_bytes:
                    doc.update_stream(res_xref, new_bytes)
                    doc.xref_set_key(res_xref, "SMask", "null")
                    doc.xref_set_key(res_xref, "Mask", "null")
                    doc.xref_set_key(res_xref, "Filter", "/DCTDecode")
            except Exception:
                pass

    # Fast save with deflate & garbage collection
    doc.save(
        output_path,
        garbage=3,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        clean=True
    )
    doc.close()
    
    compressed_size = os.path.getsize(output_path)
    processing_time = round(time.time() - start_time, 2)
    
    # If compressed size is somehow larger than original, copy original file
    if compressed_size >= original_size:
        import shutil
        shutil.copyfile(input_path, output_path)
        compressed_size = original_size
        
    space_saved = max(0, original_size - compressed_size)
    saved_percent = round((space_saved / original_size) * 100, 1) if original_size > 0 else 0.0
    
    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "space_saved": space_saved,
        "saved_percent": saved_percent,
        "processing_time": processing_time
    }
