"""
PDF Combiner Engine powered by PyMuPDF (fitz), Pillow (PIL), and python-docx / MS Word COM.
Converts multi-format files (PDF, DOCX, DOC, JPG, PNG, WEBP) into individual page thumbnails,
supports page reordering, rotation, page deletion, insertion anywhere, and generates final PDF.
"""

import os
import uuid
import fitz  # PyMuPDF
from PIL import Image
from typing import List, Dict, Any

def convert_docx_to_pdf(docx_path: str, pdf_out_path: str) -> bool:
    """Converts DOCX / DOC file to PDF using win32com (MS Word COM) with python-docx fallback."""
    # Method 1: win32com (MS Word COM)
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(os.path.abspath(docx_path))
        doc.SaveAs(os.path.abspath(pdf_out_path), FileFormat=17) # 17 = wdFormatPDF
        doc.Close()
        word.Quit()
        pythoncom.CoUninitialize()
        if os.path.exists(pdf_out_path) and os.path.getsize(pdf_out_path) > 0:
            return True
    except Exception as e:
        print(f"Win32com docx conversion fallback triggered: {e}")

    # Method 2: Pure Python docx -> fitz PDF fallback
    try:
        import docx
        doc_obj = docx.Document(docx_path)
        pdf_doc = fitz.open()
        page = pdf_doc.new_page(width=595, height=842) # A4
        y = 50
        
        for para in doc_obj.paragraphs:
            text = para.text.strip()
            if not text:
                y += 10
                continue
            if y > 780:
                page = pdf_doc.new_page(width=595, height=842)
                y = 50
            page.insert_text((50, y), text[:120], fontsize=11, color=(0.1, 0.1, 0.1))
            y += 18
            
        pdf_doc.save(pdf_out_path)
        pdf_doc.close()
        return os.path.exists(pdf_out_path) and os.path.getsize(pdf_out_path) > 0
    except Exception as e:
        print(f"Python docx fallback error: {e}")
        return False

def process_file_into_pages(file_path: str, filename: str, thumb_dir: str) -> List[Dict[str, Any]]:
    """
    Parses PDF, Word (.docx/.doc), or Image file into individual page representations.
    Generates fast 150px JPEG thumbnails for UI display.
    """
    os.makedirs(thumb_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1].lower()
    pages_meta = []
    file_id = str(uuid.uuid4())[:8]

    pdf_to_read = file_path

    # Convert DOCX/DOC to PDF first if needed
    if ext in ('.docx', '.doc'):
        converted_pdf_path = os.path.join(os.path.dirname(file_path), f"conv_{file_id}.pdf")
        if convert_docx_to_pdf(file_path, converted_pdf_path):
            pdf_to_read = converted_pdf_path
            ext = '.pdf'

    if ext == '.pdf':
        try:
            doc = fitz.open(pdf_to_read)
            if doc.is_encrypted:
                doc.close()
                raise ValueError(f"'{filename}' is password-protected or encrypted.")
            if len(doc) == 0:
                doc.close()
                raise ValueError(f"'{filename}' has 0 pages or is empty.")
            
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=54)
                
                thumb_filename = f"thumb_{file_id}_p{page_idx+1}.jpg"
                thumb_path = os.path.join(thumb_dir, thumb_filename)
                pix.save(thumb_path)

                page_id = f"{file_id}_p{page_idx+1}"
                pages_meta.append({
                    "page_id": page_id,
                    "file_id": file_id,
                    "file_name": filename,
                    "file_path": pdf_to_read,
                    "is_image": False,
                    "source_page_idx": page_idx,
                    "page_num": page_idx + 1,
                    "total_pages": len(doc),
                    "thumbnail_filename": thumb_filename,
                    "rotation": 0
                })
            doc.close()
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Failed to read PDF '{filename}': {str(e)}")

    elif ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'):
        try:
            img = Image.open(file_path)
            img_rgb = img.convert('RGB')
            
            thumb_filename = f"thumb_{file_id}_img.jpg"
            thumb_path = os.path.join(thumb_dir, thumb_filename)
            img_rgb.thumbnail((200, 280), Image.Resampling.BILINEAR)
            img_rgb.save(thumb_path, format="JPEG", quality=75)

            page_id = f"{file_id}_img"
            pages_meta.append({
                "page_id": page_id,
                "file_id": file_id,
                "file_name": filename,
                "file_path": file_path,
                "is_image": True,
                "source_page_idx": 0,
                "page_num": 1,
                "total_pages": 1,
                "thumbnail_filename": thumb_filename,
                "rotation": 0
            })
        except Exception as e:
            raise ValueError(f"Failed to process image '{filename}': {str(e)}")
    else:
        raise ValueError(f"Unsupported file format for '{filename}'. Allowed: PDF, DOCX, DOC, JPG, PNG, WEBP, BMP.")

    return pages_meta

def combine_pages_to_pdf(page_specs: List[Dict[str, Any]], output_path: str) -> Dict[str, Any]:
    """
    High-Speed PDF Combiner Engine:
    Takes an ordered list of page operations, caches open document handles to avoid repeated disk I/O,
    and builds the final combined PDF document in milliseconds.
    """
    import time
    start_time = time.time()
    out_doc = fitz.open()

    # Cache open PDF document handles to eliminate opening the same PDF dozens of times
    open_doc_cache = {}

    try:
        for spec in page_specs:
            file_path = spec["file_path"]
            is_image = spec.get("is_image", False)
            source_idx = spec.get("source_page_idx", 0)
            rotation = spec.get("rotation", 0) % 360

            if is_image:
                img_doc = fitz.open(file_path)
                pdf_bytes = img_doc.convert_to_pdf()
                img_doc.close()

                img_pdf = fitz.open("pdf", pdf_bytes)
                page = out_doc.new_page(width=img_pdf[0].rect.width, height=img_pdf[0].rect.height)
                page.show_pdf_page(page.rect, img_pdf, 0)
                img_pdf.close()

                if rotation > 0:
                    out_doc[-1].set_rotation(rotation)
            else:
                if file_path not in open_doc_cache:
                    if os.path.exists(file_path):
                        open_doc_cache[file_path] = fitz.open(file_path)

                src_doc = open_doc_cache.get(file_path)
                if src_doc and 0 <= source_idx < len(src_doc):
                    out_doc.insert_pdf(src_doc, from_page=source_idx, to_page=source_idx)
                    if rotation > 0:
                        out_doc[-1].set_rotation(rotation)

        # Ultra-fast save with compression
        out_doc.save(output_path, deflate=True)
        total_pages = len(out_doc)
    finally:
        out_doc.close()
        for doc_handle in open_doc_cache.values():
            try:
                doc_handle.close()
            except Exception:
                pass

    output_size = os.path.getsize(output_path)
    processing_time = round(time.time() - start_time, 2)

    return {
        "total_pages": total_pages,
        "file_size": output_size,
        "processing_time": processing_time
    }
