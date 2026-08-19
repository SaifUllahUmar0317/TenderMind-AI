import re
import urllib.parse
from typing import Dict, Any, List, Optional
from documents.summarizer import DocumentSummarizer

class ProductSearchHandler:
    """
    Handles inline product and equipment search requests inside the Tender Assistant chatbot.
    Extracts specifications from the RAG knowledge base and generates high-precision Google Search links.
    """

    PRODUCT_INTENT_PATTERNS = [
        r'\b(?:find|search|give|get|show|provide|fetch)\b.*?\b(?:product|products|equipment|hardware|item|items|model|models|device|devices|links?|url|urls)\b',
        r'\b(?:where|how)\b.*?\b(?:buy|purchase|order|get|procure|find)\b',
        r'\b(?:supplier|suppliers|distributor|distributors|vendor|vendors|dealer|dealers)\b',
        r'\b(?:search|google|find)\b.*?\b(?:online|web|google|market|pakistan)\b',
        r'\b(?:exact|matching|commercial)\b.*?\b(?:product|products|model|models|equipment)\b',
        r'\blinks?\b.*?\b(?:products?|equipment|items?|models?|hardware|these)\b',
        r'\b(?:products?|equipment|items?)\b.*?\blinks?\b',
        r'\bonline\s+links?\b',
        r'\bgoogle\s+search\b',
        r'\b(?:links?|urls?)\s+for\b'
    ]

    @classmethod
    def is_product_search_intent(cls, question: str) -> bool:
        """Determines if the user's query is asking to find products or equipment online."""
        q = question.lower().strip()
        
        # Check against regex patterns
        for pat in cls.PRODUCT_INTENT_PATTERNS:
            if re.search(pat, q, re.IGNORECASE):
                return True
        return False

    ICON_MAP = {
        "computer": "💻",
        "desktop": "🖥️",
        "laptop": "💻",
        "printer": "🖨️",
        "scanner": "📠",
        "microscope": "🔬",
        "camera": "📷",
        "ups": "⚡",
        "server": "🗄️",
        "switch": "🔌",
        "router": "📡",
        "monitor": "🖥️",
        "screen": "📺",
        "refrigerator": "❄️",
        "centrifuge": "🧪",
        "speaker": "🔊",
        "led": "💡",
        "hardware": "⚙️",
        "equipment": "📦",
        "device": "📱",
        "machine": "⚙️",
        "default": "📦"
    }

    @classmethod
    def _get_icon_for_item(cls, name: str) -> str:
        name_lower = name.lower()
        for key, icon in cls.ICON_MAP.items():
            if key in name_lower:
                return icon
        return cls.ICON_MAP["default"]

    @classmethod
    def _clean_query_string(cls, item_name: str, specifications: List[str]) -> str:
        """
        Builds a concise, keyword-rich Google search query without boilerplate words.
        """
        # Filter out noisy boilerplate phrases
        stopwords = {
            "the", "and", "or", "with", "for", "to", "in", "of", "a", "an",
            "required", "requirement", "requirements", "minimum", "maximum",
            "tender", "bidding", "contractor", "bidder", "supply", "installation",
            "accordance", "specifications", "specification", "compliance", "standard",
            "shall", "must", "be", "as", "per", "schedule", "item", "qty", "quantity", "nos"
        }

        combined_specs = []
        for s in specifications:
            s_clean = re.sub(r'[^\w\s\.\-\/\+]', ' ', str(s))
            words = s_clean.split()
            meaningful_words = [w for w in words if w.lower() not in stopwords and len(w) > 1]
            if meaningful_words:
                combined_specs.append(" ".join(meaningful_words[:5]))

        specs_str = " ".join(combined_specs[:4])
        query_text = f"{item_name} {specs_str}".strip()
        
        # Limit to ~10-12 key tokens
        tokens = query_text.split()
        return " ".join(tokens[:12])

    @classmethod
    def handle_product_search(cls, question: str, doc_id: str, retrieved_chunks: list, rag_retriever=None) -> Dict[str, Any]:
        """
        Extracts required equipment items and generates clickable specification-based Google search cards.
        """
        q_lower = question.lower()
        
        # Check location from question or document metadata (e.g. Peshawar, Pakistan)
        summary_data = DocumentSummarizer.get_summary(doc_id) if doc_id else {}
        doc_text_combined = " ".join([s.get("summary", "") for s in summary_data.get("section_summaries", [])]) if summary_data else ""
        
        is_pakistan_focused = any(kw in q_lower or kw in doc_text_combined.lower() for kw in ["pakistan", "peshawar", "karachi", "lahore", "islamabad", "rawalpindi"])
        is_supplier_focused = any(kw in q_lower for kw in ["supplier", "distributor", "dealer", "vendor", "buy", "quote", "pricing", "price"])

        items = []
        seen_item_names = set()

        # 1. Try to extract structured items via DocumentSummarizer tables (Annexure-II, Financial Proposal, BOQ)
        if summary_data:
            # Check extracted tables for items with quantities / units
            for tbl_obj in summary_data.get("extracted_tables", []):
                tbl_md = tbl_obj.get("table_md", "")
                page_num = tbl_obj.get("page", 1)
                for line in tbl_md.split("\n"):
                    line_clean = line.strip().strip("|").strip()
                    # Match rows like "Air Conditioner 2 Ton (DC Inverter) | 16 Nos" or "1 | Air Conditioner 2 Ton | 16"
                    if any(kw in line_clean.lower() for kw in ["air conditioner", "inverter", "ton", "scanner", "printer", "camera", "ups", "generator", "server", "switch", "laptop", "desktop", "computer", "copper pipe"]):
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            # Candidate name is the longest text part that isn't a single number
                            name_cand = max([p for p in parts if not re.match(r'^\d+$', p)], key=len, default="")
                            if name_cand and len(name_cand) > 3 and name_cand.lower() not in seen_item_names:
                                # Clean up S# or numbering
                                clean_name = re.sub(r'^\d+[\.\)\s]+', '', name_cand).strip()
                                if clean_name.lower() not in seen_item_names and len(clean_name) < 90:
                                    seen_item_names.add(clean_name.lower())
                                    
                                    # Collect specs from table row or related text
                                    specs = []
                                    if "inverter" in line_clean.lower(): specs.append("DC Inverter Technology")
                                    if "ton" in line_clean.lower(): 
                                        ton_m = re.search(r'(\d+(?:\.\d+)?\s*Ton)', line_clean, re.IGNORECASE)
                                        if ton_m: specs.append(ton_m.group(1))
                                    if "wall" in line_clean.lower(): specs.append("Wall Mounted")
                                    if "copper" in line_clean.lower(): specs.append("Refrigeration Grade")

                                    items.append({
                                        "name": clean_name,
                                        "model": "Not specified",
                                        "quantity": 1,
                                        "specifications": specs,
                                        "source_pages": [page_num]
                                    })

            # Check section summaries for product mentions
            if not items:
                for sec in summary_data.get("section_summaries", []):
                    sec_title = sec.get("section", "")
                    sec_summary = sec.get("summary", "")
                    sec_page = sec.get("page", 1)
                    if any(kw in sec_title.lower() or kw in sec_summary.lower() for kw in ["procurement of", "specification", "annexure", "bidding for"]):
                        # Extract product title
                        match = re.search(r'(?:procurement of|supply of|purchase of)\s+([A-Za-z0-9\s\(\)\-\.]+?)(?:\s+by|\s+deadline|\s+tender|\s+at|\.|$)', sec_title + " " + sec_summary, re.IGNORECASE)
                        if match:
                            prod_name = match.group(1).strip()
                            if prod_name and prod_name.lower() not in seen_item_names and len(prod_name) < 70:
                                seen_item_names.add(prod_name.lower())
                                items.append({
                                    "name": prod_name,
                                    "model": "Tender Specified",
                                    "quantity": 1,
                                    "specifications": ["Extracted from tender requirements"],
                                    "source_pages": [sec_page]
                                })


        # 3. Fallback heuristic extraction from retrieved chunks
        if not items:
            for chunk in retrieved_chunks:
                text = chunk.get("text", "")
                page = chunk.get("page_start", 1)
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                for line in lines:
                    if any(kw in line.lower() for kw in ["air conditioner", "inverter", "ton", "scanner", "printer", "camera", "ups", "generator", "server", "switch", "laptop", "desktop", "computer"]) and len(line) < 80:
                        clean_name = re.sub(r'^(?:item\s*\d*[:\.\-]?|\d+[\.\)])\s*', '', line, flags=re.IGNORECASE).strip()
                        if clean_name.lower() not in seen_item_names:
                            seen_item_names.add(clean_name.lower())
                            items.append({
                                "name": clean_name,
                                "model": "Not specified",
                                "quantity": 1,
                                "specifications": [],
                                "source_pages": [page]
                            })

        # 4. If still no items detected, extract main subject from tender filename/header
        if not items:
            doc_subject = summary_data.get("filename", "Tender Equipment").replace(".pdf", "").replace("_", " ").replace("-", " ")
            items.append({
                "name": doc_subject,
                "model": "Not specified",
                "quantity": 1,
                "specifications": ["Specifications extracted from tender document"],
                "source_pages": [1]
            })

        # Build response cards
        cards_html = []
        markdown_parts = ["EQUIPMENT LINKS\n"]

        for idx, itm in enumerate(items, 1):
            name = itm["name"]
            specs = itm.get("specifications", [])
            page_num = itm.get("source_pages", [1])[0]
            icon = cls._get_icon_for_item(name)

            clean_query = cls._clean_query_string(name, specs)
            encoded_query = urllib.parse.quote_plus(clean_query)
            google_search_url = f"https://www.google.com/search?q={encoded_query}"

            # Supplier query
            supplier_suffix = "supplier distributor Pakistan" if is_pakistan_focused else "supplier authorized distributor"
            supplier_query = f"{name} {supplier_suffix}".strip()
            encoded_supplier_query = urllib.parse.quote_plus(supplier_query)
            supplier_search_url = f"https://www.google.com/search?q={encoded_supplier_query}"

            # Strict deterministic Markdown representation:
            # EQUIPMENT LINKS
            # 1). [Equipment Name]
            # Official Product/Search Link: [URL]
            markdown_parts.append(f"{idx}). {name}\nOfficial Product/Search Link: {google_search_url} [Page {page_num}]\n")

            # HTML Card for rich UI rendering
            spec_pills_html = "".join([
                f'<span class="cpc-spec-pill">{s}</span>' for s in specs[:3]
            ]) if specs else '<span class="cpc-spec-pill">Tender Specifications</span>'

            supplier_btn_label = "Search Suppliers (Pakistan)" if is_pakistan_focused else "Search Suppliers"

            card_html = f"""
<div class="chat-product-card">
    <div class="cpc-header">
        <div class="cpc-title-wrap">
            <span class="cpc-icon">{icon}</span>
            <div>
                <h4 class="cpc-name">{name}</h4>
                {f'<span class="cpc-model">Model: {itm["model"]}</span>' if itm.get("model") and itm["model"] != "Not specified" else ""}
            </div>
        </div>
        <span class="cpc-page-badge" title="Referenced in Tender PDF">[Page {page_num}]</span>
    </div>
    <div class="cpc-specs">
        {spec_pills_html}
    </div>
    <div class="cpc-actions">
        <a href="{google_search_url}" target="_blank" rel="noopener noreferrer" class="cpc-btn cpc-btn-primary" title="Search matching products on Google">
            <i data-lucide="search"></i>
            <span>Search on Google</span>
            <i data-lucide="external-link" class="cpc-ext-icon"></i>
        </a>
        <a href="{supplier_search_url}" target="_blank" rel="noopener noreferrer" class="cpc-btn cpc-btn-secondary" title="Search authorized suppliers and distributors">
            <i data-lucide="building-2"></i>
            <span>{supplier_btn_label}</span>
            <i data-lucide="external-link" class="cpc-ext-icon"></i>
        </a>
    </div>
</div>
"""
            cards_html.append(card_html)

        full_markdown = "\n".join(markdown_parts)
        full_html = f"""
<div class="chat-product-search-response">
    <p class="cpc-intro-text">Here are Google search links for products matching the tender specifications extracted from your document:</p>
    <div class="chat-product-cards-list">
        {"".join(cards_html)}
    </div>
</div>
"""

        citations = [{"citation_text": f"[Page {itm.get('source_pages', [1])[0]}]", "page_number": itm.get("source_pages", [1])[0], "section": "Equipment", "source": "Tender PDF"} for itm in items]

        return {
            "answer_text": full_markdown,
            "answer_html": full_html,
            "citations": citations,
            "items_count": len(items)
        }
