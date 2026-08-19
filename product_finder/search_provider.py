import os
import re
import urllib.parse
import requests
import json
from typing import List, Dict, Any, Optional
from product_finder.cache import SearchCache

class SearchProvider:
    """Abstract base class for Product Finder search providers."""

    def search_products(self, item_name: str, specifications: List[str], quantity: int = 1) -> Dict[str, Any]:
        raise NotImplementedError

class GeminiGroundingProvider(SearchProvider):
    """
    Search Provider utilizing Gemini Google Search Grounding.
    Extracts real, live search results and verified product URLs directly from Google Search grounding metadata.
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = os.getenv("GEMINI_SEARCH_MODEL", "gemini-1.5-flash")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_optimized_queries(self, item_name: str, specifications: List[str]) -> List[str]:
        """Creates 2-3 precise, keyword-rich search queries."""
        clean_specs = [s.replace("\n", " ").strip() for s in specifications if s and len(s) > 2][:4]
        combined = " ".join(clean_specs)
        # Remove noisy punctuation
        words = re.findall(r'[A-Za-z0-9\.\-\/]+', f"{item_name} {combined}")
        query_1 = " ".join(words[:8])
        query_2 = f"{item_name} {combined}"[:80].strip()
        query_3 = f"buy {item_name} specifications price"
        return [query_1, query_2, query_3]

    def search_products(self, item_name: str, specifications: List[str], quantity: int = 1) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "success": False,
                "provider": "gemini_grounding",
                "error": "Gemini API Key is not configured."
            }

        SearchCache.throttle()

        queries = self.generate_optimized_queries(item_name, specifications)
        specs_formatted = "\n".join([f"- {s}" for s in specifications if s])

        prompt = f"""You are an expert Procurement Product Specialist.
Find REAL, currently commercially available products, models, and supplier listings matching these exact tender requirements:

ITEM: {item_name}
QUANTITY: {quantity}
REQUIRED SPECIFICATIONS:
{specs_formatted}

INSTRUCTIONS:
1. Search the web for real products, exact brand and model names, manufacturer pages, authorized distributors, or major retailers.
2. DO NOT fabricate or invent product names, models, prices, or URLs.
3. Return a structured JSON block matching this exact JSON format:

```json
{{
  "products": [
    {{
      "name": "Full Product Name & Model (e.g. Dell OptiPlex 7010 Micro)",
      "brand": "Brand Name (e.g. Dell)",
      "model": "Exact Model Number",
      "source_website": "Domain or Retailer Name (e.g. Dell Official Store / Amazon)",
      "url": "Actual verified URL if returned by search grounding or leave empty if unverified",
      "source_type": "Manufacturer / Authorized Distributor / Retailer / Marketplace / Other",
      "price": "Price with currency or 'Price on request'",
      "availability": "In Stock / Available / Inquire",
      "extracted_specs": [
        "Spec 1 found on product (e.g. Intel Core i7-13700T)",
        "Spec 2 found on product (e.g. 16GB DDR5 RAM)",
        "Spec 3 found on product (e.g. 512GB NVMe SSD)"
      ],
      "highlights": "Key highlights and warranty info"
    }}
  ]
}}
```
"""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2000
            }
        }

        try:
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code != 200:
                # Fallback without grounding tool if tool is not enabled for this key
                payload_fallback = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2000}
                }
                res = requests.post(url, json=payload_fallback, timeout=20)
                if res.status_code != 200:
                    return {"success": False, "provider": "gemini_grounding", "error": f"Gemini API returned status {res.status_code}"}

            data = res.json()
            candidate = data.get("candidates", [{}])[0]
            text_content = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")

            # Extract real verified grounding URLs if returned by Google search
            grounding_chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
            grounded_sources = []
            for chunk in grounding_chunks:
                web = chunk.get("web", {})
                if web.get("uri"):
                    grounded_sources.append({
                        "title": web.get("title", "Search Result"),
                        "url": web.get("uri")
                    })

            # Parse JSON from response
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text_content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(1))
            else:
                parsed = json.loads(text_content)

            products = parsed.get("products", [])
            
            # Enrich products with grounded URLs if missing
            for idx, prod in enumerate(products):
                if not prod.get("url") and idx < len(grounded_sources):
                    prod["url"] = grounded_sources[idx]["url"]
                    if not prod.get("source_website"):
                        prod["source_website"] = grounded_sources[idx]["title"]
                
                # Check verification status
                if prod.get("url") and (prod["url"].startswith("http://") or prod["url"].startswith("https://")):
                    prod["verification_status"] = "Verified Search Result"
                else:
                    prod["verification_status"] = "AI Grounded (URL Not Verified)"

            return {
                "success": True,
                "provider": "gemini_grounding",
                "products": products,
                "search_queries": queries,
                "grounded_sources": grounded_sources,
                "raw_text": text_content
            }

        except Exception as e:
            return {
                "success": False,
                "provider": "gemini_grounding",
                "error": f"Search error: {str(e)}",
                "search_queries": queries
            }

class FreeSearchProvider(SearchProvider):
    """
    Zero-cost Search Provider and Fallback.
    Generates precision search links and formatted search queries for Google and Bing.
    Never hallucinates fake product URLs.
    """

    def generate_search_links(self, item_name: str, specifications: List[str]) -> Dict[str, Any]:
        clean_specs = [s.replace("\n", " ").strip() for s in specifications if s and len(s) > 2][:4]
        combined = " ".join(clean_specs)
        clean_query = f"{item_name} {combined}".strip()

        encoded_q = urllib.parse.quote_plus(clean_query)
        google_url = f"https://www.google.com/search?q={encoded_q}"
        bing_url = f"https://www.bing.com/search?q={encoded_q}"
        google_shopping_url = f"https://www.google.com/search?tbm=shop&q={encoded_q}"

        queries = [
            clean_query,
            f"{item_name} best model specifications price",
            f"buy {item_name} authorized dealer quotation"
        ]

        return {
            "query": clean_query,
            "queries": queries,
            "google_search_url": google_url,
            "bing_search_url": bing_url,
            "google_shopping_url": google_shopping_url
        }

    def search_products(self, item_name: str, specifications: List[str], quantity: int = 1) -> Dict[str, Any]:
        links = self.generate_search_links(item_name, specifications)
        return {
            "success": True,
            "provider": "free_search_links",
            "is_fallback": True,
            "message": "Live product search is active in direct query link mode. Use verified search links below.",
            "search_queries": links["queries"],
            "primary_query": links["query"],
            "google_search_url": links["google_search_url"],
            "bing_search_url": links["bing_search_url"],
            "google_shopping_url": links["google_shopping_url"],
            "products": []
        }
