"""
Intelligent Tender Deadline Extractor.
Extracts submission deadline, opening date/time, tender title, and organization
grounded strictly in the document text, summary metadata, and first pages.
Supports comprehensive multi-format regex matching AND AI LLM extraction fallback.
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
from documents.summarizer import DocumentSummarizer
from deadlines.database import DEFAULT_TIMEZONE, TimezoneHelper
from llm.provider import LLMProvider

class DeadlineExtractor:
    """
    Analyzes document text, section summaries, key-value metadata, tables,
    and RAG chunks using hybrid regex + LLM extraction to guarantee high accuracy.
    """

    MONTH_NAMES = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    
    # Regex patterns for date extraction
    DATE_PATTERNS = [
        # August 17, 2026 / August 17 2026 / 17 August 2026 / 17th August, 2026 / 17-Aug-2026
        rf"({MONTH_NAMES}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{2,4}})",
        rf"(\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH_NAMES},?\s+\d{{2,4}})",
        rf"(\d{{1,2}}(?:st|nd|rd|th)?[-/]{MONTH_NAMES}[-/]\d{{2,4}})",
        rf"({MONTH_NAMES}[-/]\d{{1,2}}(?:st|nd|rd|th)?[-/]\d{{2,4}})",
        # 26.08.2026 / 26/08/2026 / 26-08-2026 / 2026-08-26 / 03/06/2026__ / 03-06-2026
        r"(\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2})",
        r"(\d{1,2}[-/. ]\d{1,2}[-/. ]\d{4})",
        r"(\d{1,2}[-/. ]\d{1,2}[-/. ]\d{2})"
    ]

    # Regex patterns for time extraction
    TIME_PATTERNS = [
        # 10:30 AM / 10.30 AM / 10:30AM / 10.30pm
        r"(\b(?:1[0-2]|0?[1-9])[:.][0-5]\d\s*(?:AM|PM|am|pm)\b)",
        # 10 30 AM / 11 00 AM (space separated from table/KV extraction)
        r"(\b(?:1[0-2]|0?[1-9])\s+[0-5]\d\s*(?:AM|PM|am|pm)\b)",
        # 10:30 hrs / 14:30 hours / 10.30 hrs
        r"(\b(?:[01]?\d|2[0-3])[:.][0-5]\d\s*(?:hrs|hours|hrs\.|hours\.)\b)",
        # 1400 hrs / 1030 hours
        r"(\b(?:[01]\d|2[0-3])[0-5]\d\s*(?:hrs|hours)\b)",
        # 10 AM / 12 PM / 9 am (strictly 1-12)
        r"(\b(?:1[0-2]|0?[1-9])\s*(?:AM|PM|am|pm)\b)",
        # 24-hour time 14:30 / 10:00 without AM/PM
        r"(\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b)",
        # 10 o'clock
        r"(\b(?:1[0-2]|0?[1-9])\s*o'clock\b)"
    ]

    @classmethod
    def extract_from_document(cls, doc_id: str, rag_retriever = None) -> Dict[str, Any]:
        """
        Main extraction entry point.
        Uses fast high-precision regex extraction first.
        If regex finds no deadline or low confidence, falls back to AI LLM extractor.
        """
        summary_data = DocumentSummarizer.get_summary(doc_id) if doc_id else {}
        
        sections = summary_data.get("section_summaries", []) if summary_data else []
        kv_pairs = summary_data.get("metadata_kv", []) if summary_data else []
        tables = summary_data.get("extracted_tables", []) if summary_data else []
        filename = summary_data.get("filename", "") if summary_data else ""

        # Title & Organization extraction
        tender_title = cls._extract_tender_title(sections, kv_pairs, filename)
        organization = cls._extract_organization(sections, kv_pairs, filename)

        # 1. Search for submission deadline via multi-pass regex
        submission_result = cls._find_submission_deadline(sections, kv_pairs, tables, rag_retriever)
        
        # 2. Search for opening datetime via regex
        opening_result = cls._find_opening_datetime(sections, kv_pairs, tables, submission_result.get("date_str"))

        # Build ISO strings
        submission_iso = None
        submission_page = submission_result.get("page", 1)
        confidence = submission_result.get("confidence", 0.0)

        if submission_result.get("date_dt"):
            dt = submission_result["date_dt"]
            submission_iso = dt.strftime("%Y-%m-%dT%H:%M:00+05:00")

        opening_iso = None
        opening_page = opening_result.get("page", 1)
        if opening_result.get("date_dt"):
            dt = opening_result["date_dt"]
            opening_iso = dt.strftime("%Y-%m-%dT%H:%M:00+05:00")

        has_deadline = submission_iso is not None and confidence >= 0.5

        # 3. AI LLM Fallback: If regex didn't find a deadline, use LLM to extract directly from document
        if not has_deadline and (rag_retriever or sections or kv_pairs):
            llm_result = cls._extract_via_llm(doc_id, sections, kv_pairs, rag_retriever, filename)
            if llm_result and llm_result.get("has_deadline"):
                return llm_result

        return {
            "has_deadline": has_deadline,
            "tender_title": tender_title,
            "organization": organization,
            "submission_deadline": submission_iso,
            "submission_deadline_source_page": submission_page,
            "submission_deadline_raw": submission_result.get("raw_text", ""),
            "opening_datetime": opening_iso,
            "opening_datetime_source_page": opening_page,
            "opening_datetime_raw": opening_result.get("raw_text", ""),
            "timezone": DEFAULT_TIMEZONE,
            "confidence": confidence,
            "candidates": submission_result.get("all_candidates", []),
            "file_name": filename
        }

    @classmethod
    def _extract_tender_title(cls, sections: List[dict], kv_pairs: List[dict], filename: str) -> str:
        """Extracts the tender project name or title."""
        for kv in kv_pairs:
            k = kv.get("key", "").lower()
            v = kv.get("value", "").strip()
            if any(t in k for t in ["tender for", "procurement of", "name of work", "project title", "title", "subject", "bidding for", "invitation to bid", "tender notice"]) and len(v) > 5:
                clean_v = re.sub(r'(?i)\s*(deadline|submission|for submission).*$', '', v).strip()
                return clean_v if clean_v else v

        for sec in sections[:4]:
            title = sec.get("section", "")
            summary = sec.get("summary", "")
            match = re.search(r'(?:procurement of|tender for|bidding for|supply of|purchase of|hiring of|invitation to bid for)\s+([A-Za-z0-9\s\(\)\-\.]+?)(?:\s+by|\s+deadline|\s+tender|\s+at|\.|$)', title + " " + summary, re.IGNORECASE)
            if match:
                clean = match.group(0).strip()
                clean = re.sub(r'(?i)\s*(deadline|submission|is:).*$', '', clean).strip()
                if 8 < len(clean) < 100:
                    return clean

        if filename:
            name = filename.replace(".pdf", "").replace("_", " ").replace("-", " ")
            return name.strip().title()
        return "Tender Document"

    @classmethod
    def _extract_organization(cls, sections: List[dict], kv_pairs: List[dict], filename: str) -> str:
        """Extracts procuring entity / organization name."""
        all_text = " ".join([kv.get("value", "") for kv in kv_pairs] + [sec.get("summary", "") + " " + sec.get("section", "") for sec in sections[:4]])
        
        match = re.search(r'(?:Institute of Management Sciences|IMSciences,?\s*Peshawar|IMSciences|University of [A-Za-z\s]+|Directorate of [A-Za-z\s]+|Department of [A-Za-z\s]+|Government of [A-Za-z\s]+|KP-ITB|PPRA|WAPDA|OGDCL|SNGPL|PTCL|Peshawar Electric Supply|National Highway Authority|Civil Aviation Authority)', all_text, re.IGNORECASE)
        if match:
            return match.group(0).strip().replace("  ", " ")

        for kv in kv_pairs:
            k = kv.get("key", "").lower()
            v = kv.get("value", "").strip()
            if any(t in k for t in ["organization", "client", "procuring entity", "institute", "department", "authority", "entity"]) and len(v) > 3:
                return v

        return "Procuring Organization"

    @classmethod
    def _find_submission_deadline(
        cls,
        sections: List[dict],
        kv_pairs: List[dict],
        tables: List[dict],
        rag_retriever = None
    ) -> Dict[str, Any]:
        """
        Locates the specific tender submission deadline.
        Distinguishes submission deadline from tender opening time.
        """
        candidates = []

        SUBMISSION_KEYWORDS = [
            "submission", "closing date", "last date", "due date", "deadline",
            "receipt of bids", "bid submission", "tender submission", "submitting tender",
            "submitted up to", "submitted on or before", "on or before", "reach on or before",
            "receive on or before", "bids must reach", "tenders must reach", "last date of receipt"
        ]

        # 1. Check metadata KV pairs
        for kv in kv_pairs:
            k = kv.get("key", "").lower()
            v = kv.get("value", "")
            p = kv.get("page", 1)
            combined = f"{k} {v}"
            if any(term in k for term in SUBMISSION_KEYWORDS) or any(term in combined.lower() for term in SUBMISSION_KEYWORDS):
                parsed = cls._parse_date_time_string(combined)
                if parsed:
                    candidates.append({
                        "date_dt": parsed["datetime"],
                        "date_str": parsed["date_str"],
                        "time_str": parsed["time_str"],
                        "page": p,
                        "raw_text": f"{kv.get('key')}: {v}",
                        "confidence": 0.95,
                        "type": "submission_deadline"
                    })

        # 2. Check section texts (especially Page 1 - 5)
        for sec in sections[:6]:
            sec_page = sec.get("page", 1)
            sec_text = sec.get("summary", "") + "\n" + sec.get("section", "")
            
            for line in sec_text.split("\n"):
                line_lower = line.lower()
                if any(kw in line_lower for kw in SUBMISSION_KEYWORDS):
                    parsed = cls._parse_date_time_string(line)
                    if parsed:
                        candidates.append({
                            "date_dt": parsed["datetime"],
                            "date_str": parsed["date_str"],
                            "time_str": parsed["time_str"],
                            "page": sec_page,
                            "raw_text": line.strip(),
                            "confidence": 0.90,
                            "type": "submission_deadline"
                        })

        # 3. Always search RAG chunks for deadline terms
        if rag_retriever:
            try:
                res = rag_retriever.retrieve("tender submission deadline closing date last date for submission of bids", top_k=4)
                for chunk in res.get("chunks", []):
                    c_text = chunk.get("text", "")
                    c_page = chunk.get("page_start", 1)
                    for line in c_text.split("\n"):
                        line_lower = line.lower()
                        if any(kw in line_lower for kw in SUBMISSION_KEYWORDS):
                            parsed = cls._parse_date_time_string(line)
                            if parsed:
                                candidates.append({
                                    "date_dt": parsed["datetime"],
                                    "date_str": parsed["date_str"],
                                    "time_str": parsed["time_str"],
                                    "page": c_page,
                                    "raw_text": line.strip(),
                                    "confidence": 0.88,
                                    "type": "submission_deadline"
                                })
            except Exception as r_err:
                print(f"[DeadlineExtractor] RAG search error: {r_err}")
        # 4. Fallback: Any date found in metadata_kv or on Page 1 - 3
        if not candidates:
            # Check all metadata KV pairs on early pages
            for kv in kv_pairs:
                combined = f"{kv.get('key', '')} {kv.get('value', '')}"
                p = kv.get("page", 1)
                if p <= 3:
                    parsed = cls._parse_date_time_string(combined)
                    if parsed:
                        candidates.append({
                            "date_dt": parsed["datetime"],
                            "date_str": parsed["date_str"],
                            "time_str": parsed["time_str"],
                            "page": p,
                            "raw_text": f"{kv.get('key')}: {kv.get('value')}",
                            "confidence": 0.82,
                            "type": "submission_deadline"
                        })
            
            # Check early sections text
            for sec in sections[:3]:
                sec_page = sec.get("page", 1)
                sec_text = sec.get("summary", "") + "\n" + sec.get("section", "")
                for line in sec_text.split("\n"):
                    parsed = cls._parse_date_time_string(line)
                    if parsed:
                        candidates.append({
                            "date_dt": parsed["datetime"],
                            "date_str": parsed["date_str"],
                            "time_str": parsed["time_str"],
                            "page": sec_page,
                            "raw_text": line.strip(),
                            "confidence": 0.78,
                            "type": "submission_deadline"
                        })

        if not candidates:
            return {"date_dt": None, "page": 1, "confidence": 0.0, "all_candidates": []}

        # If we have multiple candidates, sort them so the earlier timestamp on Page 1 comes first (submission before opening)
        candidates.sort(key=lambda c: (c["confidence"], -(c["page"] if c["page"] else 1), -c["date_dt"].timestamp() if c.get("date_dt") else 0), reverse=True)
        
        # When confidence is tied on same page, pick the earlier time of the day as submission
        same_page_candidates = [c for c in candidates if c.get("date_dt") and (c.get("page") == candidates[0].get("page"))]
        if len(same_page_candidates) > 1:
            same_page_candidates.sort(key=lambda c: c["date_dt"])
            best = same_page_candidates[0].copy()
        else:
            best = candidates[0].copy()

        best["all_candidates"] = candidates
        return best

    @classmethod
    def _find_opening_datetime(
        cls,
        sections: List[dict],
        kv_pairs: List[dict],
        tables: List[dict],
        submission_date_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """Locates the tender bid opening date & time."""
        candidates = []

        OPENING_KEYWORDS = [
            "opening", "opening date", "tender opening", "bids opening",
            "opened on", "opened at", "opening of bids", "bid opening date"
        ]

        for kv in kv_pairs:
            k = kv.get("key", "").lower()
            v = kv.get("value", "")
            p = kv.get("page", 1)
            combined = f"{k} {v}"
            if any(term in k for term in OPENING_KEYWORDS) or any(term in combined.lower() for term in OPENING_KEYWORDS):
                parsed = cls._parse_date_time_string(combined)
                if parsed:
                    candidates.append({
                        "date_dt": parsed["datetime"],
                        "date_str": parsed["date_str"],
                        "time_str": parsed["time_str"],
                        "page": p,
                        "raw_text": f"{kv.get('key')}: {v}",
                        "confidence": 0.90
                    })

        for sec in sections[:6]:
            sec_page = sec.get("page", 1)
            sec_text = sec.get("summary", "") + "\n" + sec.get("section", "")
            for line in sec_text.split("\n"):
                line_lower = line.lower()
                if any(kw in line_lower for kw in OPENING_KEYWORDS):
                    parsed = cls._parse_date_time_string(line)
                    if parsed:
                        candidates.append({
                            "date_dt": parsed["datetime"],
                            "date_str": parsed["date_str"],
                            "time_str": parsed["time_str"],
                            "page": sec_page,
                            "raw_text": line.strip(),
                            "confidence": 0.85
                        })

        if candidates:
            candidates.sort(key=lambda c: c["confidence"], reverse=True)
            return candidates[0]
        return {"date_dt": None, "page": 1, "confidence": 0.0}

    @classmethod
    def _parse_date_time_string(cls, text: str) -> Optional[Dict[str, Any]]:
        """
        Parses a date and optional time from text.
        Supports:
          - 26.08.2026, 26/08/2026, 26-08-2026, 2026-08-26
          - August 17, 2026, 17th August 2026, 17-Aug-2026
          - 10:30 AM, 10.30 AM, 10:30AM, 10:30 hrs, 12:00 PM
        Returns a dictionary with parsed datetime object, date string, and time string.
        """
        found_date_str = None
        for pattern in cls.DATE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                found_date_str = m.group(1).strip()
                break

        if not found_date_str:
            return None

        # Clean date string (remove underscores, st, nd, rd, th)
        clean_date_str = re.sub(r'[_]+', '', found_date_str)
        clean_date_str = re.sub(r'(\d+)(?:st|nd|rd|th)', r'\1', clean_date_str)
        clean_date_str = re.sub(r'\s+', ' ', clean_date_str).strip()

        # Parse date with comprehensive format list
        dt_obj = None
        date_formats = [
            # Word months
            "%B %d, %Y", "%B %d %Y", "%d %B, %Y", "%d %B %Y",
            "%b %d, %Y", "%b %d %Y", "%d %b, %Y", "%d %b %Y",
            "%d-%b-%Y", "%d-%B-%Y", "%d/%b/%Y", "%d/%B/%Y",
            "%b-%d-%Y", "%B-%d-%Y",
            # Numeric with dot (e.g. 26.08.2026)
            "%d.%m.%Y", "%d.%m.%y", "%Y.%m.%d", "%m.%d.%Y",
            # Numeric with dash (e.g. 26-08-2026, 2026-08-26)
            "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%m-%d-%Y",
            # Numeric with slash (e.g. 26/08/2026, 2026/08/26)
            "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"
        ]
        
        for fmt in date_formats:
            try:
                dt_obj = datetime.strptime(clean_date_str, fmt)
                # If 2-digit year parsed as 20xx, ensure reasonable century
                if dt_obj.year < 100:
                    dt_obj = dt_obj.replace(year=2000 + dt_obj.year)
                break
            except ValueError:
                continue

        if not dt_obj:
            return None

        # Look for time in same text
        found_time_str = None
        hour = 12
        minute = 0

        for t_pat in cls.TIME_PATTERNS:
            tm = re.search(t_pat, text, re.IGNORECASE)
            if tm:
                found_time_str = tm.group(1).strip()
                break

        if found_time_str:
            time_clean = found_time_str.upper()
            # Replace dot separator or space separator like 10.30 AM -> 10:30 AM, 10 30 AM -> 10:30 AM
            time_clean = re.sub(r'(\d{1,2})[.\s](\d{2})\s*(AM|PM|HRS|HOURS)?', r'\1:\2 \3', time_clean)
            
            # e.g., 10:30 AM or 12 PM or 10:30AM or 10:30 HRS
            m_time = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM|HRS|HOURS)?', time_clean)
            if m_time:
                h = int(m_time.group(1))
                m_min = int(m_time.group(2)) if m_time.group(2) else 0
                ampm = m_time.group(3)
                if ampm == "PM" and h < 12:
                    h += 12
                elif ampm == "AM" and h == 12:
                    h = 0
                elif ampm in ("HRS", "HOURS") and h >= 24:
                    h = 12
                hour = h
                minute = m_min
        else:
            # Default to 12:00 PM if time not specified
            found_time_str = "12:00 PM"

        # Hard bounds check to guarantee no ValueError
        if not (0 <= hour <= 23):
            hour = 12
        if not (0 <= minute <= 59):
            minute = 0

        try:
            final_dt = dt_obj.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        except Exception:
            final_dt = dt_obj.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo(DEFAULT_TIMEZONE))

        return {
            "datetime": final_dt,
            "date_str": found_date_str,
            "time_str": found_time_str
        }

    @classmethod
    def _extract_via_llm(
        cls,
        doc_id: str,
        sections: List[dict],
        kv_pairs: List[dict],
        rag_retriever,
        filename: str
    ) -> Optional[Dict[str, Any]]:
        """
        AI LLM Fallback Extraction.
        Queries LLM with first 2 pages / RAG excerpts to extract structured deadline JSON.
        """
        try:
            # Build context from top RAG chunks and section summaries
            context_text = ""
            if rag_retriever:
                r_res = rag_retriever.retrieve("tender submission deadline closing date last date for receipt of bids tender opening date time", top_k=3)
                chunks = r_res.get("chunks", [])
                context_text = "\n\n".join([f"[Page {c.get('page_start', 1)}]: {c.get('text', '')}" for c in chunks])

            if not context_text:
                context_text = "\n".join([f"Page {s.get('page', 1)}: {s.get('section', '')} - {s.get('summary', '')}" for s in sections[:4]])

            if not context_text:
                return None

            prompt = (
                "You are an expert tender contract analyst. Carefully analyze the following tender document text and extract key deadline metadata.\n\n"
                f"DOCUMENT CONTEXT:\n{context_text}\n\n"
                "INSTRUCTIONS:\n"
                "Extract the following fields and return ONLY a valid JSON object (no markdown, no other text):\n"
                "{\n"
                '  "has_deadline": true or false,\n'
                '  "tender_title": "Full title/project name of tender",\n'
                '  "organization": "Procuring entity or organization name",\n'
                '  "submission_deadline": "YYYY-MM-DDTHH:MM:SS+05:00" (or null if no deadline found),\n'
                '  "submission_deadline_source_page": 1 (integer page number),\n'
                '  "submission_deadline_raw": "exact raw sentence mentioning deadline",\n'
                '  "opening_datetime": "YYYY-MM-DDTHH:MM:SS+05:00" (or null if not mentioned),\n'
                '  "opening_datetime_source_page": 1\n'
                "}\n"
            )

            # Use LLM provider
            provider = LLMProvider.get_provider_name()
            if provider == "groq":
                raw_out = LLMProvider._call_groq("You are a JSON-only data extractor.", prompt, [])
            elif provider == "gemini":
                raw_out = LLMProvider._call_gemini("You are a JSON-only data extractor.", prompt, [])
            elif provider == "openai":
                raw_out = LLMProvider._call_openai("You are a JSON-only data extractor.", prompt, [])
            else:
                return None

            # Extract JSON block
            json_match = re.search(r'\{.*\}', raw_out, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group(0))
            if data.get("has_deadline") and data.get("submission_deadline"):
                data["timezone"] = DEFAULT_TIMEZONE
                data["confidence"] = 0.95
                data["file_name"] = filename
                data["candidates"] = []
                print(f"[DeadlineExtractor] LLM fallback successfully extracted deadline: {data.get('submission_deadline')} for '{filename}'")
                return data
        except Exception as err:
            print(f"[DeadlineExtractor] LLM extraction error: {err}")
        return None
