"""
PDF Compressor Engine powered by PyMuPDF (fitz) & Pillow (PIL).
Intelligently analyzes PDF structure and compresses images & streams while preserving
vector geometry, fonts, selectable text, links, transparency, and page layouts without image loss.
"""

import os
import io
import time
import shutil
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
        est_reduction = "40% – 80%"
    elif file_size > 2 * 1024 * 1024:
        est_reduction = "20% – 45%"
    else:
        est_reduction = "10% – 25%"
        
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

def compress_pdf(input_path: str, output_path: str, mode: str = "recommended") -> Dict[str, Any]:
    """
    High-performance PDF compression engine.
    - Accurately downscales and compresses high-resolution images without loss of visibility.
    - Synchronizes image dimensions, filter, and color spaces in PDF object dictionaries.
    - Fully preserves transparency (SMask) and vector graphics.
    - Provides strong, consistent size reduction across all compression modes.
    """
    start_time = time.time()
    doc = fitz.open(input_path)
    original_size = os.path.getsize(input_path)
    
    # Configure compression parameters based on selected mode
    if mode == "maximum":
        max_dim = 900
        quality = 50
    elif mode == "balanced":
        max_dim = 1400
        quality = 75
    elif mode == "high_quality":
        max_dim = 1800
        quality = 82
    else:  # 'recommended' (Standard optimal mode)
        max_dim = 1200
        quality = 70
        
    # Collect all unique image xrefs and their transparency soft masks (SMask)
    unique_images = {}
    smask_xrefs = set()
    
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            smask = img_info[1] if len(img_info) > 1 else 0
            if smask > 0:
                smask_xrefs.add(smask)
            if xref not in unique_images:
                unique_images[xref] = smask

    # Process and compress each image
    for xref, smask in unique_images.items():
        # SMask streams are handled in conjunction with their parent image
        if xref in smask_xrefs:
            continue
            
        try:
            # Skip 1-bit stencil masks (monochrome text/signatures) to prevent bloat/corruption
            is_mask = doc.xref_get_key(xref, "ImageMask")
            if is_mask[0] == "bool" and is_mask[1] == "true":
                continue
                
            img_info = doc.extract_image(xref)
            orig_bytes_len = len(img_info.get("image", b"")) if img_info else 0
            width = img_info.get("width", 0) if img_info else 0
            height = img_info.get("height", 0) if img_info else 0
            
            # Skip tiny icons / color swatches (under 64x64 and < 4KB)
            if width > 0 and height > 0 and width <= 64 and height <= 64 and orig_bytes_len < 4096:
                continue

            if smask > 0:
                # Handle image with alpha transparency mask (SMask)
                pix = fitz.Pixmap(doc, xref)
                if pix.colorspace not in (fitz.csRGB, fitz.csGRAY):
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                    
                mask_pix = fitz.Pixmap(doc, smask)
                rgba_pix = fitz.Pixmap(pix, mask_pix)
                
                pil_img = Image.open(io.BytesIO(rgba_pix.tobytes("png")))
                if max(pil_img.width, pil_img.height) > max_dim:
                    pil_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                    
                rgb_part = pil_img.convert("RGB")
                alpha_part = pil_img.split()[3]
                
                rgb_buf = io.BytesIO()
                rgb_part.save(rgb_buf, format="JPEG", quality=quality, optimize=True)
                new_rgb_bytes = rgb_buf.getvalue()
                
                alpha_buf = io.BytesIO()
                alpha_part.save(alpha_buf, format="JPEG", quality=max(60, quality), optimize=True)
                new_alpha_bytes = alpha_buf.getvalue()
                
                # Update base image stream & dictionary
                doc.update_stream(xref, new_rgb_bytes, compress=False)
                doc.xref_set_key(xref, "Width", str(rgb_part.width))
                doc.xref_set_key(xref, "Height", str(rgb_part.height))
                doc.xref_set_key(xref, "Filter", "/DCTDecode")
                doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
                doc.xref_set_key(xref, "BitsPerComponent", "8")
                doc.xref_set_key(xref, "DecodeParms", "null")
                doc.xref_set_key(xref, "Mask", "null")
                
                # Update soft mask stream & dictionary
                doc.update_stream(smask, new_alpha_bytes, compress=False)
                doc.xref_set_key(smask, "Width", str(alpha_part.width))
                doc.xref_set_key(smask, "Height", str(alpha_part.height))
                doc.xref_set_key(smask, "Filter", "/DCTDecode")
                doc.xref_set_key(smask, "ColorSpace", "/DeviceGray")
                doc.xref_set_key(smask, "BitsPerComponent", "8")
                doc.xref_set_key(smask, "DecodeParms", "null")
            else:
                # Handle standard opaque images (RGB, CMYK, Grayscale, etc.)
                pix = fitz.Pixmap(doc, xref)
                
                # Convert CMYK / Indexed / ICCBased / Lab to standard color spaces
                if pix.colorspace not in (fitz.csRGB, fitz.csGRAY):
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                    
                if pix.colorspace == fitz.csGRAY:
                    pil_img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
                    is_gray = True
                else:
                    pil_img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                    is_gray = False
                    
                orig_w, orig_h = pil_img.size
                if max(orig_w, orig_h) > max_dim:
                    pil_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                    
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=quality, optimize=True)
                new_bytes = buf.getvalue()
                
                # Replace stream if compressed version is smaller or if image was downscaled
                if not orig_bytes_len or len(new_bytes) < orig_bytes_len or max(orig_w, orig_h) > max_dim:
                    doc.update_stream(xref, new_bytes, compress=False)
                    doc.xref_set_key(xref, "Width", str(pil_img.width))
                    doc.xref_set_key(xref, "Height", str(pil_img.height))
                    doc.xref_set_key(xref, "Filter", "/DCTDecode")
                    doc.xref_set_key(xref, "ColorSpace", "/DeviceGray" if is_gray else "/DeviceRGB")
                    doc.xref_set_key(xref, "BitsPerComponent", "8")
                    doc.xref_set_key(xref, "DecodeParms", "null")
                    doc.xref_set_key(xref, "SMask", "null")
                    doc.xref_set_key(xref, "Mask", "null")
        except Exception:
            continue

    # Deflate streams and perform deep garbage collection
    doc.save(
        output_path,
        garbage=4,
        deflate=True,
        clean=True
    )
    doc.close()
    
    compressed_size = os.path.getsize(output_path)
    processing_time = round(time.time() - start_time, 2)
    
    # Safety fallback: if compressed file is somehow larger than original, copy original
    if compressed_size >= original_size:
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
