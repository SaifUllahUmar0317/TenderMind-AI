import sys, os
sys.path.insert(0, ".")
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
import config
from services.text_extractor import TextExtractor

pdf_path = 'uploads/2811823b-2a66-4fd4-895d-2f2de9c9fc60_tender2.pdf'
extracted = TextExtractor.extract_document_fast(pdf_path)

rows = extracted['pages'][7].get('tables_data', [])[0]

for r in rows:
    if not r or not any(r):
        continue
    cells = [str(c).strip() if c is not None else "" for c in r]
    h_text = " ".join(cells).lower()
    
    # Check if header
    if any(k in h_text for k in ["specification", "description", "item", "particulars", "nomenclature"]) and any(q in h_text for q in ["qty", "quantity", "unit", "rate", "total", "amount", "price"]):
        print("SKIPPED HEADER:", cells)
        continue
    if "total cost" in h_text or "grand total" in h_text or "total amount" in h_text:
        print("SKIPPED TOTAL:", cells)
        continue
        
    name = cells[0] if cells[0] else ""
    spec = cells[1] if len(cells) > 1 else ""
    unit = cells[2] if len(cells) > 2 else ""
    qty = cells[3] if len(cells) > 3 else ""
    
    if qty and unit:
        full_qty = f"{qty} {unit}".strip()
    elif qty:
        full_qty = qty
    elif unit:
        full_qty = unit
    else:
        full_qty = "Not specified"
        
    print(f"ITEM: {name} | QTY: {full_qty} | SPECS: {spec[:60]}...")
