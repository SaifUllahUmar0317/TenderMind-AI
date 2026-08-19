import re

class EquipmentScheduleParser:
    """
    Intelligent Table & Schedule Parser that stitches multi-page specification/BOQ tables
    and extracts atomic, structured equipment and material records with full attribute fidelity.
    """

    @classmethod
    def stitch_and_extract_items(cls, doc_pages: list) -> list:
        """
        Processes all pages in the document, identifies technical specification tables,
        merges multi-page row splits, deduplicates between Technical Spec tables and Financial BOQs,
        and returns structured records:
        [
            {
                "serial_number": 1,
                "name": "Air Conditioner 2 Ton (DC Inverter) Wall Mounted",
                "quantity": "16 Nos",
                "unit": "Nos",
                "specifications": [
                    "DC Inverter Technology",
                    "Cooling & Heating",
                    "Minimum cooling capacity: 24,000 BTU/hr"
                ],
                "source_pages": [14],
                "category": "Main Equipment",
                "raw_text": "..."
            }
        ]
        """
        all_tables_with_page = []
        for p_idx, page in enumerate(doc_pages):
            page_num = page.get("page_number", p_idx + 1)
            tables = page.get("tables_data", [])
            for t in tables:
                if t and len(t) > 0:
                    all_tables_with_page.append({"page": page_num, "rows": t})

        # Identify candidate specification tables
        spec_tables = []
        financial_tables = []

        for item in all_tables_with_page:
            p_num = item["page"]
            rows = item["rows"]
            if not rows:
                continue

            full_tab_text = " ".join([" ".join([str(c) for c in r if c is not None]) for r in rows[:3]]).lower()

            # Reject Date tables and Evaluation/Marking Criteria tables
            if "total marks" in full_tab_text or "sub marks" in full_tab_text or "sub parameter" in full_tab_text:
                continue
            if "dates" in full_tab_text and ("bid submission" in full_tab_text or "opening of technical" in full_tab_text):
                continue
            if "compliance to" in full_tab_text and "purchaser" in full_tab_text:
                continue

            is_financial = False
            is_spec = False

            if "unit rate" in full_tab_text or "total amount" in full_tab_text or "financial proposal" in full_tab_text:
                is_financial = True
            if any(k in full_tab_text for k in ["specification", "specifications", "item name", "equipment", "schedule of requirement", "boq", "bill of quantities"]) or (("qty" in full_tab_text or "quantity" in full_tab_text) and "description" in full_tab_text):
                is_spec = True

            if is_financial and not is_spec:
                financial_tables.append(item)
            elif is_spec:
                spec_tables.append(item)

        # Merge rows across consecutive specification table pages
        consolidated_rows = []
        
        # If we have dedicated specification tables, use them; otherwise use financial BOQ tables
        chosen_tables = spec_tables if spec_tables else financial_tables

        for tab_idx, tab_item in enumerate(chosen_tables):
            p_num = tab_item["page"]
            rows = tab_item["rows"]
            
            for r_idx, raw_row in enumerate(rows):
                if not raw_row or not any(raw_row):
                    continue

                cells = [str(c).strip() if c is not None else "" for c in raw_row]
                
                # Check if this row is a header row
                header_text = " ".join(cells).lower()
                if ("s#" in header_text or "s. #" in header_text or "s.no" in header_text or "sr. #" in header_text or "sr #" in header_text) and ("description" in header_text or "item" in header_text or "specification" in header_text):
                    continue
                
                # Check if this row is a continuation of previous row
                first_cell = cells[0] if len(cells) > 0 else ""
                second_cell = cells[1] if len(cells) > 1 else ""
                third_cell = cells[2] if len(cells) > 2 else ""
                
                is_continuation = False
                if not first_cell and not second_cell and len(consolidated_rows) > 0:
                    is_continuation = True
                elif not first_cell.isdigit() and len(cells) >= 3 and not second_cell and third_cell and len(consolidated_rows) > 0:
                    is_continuation = True

                if is_continuation and len(consolidated_rows) > 0:
                    last_rec = consolidated_rows[-1]
                    # Append text to previous record
                    continuation_text = " ".join([c for c in cells if c])
                    last_rec["raw_cells"].append(continuation_text)
                    if p_num not in last_rec["pages"]:
                        last_rec["pages"].append(p_num)
                else:
                    consolidated_rows.append({
                        "cells": cells,
                        "raw_cells": [c for c in cells if c],
                        "pages": [p_num]
                    })

        # Parse each consolidated row into structured equipment item
        extracted_items = []
        seen_names = {}
        
        for item_idx, r_dict in enumerate(consolidated_rows):
            cells = r_dict["cells"]
            pages = r_dict["pages"]
            
            s_num = ""
            name = ""
            qty = ""
            spec_blob = ""
            
            # Find serial number
            if len(cells) >= 1 and re.match(r'^\d+$', cells[0].strip()):
                s_num = cells[0].strip()
                cell_offset = 1
            else:
                s_num = str(item_idx + 1)
                cell_offset = 0
                
            rem_cells = cells[cell_offset:]
            if not rem_cells:
                continue

            # Look for quantity pattern in cells (e.g. "16 Nos", "100 Meter", "04 Nos", "1 Set", "1", "2")
            qty_idx = -1
            for idx, c in enumerate(rem_cells):
                c_clean = c.strip()
                if re.search(r'^(?:\d+\s*(?:nos|meter|meters|sets?|units?|pcs|pkg|pack|lot)|(?:0[1-9]|[1-9]\d*))$', c_clean, re.IGNORECASE) and len(c_clean) < 25:
                    qty = c_clean
                    qty_idx = idx
                    break

            if len(rem_cells) == 1:
                name = rem_cells[0]
            elif len(rem_cells) == 2:
                if qty_idx == 1:
                    name = rem_cells[0]
                elif qty_idx == 0:
                    qty = rem_cells[0]
                    name = rem_cells[1]
                else:
                    name = rem_cells[0]
                    spec_blob = rem_cells[1]
            elif len(rem_cells) >= 3:
                if qty_idx == 1:  # [Description, Quantity, Specification]
                    name = rem_cells[0]
                    qty = rem_cells[1]
                    spec_blob = " ".join(rem_cells[2:] + r_dict["raw_cells"][len(cells):])
                elif qty_idx == len(rem_cells) - 1:  # [Item Name, Specification, Quantity]
                    name = rem_cells[0]
                    spec_blob = " ".join(rem_cells[1:-1] + r_dict["raw_cells"][len(cells):])
                    qty = rem_cells[-1]
                elif qty_idx == 2 and len(rem_cells) >= 3:
                    name = rem_cells[0]
                    spec_blob = rem_cells[1]
                    qty = rem_cells[2]
                else:
                    name = rem_cells[0]
                    qty = rem_cells[1] if len(rem_cells) > 1 and len(rem_cells[1]) < 15 else ""
                    spec_blob = " ".join(rem_cells[2:] if qty else rem_cells[1:])

            # Also check if additional text was merged from continuation rows
            if len(r_dict["raw_cells"]) > len(cells):
                spec_blob += " " + " ".join(r_dict["raw_cells"][len(cells):])

            name_clean = name.replace('\n', ' ').strip()
            # If name has trailing page numbers or noise, clean it
            name_clean = re.sub(r'\s*\bPage\s*\d+\b', '', name_clean, flags=re.IGNORECASE).strip()

            # Normalize quantity: collapse embedded newlines/spaces
            qty = re.sub(r'\s+', ' ', qty.replace('\n', ' ')).strip()
            
            # If name is "Grand Total", skip
            if "grand total" in name_clean.lower() or "total amount" in name_clean.lower():
                continue

            if not name_clean or len(name_clean) < 3:
                continue

            # Parse specifications into clean bullet points
            spec_bullets = cls._parse_specification_bullets(spec_blob, name_clean)

            # Determine category: Main Equipment vs Installation / Materials
            category = cls._categorize_item(name_clean)

            norm_name = re.sub(r'[^a-z0-9]', '', name_clean.lower())
            
            # If item already exists from a previous table, enrich it with specs/pages if richer
            if norm_name in seen_names:
                existing_idx = seen_names[norm_name]
                existing_item = extracted_items[existing_idx]
                if len(spec_bullets) > len(existing_item["specifications"]):
                    existing_item["specifications"] = spec_bullets
                if (not existing_item["quantity"] or existing_item["quantity"] == "Not specified") and qty:
                    existing_item["quantity"] = qty
                for p in pages:
                    if p not in existing_item["source_pages"]:
                        existing_item["source_pages"].append(p)
                continue

            item_record = {
                "serial_number": str(len(extracted_items) + 1),
                "original_s_num": s_num,
                "name": name_clean,
                "quantity": qty if qty else "Not specified",
                "specifications": spec_bullets,
                "source_pages": pages,
                "category": category,
                "raw_text": f"{name_clean} | Qty: {qty} | Specs: {spec_blob}"
            }
            seen_names[norm_name] = len(extracted_items)
            extracted_items.append(item_record)

        # Cross-reference with Financial Proposal tables if quantity or items are missing
        if financial_tables:
            fin_items = cls._extract_from_financial_tables(financial_tables)
            for fin_item in fin_items:
                fin_norm = re.sub(r'[^a-z0-9]', '', fin_item["name"].lower())
                if fin_norm in seen_names:
                    idx = seen_names[fin_norm]
                    if (not extracted_items[idx]["quantity"] or extracted_items[idx]["quantity"] == "Not specified") and fin_item["quantity"]:
                        extracted_items[idx]["quantity"] = fin_item["quantity"]
                else:
                    # If this item was not in spec tables (e.g. items 7-11 in financial table only)
                    item_record = {
                        "serial_number": str(len(extracted_items) + 1),
                        "original_s_num": fin_item.get("serial_number", str(len(extracted_items) + 1)),
                        "name": fin_item["name"],
                        "quantity": fin_item["quantity"] if fin_item["quantity"] else "Not specified",
                        "specifications": fin_item.get("specifications", []),
                        "source_pages": fin_item["source_pages"],
                        "category": cls._categorize_item(fin_item["name"]),
                        "raw_text": fin_item.get("raw_text", "")
                    }
                    seen_names[fin_norm] = len(extracted_items)
                    extracted_items.append(item_record)

        return extracted_items

    @classmethod
    def _extract_from_financial_tables(cls, financial_tables: list) -> list:
        items = []
        for tab in financial_tables:
            p_num = tab["page"]
            rows = tab["rows"]
            for r in rows:
                if not r or not any(r):
                    continue
                cells = [str(c).strip() if c is not None else "" for c in r]
                header_text = " ".join(cells).lower()
                if "s#" in header_text and "description" in header_text:
                    continue
                
                s_num = cells[0] if len(cells) > 0 and cells[0].isdigit() else ""
                name = cells[1] if len(cells) > 1 else ""
                qty = cells[2] if len(cells) > 2 else ""
                
                name_clean = name.replace('\n', ' ').strip()
                if "grand total" in name_clean.lower() or not name_clean:
                    continue
                
                items.append({
                    "serial_number": s_num,
                    "name": name_clean,
                    "quantity": qty.replace('\n', ' ').strip() if qty else "Not specified",
                    "specifications": [],
                    "source_pages": [p_num],
                    "raw_text": f"{name_clean} | Qty: {qty}"
                })
        return items

    @classmethod
    def _parse_specification_bullets(cls, spec_text: str, item_name: str) -> list:
        if not spec_text or not spec_text.strip():
            return []

        # Replace unicode bullets with newline
        cleaned = spec_text.replace('•', '\n•').replace('·', '\n•')
        raw_lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
        
        bullets = []
        seen_bullets = set()
        for line in raw_lines:
            line_clean = re.sub(r'^[•\-\*\+\d\.\)]\s*', '', line).strip()
            if not line_clean:
                continue
            
            # Avoid repeating the item name as the first specification bullet if it's identical
            if line_clean.lower() == item_name.lower():
                continue
            
            # Avoid trailing table footers / page numbers
            if re.match(r'^\d+\s*$', line_clean) or line_clean.lower().startswith('annexure'):
                continue

            # Deduplicate: skip if same bullet already added (handles multi-page continuation overlap)
            norm = re.sub(r'\s+', ' ', line_clean.lower())
            if norm in seen_bullets:
                continue
            seen_bullets.add(norm)

            bullets.append(line_clean)

        # If no bullet points were found via split, try splitting by sentence or semicolons
        if not bullets and len(spec_text) > 15:
            sentences = re.split(r'(?<=[.;])\s+', spec_text)
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) > 5 and s_clean.lower() != item_name.lower():
                    bullets.append(s_clean)

        return bullets

    @classmethod
    def _categorize_item(cls, item_name: str) -> str:
        name_lower = item_name.lower()
        materials_keywords = [
            "cable", "wire", "pipe", "conduit", "aeroflex", "insulation", "duct",
            "fitting", "socket", "elbow", "clamp", "accessories", "installation of",
            "supply and installation of 3", "supply, installation and commissioning of copper"
        ]
        if any(k in name_lower for k in materials_keywords):
            return "Related Materials / Installation Items"
        return "Main Equipment"
