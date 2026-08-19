import os
from typing import List, Dict, Any, Optional
from product_finder.search_provider import GeminiGroundingProvider, FreeSearchProvider
from product_finder.matcher import SpecificationMatcher
from product_finder.cache import SearchCache
from product_finder.equipment_extractor import EquipmentExtractor

class ProductFinderService:
    """
    Central Orchestrator for the Product Finder feature.
    Coordinates search providers, caches, specification matching, and comparison matrices.
    """

    def __init__(self):
        self.gemini_provider = GeminiGroundingProvider()
        self.free_provider = FreeSearchProvider()

    def get_tender_equipment(self, doc_id: str, rag_retriever=None) -> Dict[str, Any]:
        """Fetches structured equipment list from the active tender document."""
        return EquipmentExtractor.get_equipment_from_tender(doc_id, rag_retriever=rag_retriever)

    def search_for_item(self, item_name: str, specifications: List[str], quantity: int = 1, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Searches for products matching a specific item and evaluates specification matches.
        """
        # 1. Check cache if not force refreshing
        if not force_refresh:
            cached_result = SearchCache.get(item_name, specifications)
            if cached_result:
                return {**cached_result, "is_cached": True}

        # 2. Try Gemini Search Grounding first if available
        search_res = None
        if self.gemini_provider.is_available():
            try:
                search_res = self.gemini_provider.search_products(item_name, specifications, quantity)
            except Exception as e:
                search_res = None

        # 3. If Gemini Search Grounding failed or returned 0 products, use Free Search Fallback
        is_fallback = False
        if not search_res or not search_res.get("success") or not search_res.get("products"):
            free_res = self.free_provider.search_products(item_name, specifications, quantity)
            is_fallback = True
            
            # If search grounding failed, construct candidate fallback products with generated search links
            links = self.free_provider.generate_search_links(item_name, specifications)
            search_res = {
                "success": True,
                "provider": "free_search_links",
                "is_fallback": True,
                "search_queries": links["queries"],
                "primary_query": links["query"],
                "google_search_url": links["google_search_url"],
                "bing_search_url": links["bing_search_url"],
                "google_shopping_url": links["google_shopping_url"],
                "products": []
            }

        # 4. Perform Specification Matching on products
        ranked_products = []
        raw_products = search_res.get("products", [])

        for idx, prod in enumerate(raw_products):
            match_data = SpecificationMatcher.match_product(specifications, prod)
            ranked_prod = {
                "id": f"prod_{idx+1}",
                "name": prod.get("name", item_name),
                "brand": prod.get("brand", "Manufacturer"),
                "model": prod.get("model", "Not specified"),
                "source_website": prod.get("source_website", "Verified Supplier"),
                "url": prod.get("url", ""),
                "source_type": prod.get("source_type", "Retailer / Distributor"),
                "price": prod.get("price", "Price on request"),
                "availability": prod.get("availability", "Available"),
                "extracted_specs": prod.get("extracted_specs", []),
                "highlights": prod.get("highlights", ""),
                "verification_status": prod.get("verification_status", "Verified Search Result"),
                "match_score": match_data["score_percent"],
                "matched_count": match_data["matched_count"],
                "partial_count": match_data["partial_count"],
                "failed_count": match_data["failed_count"],
                "total_count": match_data["total_count"],
                "summary_label": match_data["summary_label"],
                "comparisons": match_data["comparisons"]
            }
            ranked_products.append(ranked_prod)

        # Sort products by match score descending
        ranked_products.sort(key=lambda x: x["match_score"], reverse=True)

        final_payload = {
            "success": True,
            "item_name": item_name,
            "quantity": quantity,
            "required_specifications": specifications,
            "provider": search_res.get("provider", "gemini_grounding"),
            "is_fallback": is_fallback,
            "search_queries": search_res.get("search_queries", []),
            "google_search_url": search_res.get("google_search_url"),
            "bing_search_url": search_res.get("bing_search_url"),
            "google_shopping_url": search_res.get("google_shopping_url"),
            "grounded_sources": search_res.get("grounded_sources", []),
            "products": ranked_products,
            "total_found": len(ranked_products)
        }

        # Cache valid result
        SearchCache.set(item_name, specifications, final_payload)
        return final_payload

    def compare_products(self, required_specs: List[str], products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates side-by-side comparison matrix for selected products."""
        return SpecificationMatcher.compare_multiple_products(required_specs, products)
