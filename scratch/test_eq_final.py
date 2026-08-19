import sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
import config
from services.text_extractor import TextExtractor
from documents.equipment_parser import EquipmentScheduleParser

pdf_path = "uploads/2811823b-2a66-4fd4-895d-2f2de9c9fc60_tender2.pdf"
extracted = TextExtractor.extract_document_fast(pdf_path)

items = EquipmentScheduleParser.stitch_and_extract_items(extracted.get("pages", []))
print("Total items extracted:", len(items))
for idx, itm in enumerate(items):
    n = itm.get("name")
    q = itm.get("quantity")
    s = itm.get("specifications", [])
    print(f"Item {idx+1}: {n} | Qty: {q} | Specs count: {len(s)}")
    if s:
        print("  First spec:", s[0][:80])
