import re
from rag.embeddings import EmbeddingGenerator
from rag.vector_store import VectorStore
from rag.keyword_search import BM25Search

class HybridRetriever:
    """
    Intent-Aware Hybrid Retrieval Engine combining FAISS Vector Similarity & BM25 Keyword Search.
    Features section-level prioritization, table-aware scoring, and query expansion to ensure
    technical specification schedules and relevant tender sections are accurately retrieved.
    """

    RELEVANCE_THRESHOLD = 0.01  # Practical relevance cutoff

    def __init__(self, vector_store: VectorStore, bm25_search: BM25Search):
        self.vector_store = vector_store
        self.bm25_search = bm25_search

    def retrieve(self, query: str, top_k: int = 6, vector_weight: float = 0.65, intent: str = None) -> dict:
        """
        Executes intent-guided hybrid vector + BM25 search with section reranking and keyword fallback.
        """
        if not query or not query.strip():
            return {"chunks": [], "top_score": 0.0, "sufficient_context": False}

        # 1. Expand query based on intent
        search_queries = [query]
        if intent in ["EQUIPMENT_SPECIFICATIONS", "EQUIPMENT", "TECHNICAL_SPECIFICATIONS", "BOQ"]:
            search_queries.extend([
                "Annexure-II Technical Specifications equipment schedule description total quantity specification",
                "Technical Specifications schedule of requirements item quantity specification",
                "S# Description Total Quantity Specification BOQ",
                "Cooling Capacity BTU Inverter Copper coil Warranty Approved brands"
            ])
        elif intent in ["TENDER_DEADLINE", "DEADLINE"]:
            search_queries.extend([
                "tender submission deadline closing date opening date time",
                "last date and time for submission of bids opening",
                "bids must be submitted by date and time closing"
            ])
        elif intent in ["BID_OPENING"]:
            search_queries.extend([
                "tender bids will be opened date time venue committee",
                "technical bids will be opened opening of bids date and time"
            ])
        elif intent in ["BID_SECURITY", "EARNEST_MONEY"]:
            search_queries.extend([
                "earnest money bid security call deposit CDR bank guarantee percentage",
                "bid security 2% earnest money call deposit receipt CDR bank draft"
            ])
        elif intent in ["DELIVERY_SCHEDULE", "DELIVERY"]:
            search_queries.extend([
                "delivery period delivery schedule completion timeline supply order work order",
                "within days place of delivery inspection consignee"
            ])
        elif intent in ["PAYMENT_TERMS", "PAYMENT"]:
            search_queries.extend([
                "payment terms payment mode payment schedule invoicing taxes withheld",
                "100% payment after inspection and successful commissioning"
            ])
        elif intent in ["ELIGIBILITY_REQUIREMENTS", "ELIGIBILITY"]:
            search_queries.extend([
                "eligibility criteria qualification requirements mandatory documents",
                "active taxpayer NTN Sales tax registration PEC category minimum turnover affidavit"
            ])
        elif intent in ["WARRANTY"]:
            search_queries.extend([
                "warranty period compressor warranty pcb warranty parts and service maintenance",
                "minimum years warranty from date of commissioning"
            ])
        elif intent in ["TENDER_SUMMARY", "SUMMARY"]:
            search_queries.extend([
                # Tender notice & scope
                "tender notice invitation for bids instructions to bidders procurement scope",
                "procurement of equipment scope of work summary requirements",
                # Deadline (MUST be included for Summary so it always finds the date)
                "last date and time for bid submission closing date submission deadline",
                "bid submission deadline tender closing time schedule",
                # Bid opening
                "bids will be opened opening of bids date time venue",
                # Bid security / earnest money
                "earnest money bid security call deposit CDR percentage",
                # Key facts: validity, eligibility, delivery, payment, warranty
                "bid validity period eligible bidders minimum requirements",
                "delivery period payment terms warranty period commissioning",
            ])

        chunk_scores = {}
        chunk_map = {}

        # 2. Execute searches across queries
        for q_text in search_queries:
            query_emb = EmbeddingGenerator.embed_query(q_text)
            vector_results = self.vector_store.search(query_emb, top_k=top_k * 3)
            bm25_results = self.bm25_search.search(q_text, top_k=top_k * 3)

            for r in vector_results:
                cid = r["chunk"]["chunk_id"]
                chunk_map[cid] = r["chunk"]
                score = max(0.0, r["score"])
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + vector_weight * score

            bm25_weight = 1.0 - vector_weight
            for r in bm25_results:
                cid = r["chunk"]["chunk_id"]
                chunk_map[cid] = r["chunk"]
                score = max(0.0, r["score"])
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + bm25_weight * score

        # 3. Intent-Aware Scoring, Section Boosting & Penalty Filtering
        for cid, chunk in chunk_map.items():
            text_lower = chunk.get("text", "").lower()
            section_lower = chunk.get("section", "").lower()
            page_start = chunk.get("page_start", chunk.get("page_number", 1))
            is_table = chunk.get("is_table", False)
            content_type = chunk.get("content_type", "")

            if intent in ["EQUIPMENT_SPECIFICATIONS", "EQUIPMENT", "TECHNICAL_SPECIFICATIONS", "BOQ"]:
                # High boost for technical spec tables and annexures
                if "annexure-ii" in text_lower or "annexure-ii" in section_lower or "technical specifications" in section_lower or "technical specification" in text_lower:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.5 + 2.5
                elif is_table and any(k in text_lower for k in ["total quantity", "specification", "description", "cooling capacity", "btu"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.0
                elif content_type == "technical_specification_table":
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 2.5 + 1.5

                # Strong penalty for unrelated non-equipment clauses
                penalty_keywords = ["payment terms", "financial proposal", "general conditions", "affidavit", "black listed", "evaluation criteria", "undertaking", "dispute resolution"]
                if any(pk in text_lower for pk in penalty_keywords) and not ("specification" in text_lower and "total quantity" in text_lower):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 0.15

            elif intent in ["TENDER_DEADLINE", "DEADLINE"]:
                if any(k in text_lower for k in ["submission deadline", "closing date", "last date and time", "submitted by", "submission:", "deadline:"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.5
                if page_start <= 3:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 1.5 + 0.5
                # Penalty for dispute/warranty/payment when looking for deadline
                if any(k in text_lower for k in ["dispute resolution", "arbitration", "warranty period", "payment shall be made"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 0.2

            elif intent in ["BID_OPENING"]:
                if any(k in text_lower for k in ["bids will be opened", "opening of bids", "opening date", "opened on", "opening time"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.5
                if page_start <= 3:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 1.5 + 0.5

            elif intent in ["BID_SECURITY", "EARNEST_MONEY"]:
                if any(k in text_lower for k in ["earnest money", "bid security", "call deposit", "cdr", "security deposit", "% of the bid", "% of the total"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.5
                # Penalty for unrelated equipment specifications
                if is_table and not any(k in text_lower for k in ["bid security", "earnest money", "cdr"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 0.2

            elif intent in ["DELIVERY_SCHEDULE", "DELIVERY"]:
                if any(k in text_lower for k in ["delivery schedule", "delivery period", "completion time", "within days", "place of delivery"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.0

            elif intent in ["PAYMENT_TERMS", "PAYMENT"]:
                if any(k in text_lower for k in ["payment terms", "mode of payment", "payment shall be", "invoicing", "100% payment"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.0

            elif intent in ["ELIGIBILITY_REQUIREMENTS", "ELIGIBILITY"]:
                if any(k in text_lower for k in ["eligibility", "qualification", "mandatory requirement", "tax registration", "turnover", "affidavit", "pec"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.0

            elif intent in ["WARRANTY"]:
                if any(k in text_lower for k in ["warranty", "guarantee", "after-sales", "maintenance", "compressor", "pcb"]):
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.0

            elif intent in ["TENDER_SUMMARY", "SUMMARY"]:
                # Boost chunks that contain key tender facts needed for the summary
                KEY_FACT_TERMS = [
                    "last date", "submission deadline", "closing date", "bid submission",
                    "bids will be opened", "opening of bids",
                    "earnest money", "bid security", "call deposit", "cdr",
                    "bid validity", "eligible", "eligibility",
                    "delivery period", "payment terms", "warranty",
                    "scope of work", "procurement", "invitation for bids",
                ]
                facts_found = sum(1 for k in KEY_FACT_TERMS if k in text_lower)
                if facts_found >= 3:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 3.0 + 2.5
                elif facts_found >= 2:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 2.0 + 1.5
                elif facts_found >= 1:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 1.5 + 0.5
                # Extra boost for early pages (tender notice pages)
                if page_start <= 3:
                    chunk_scores[cid] = chunk_scores.get(cid, 0.0) * 1.4 + 0.5

        # 4. Fallback Exact-Phrase Scan across all chunks if top score is weak
        intent_required_keywords = {
            "TENDER_DEADLINE": ["deadline", "submission", "closing date", "last date"],
            "BID_OPENING": ["opened", "opening"],
            "BID_SECURITY": ["bid security", "earnest money", "call deposit", "cdr", "security deposit"],
            "DELIVERY_SCHEDULE": ["delivery", "completion time", "supply order"],
            "PAYMENT_TERMS": ["payment", "invoicing"],
            "ELIGIBILITY_REQUIREMENTS": ["eligibility", "qualification", "mandatory", "taxpayer", "turnover"],
            "WARRANTY": ["warranty", "guarantee"]
        }

        req_kw = intent_required_keywords.get(intent, [])
        if req_kw:
            # Check if any top chunk contains required keywords
            has_relevant = any(
                any(kw in chunk_map.get(cid, {}).get("text", "").lower() for kw in req_kw)
                for cid in list(chunk_scores.keys())[:3]
            )
            if not has_relevant and hasattr(self.vector_store, "chunks"):
                # Fallback scan all chunks in document
                for chk in self.vector_store.chunks:
                    cid = chk.get("chunk_id")
                    t_lower = chk.get("text", "").lower()
                    kw_matches = sum(1 for kw in req_kw if kw in t_lower)
                    if kw_matches > 0:
                        chunk_map[cid] = chk
                        chunk_scores[cid] = chunk_scores.get(cid, 0.0) + (kw_matches * 2.0)

        # Sort by combined score descending
        sorted_chunks = sorted(chunk_scores.items(), key=lambda item: item[1], reverse=True)

        retrieved_chunks = []
        top_score = sorted_chunks[0][1] if sorted_chunks else 0.0

        for cid, score in sorted_chunks[:top_k]:
            chunk_copy = dict(chunk_map[cid])
            chunk_copy["retrieval_score"] = round(score, 4)
            retrieved_chunks.append(chunk_copy)

        # Context is sufficient if any candidate chunks exist
        sufficient_context = len(retrieved_chunks) > 0 and top_score >= self.RELEVANCE_THRESHOLD

        return {
            "chunks": retrieved_chunks,
            "top_score": round(top_score, 4),
            "sufficient_context": sufficient_context
        }
