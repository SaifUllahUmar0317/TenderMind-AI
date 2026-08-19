import os
import re
import requests
import config
from llm.prompts import (
    TENDER_SUMMARY_PROMPT,
    EQUIPMENT_SCHEDULE_PROMPT,
    DEADLINE_PROMPT,
    BID_OPENING_PROMPT,
    BID_SECURITY_PROMPT,
    DELIVERY_SCHEDULE_PROMPT,
    PAYMENT_TERMS_PROMPT,
    ELIGIBILITY_PROMPT,
    WARRANTY_PROMPT,
    GENERAL_RAG_PROMPT,
    RAG_SYSTEM_PROMPT
)

class LLMProvider:
    """
    Pluggable LLM Abstraction Provider supporting Groq, Google Gemini, OpenAI,
    and an Intelligent Offline Grounded RAG Synthesis Engine fallback.
    Enforces deterministic intent classification, context validation, and schema rendering.
    """

    @classmethod
    def get_provider_name(cls) -> str:
        provider = os.getenv("LLM_PROVIDER", "").lower()
        if provider:
            return provider
        if os.getenv("GROQ_API_KEY"):
            return "groq"
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return "gemini"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return "offline_rag"

    @classmethod
    def classify_question_type(cls, question: str) -> str:
        """
        Classifies user inquiry into one of the specialized intent categories:
        1. TENDER_SUMMARY
        2. TENDER_DEADLINE
        3. BID_OPENING
        4. BID_SECURITY (Earnest Money / CDR)
        5. EQUIPMENT_SPECIFICATIONS (Equipment / BOQ / Technical Specs)
        6. DELIVERY_SCHEDULE
        7. PAYMENT_TERMS
        8. ELIGIBILITY_REQUIREMENTS
        9. WARRANTY
        10. PRODUCT_SEARCH
        11. GENERAL_DOCUMENT_QUESTION
        """
        q = question.lower().strip()

        # 1. Product Search / Links Intent
        if re.search(r'\b(?:official\s+)?links?\s+for\s+(?:all\s+)?(?:the\s+)?(?:required\s+)?equipments?\b', q) or re.search(r'\bproduct\s+links?\b', q):
            return "PRODUCT_SEARCH"

        # 2. Equipment / Specifications / BOQ Intent
        equipment_patterns = [
            r'\b(?:list|extract|give|show|what\s+are|all)\s+(?:all\s+)?(?:the\s+)?(?:equipment|equipments|items?|materials?|hardware|products?)\b',
            r'\b(?:technical\s+)?specifications?\b',
            r'\btechnical\s+details?\b',
            r'\btechnical\s+requirements?\b',
            r'\b(?:equipment|item)\s+schedule\b',
            r'\bquantities\s+and\s+specifications?\b',
            r'\b(?:schedule\s+of\s+requirements|bill\s+of\s+quantities|boq)\b',
            r'\bwhat\s+(?:equipment|items?|products?)\s+(?:is|are)\s+required\b',
            r'\b(?:all\s+)?ac\s+specifications?\b',
            r'\bdescription\s+and\s+quantit(?:y|ies)\b',
            r'\bquantit(?:y|ies)\s+and\s+(?:specs?|specifications?)\b'
        ]
        if any(re.search(pat, q) for pat in equipment_patterns):
            return "EQUIPMENT_SPECIFICATIONS"

        # 3. Bid Opening Intent (check before deadline so opening questions are isolated)
        if re.search(r'\b(bid\s+opening|opening\s+of\s+bids|when\s+will\s+(?:the\s+)?bids?\s+be\s+opened|tender\s+opening|opening\s+time|opening\s+date|opening\s+venue)\b', q):
            return "BID_OPENING"

        # 4. Tender Deadline Intent
        if re.search(r'\b(deadline|submission\s+date|closing\s+date|last\s+date|when\s+is\s+the\s+(?:tender|submission|bid)|when\s+does\s+this\s+tender\s+close|closing\s+time|submission\s+time|date\s+and\s+time\s+for\s+bid\s+submission|last\s+date\s+to\s+submit)\b', q):
            return "TENDER_DEADLINE"

        # 5. Bid Security / Earnest Money Intent
        if re.search(r'\b(earnest\s+money|bid\s+security|call\s+deposit|cdr|security\s+deposit|bank\s+guarantee|performance\s+bond)\b', q):
            return "BID_SECURITY"

        # 6. Tender Summary Intent
        if re.search(r'\b(summarize|summary|overview|main\s+findings|requirements\s+and\s+deadlines|important\s+requirements|what\s+is\s+this\s+tender\s+about)\b', q):
            return "TENDER_SUMMARY"

        # 7. Delivery Schedule Intent
        if re.search(r'\b(delivery\s+schedule|delivery\s+period|delivery\s+timeline|completion\s+time|supply\s+order\s+timeline|place\s+of\s+delivery|when\s+must\s+equipment\s+be\s+delivered)\b', q):
            return "DELIVERY_SCHEDULE"

        # 8. Payment Terms Intent
        if re.search(r'\b(payment\s+terms?|payment\s+schedule|payment\s+mode|invoicing|advance\s+payment|payment\s+milestones?|how\s+will\s+payment\s+be\s+released)\b', q):
            return "PAYMENT_TERMS"

        # 9. Eligibility Requirements Intent
        if re.search(r'\b(eligibility|qualification|mandatory\s+requirements?|bidder\s+requirements?|turnover|tax\s+registration|ntn|pec|mandatory\s+documents?|who\s+is\s+eligible)\b', q):
            return "ELIGIBILITY_REQUIREMENTS"

        # 10. Warranty Intent
        if re.search(r'\b(warranty|maintenance|guarantee\s+period|compressor\s+warranty|pcb\s+warranty|after[- ]sales)\b', q):
            return "WARRANTY"

        return "GENERAL_DOCUMENT_QUESTION"

    @classmethod
    def generate_rag_answer(cls, question: str, retrieved_chunks: list, chat_history: list = None, summary_data: dict = None, question_type: str = None) -> dict:
        """
        Synthesizes a grounded, structured answer with validated context and page citations.
        """
        qtype = question_type or cls.classify_question_type(question)

        # Normalize legacy qtype identifiers
        if qtype in ["summary", "SUMMARY"]:
            qtype = "TENDER_SUMMARY"
        elif qtype in ["equipment_specs", "equipment", "EQUIPMENT", "TECHNICAL_SPECIFICATIONS", "BOQ"]:
            qtype = "EQUIPMENT_SPECIFICATIONS"
        elif qtype in ["deadline", "DEADLINE"]:
            qtype = "TENDER_DEADLINE"
        elif qtype in ["bid_opening", "BID_OPENING"]:
            qtype = "BID_OPENING"
        elif qtype in ["bid_security", "earnest_money", "EARNEST_MONEY", "BID_SECURITY"]:
            qtype = "BID_SECURITY"
        elif qtype in ["equipment_links", "PRODUCT_SEARCH"]:
            qtype = "PRODUCT_SEARCH"
        elif qtype in ["delivery", "DELIVERY"]:
            qtype = "DELIVERY_SCHEDULE"
        elif qtype in ["payment", "PAYMENT"]:
            qtype = "PAYMENT_TERMS"
        elif qtype in ["eligibility", "ELIGIBILITY"]:
            qtype = "ELIGIBILITY_REQUIREMENTS"
        elif qtype in ["warranty", "WARRANTY"]:
            qtype = "WARRANTY"
        elif qtype in ["specific_question", "GENERAL_DOCUMENT_QUESTION"]:
            qtype = "GENERAL_DOCUMENT_QUESTION"

        # Specialized Fast & Complete Equipment Schedule Generator
        if qtype == "EQUIPMENT_SPECIFICATIONS":
            structured_items = summary_data.get("structured_equipment", []) if summary_data else []
            if structured_items:
                formatted_response = cls._format_structured_equipment_response(structured_items)
                all_pages = []
                for itm in structured_items:
                    for p in itm.get("source_pages", []):
                        if p not in all_pages:
                            all_pages.append(p)
                citations = [{"page": p, "section": "Technical Specifications", "source": "Document Extraction"} for p in sorted(all_pages)]

                return {
                    "answer": formatted_response,
                    "citations": citations,
                    "provider": "structured_table_engine",
                    "question_type": qtype
                }

        # Build Context from retrieved chunks and document summaries
        citations = []
        context_parts = []

        for idx, chunk in enumerate(retrieved_chunks):
            p = chunk.get("page_start", chunk.get("page_number", 1))
            sec = chunk.get("section", chunk.get("section_name", "General"))
            text = chunk.get("text", "").strip()
            source = chunk.get("source", "PDF Text")

            citation_tag = f"Page {p}"
            citations.append({
                "page": p,
                "section": sec,
                "source": source
            })

            context_parts.append(
                f"--- EXCERPT {idx+1} ({citation_tag} | Section: {sec}) ---\n{text}"
            )

        if summary_data:
            doc_meta = []
            if summary_data.get("filename"):
                doc_meta.append(f"Document: {summary_data['filename']}")
            if summary_data.get("metadata_kv"):
                for kv in summary_data["metadata_kv"]:
                    p = kv.get("page", 1)
                    doc_meta.append(f"- {kv['key']}: {kv['value']} *(Page {p})*")
            if doc_meta:
                context_parts.insert(0, "--- DOCUMENT CORE METADATA ---\n" + "\n".join(doc_meta))

        # Include structured tables if available
        if summary_data and summary_data.get("extracted_tables"):
            spec_tables = []
            for tbl in summary_data["extracted_tables"]:
                t_page = tbl.get("page", 1)
                t_md = tbl.get("table_md", "")
                if t_md:
                    spec_tables.append(f"--- DOCUMENT TABLE (Page {t_page}) ---\n{t_md}")
            if spec_tables:
                context_parts.append("\n\n".join(spec_tables))

        formatted_context = "\n\n".join(context_parts)

        # Route to Intent-Specific Prompt Schema
        if qtype == "TENDER_SUMMARY":
            prompt_template = TENDER_SUMMARY_PROMPT
        elif qtype == "EQUIPMENT_SPECIFICATIONS":
            prompt_template = EQUIPMENT_SCHEDULE_PROMPT
        elif qtype == "TENDER_DEADLINE":
            prompt_template = DEADLINE_PROMPT
        elif qtype == "BID_OPENING":
            prompt_template = BID_OPENING_PROMPT
        elif qtype == "BID_SECURITY":
            prompt_template = BID_SECURITY_PROMPT
        elif qtype == "DELIVERY_SCHEDULE":
            prompt_template = DELIVERY_SCHEDULE_PROMPT
        elif qtype == "PAYMENT_TERMS":
            prompt_template = PAYMENT_TERMS_PROMPT
        elif qtype == "ELIGIBILITY_REQUIREMENTS":
            prompt_template = ELIGIBILITY_PROMPT
        elif qtype == "WARRANTY":
            prompt_template = WARRANTY_PROMPT
        else:
            prompt_template = GENERAL_RAG_PROMPT

        system_prompt = prompt_template.format(context=formatted_context)
        provider_name = cls.get_provider_name()

        try:
            if provider_name == "groq":
                raw_answer = cls._call_groq(system_prompt, question, chat_history)
            elif provider_name == "gemini":
                raw_answer = cls._call_gemini(system_prompt, question, chat_history)
            elif provider_name == "openai":
                raw_answer = cls._call_openai(system_prompt, question, chat_history)
            else:
                raw_answer = cls._call_offline_rag(retrieved_chunks, question, summary_data, qtype)
        except Exception:
            raw_answer = cls._call_offline_rag(retrieved_chunks, question, summary_data, qtype)

        # Apply strict normalization and formatting rules
        answer = cls._clean_and_normalize_response(raw_answer, qtype)

        return {
            "answer": answer,
            "citations": citations,
            "provider": provider_name,
            "question_type": qtype
        }

    @classmethod
    def _format_structured_equipment_response(cls, structured_items: list) -> str:
        """
        Formats extracted equipment records directly into the required deterministic Markdown schema.
        """
        lines = ["## EQUIPMENT SCHEDULE\n"]

        for idx, item in enumerate(structured_items):
            s_num = item.get("serial_number", str(idx + 1))
            name = item.get("name", "Equipment Item")
            qty = item.get("quantity", "Not specified")
            specs = item.get("specifications", [])
            pages = item.get("source_pages", [])

            if len(pages) == 1:
                page_str = f"Page {pages[0]}"
            elif len(pages) > 1:
                page_str = f"Pages {pages[0]}–{pages[-1]}"
            else:
                page_str = "Page 1"

            lines.append(f"### {s_num}. {name}\n")
            lines.append(f"- **Quantity:** {qty}")

            if specs:
                for sp in specs:
                    lines.append(f"- **Specification:** {sp}")
            else:
                lines.append("- **Specification:** As per tender schedule of requirements.")

            lines.append(f"- **Source:** {page_str}\n")

        return "\n".join(lines).strip()

    @classmethod
    def _clean_and_normalize_response(cls, text: str, qtype: str = "GENERAL_DOCUMENT_QUESTION") -> str:
        """
        Cleans LLM response artifacts while PRESERVING valid Markdown.
        """
        if not text:
            return ""

        # Step 1: Remove explicit <think>...</think> XML blocks
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()

        # Step 2: Strip any planning / reasoning preamble that precedes the real answer
        thought_indicators = [
            r'Here\'?s a thinking process',
            r'Analyze User (?:Input|Request|Query|Prompt)',
            r'Analyze (?:Input|Request|Query|Prompt|User)',
            r'Check (?:System Prompt|Formatting|Constraints)',
            r'Scan (?:Retrieved )?Context',
            r'Extract (?:Information|Data|Items|Specs) from Context',
            r'Thought Process:',
            r'Thinking Process:',
            r'Draft Response',
            r'Mental Refinement',
            r'Let\'?s (?:parse|extract|check|scan|analyze)'
        ]

        if any(re.search(pat, text[:1200], re.IGNORECASE) for pat in thought_indicators):
            matches = list(re.finditer(
                r'(?:^|\n)(#{1,3}\s+\S|##\s|###\s|\*\*[A-Z]|[A-Z][^\n]{10,})',
                text, re.IGNORECASE
            ))
            real_start = None
            for m in matches:
                snippet = text[m.start():m.start() + 200]
                if ('[Equipment Name]' not in snippet
                        and '[Item Name]' not in snippet
                        and '[Page X]' not in snippet
                        and '[value]' not in snippet):
                    real_start = m.start()
                    break

            if real_start is not None:
                text = text[real_start:].strip()

        # Step 3: Remove ``` markdown/code fence wrappers around the ENTIRE response
        stripped = text.strip()
        if stripped.startswith('```'):
            first_newline = stripped.find('\n')
            if first_newline != -1:
                rest = stripped[first_newline + 1:]
                if rest.rstrip().endswith('```'):
                    text = rest.rstrip()[:-3].strip()

        # Step 4: Strip stray raw HTML tags
        text = re.sub(r'<(?!br\s*/?|p\b)[a-zA-Z][^>]{0,60}>', '', text)
        text = re.sub(r'</[a-zA-Z]{1,20}>', '', text)

        # Step 5: Normalize excessive blank lines (max 2 consecutive)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # Step 6: Ensure heading consistency for structured intents
        if qtype == "TENDER_SUMMARY":
            text = re.sub(r'^(?:#{1,3}|\*\*|__)?\s*Tender\s+Summary\s*(?:\*\*|__)?\s*', '', text, flags=re.IGNORECASE).strip()
            if not text.startswith("## TENDER SUMMARY"):
                text = "## TENDER SUMMARY\n\n" + text
        elif qtype == "EQUIPMENT_SPECIFICATIONS":
            if not text.startswith("## EQUIPMENT SCHEDULE") and not text.startswith("## EQUIPMENT &"):
                text = "## EQUIPMENT SCHEDULE\n\n" + text

        return text.strip()

    @classmethod
    def _clean_llm_response(cls, text: str) -> str:
        """Backward-compatible helper calling _clean_and_normalize_response."""
        return cls._clean_and_normalize_response(text, "GENERAL_DOCUMENT_QUESTION")

    @classmethod
    def _call_groq(cls, system_prompt: str, question: str, chat_history: list) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set.")

        env_model = os.getenv("LLM_MODEL", "").strip()
        models_to_try = [m for m in [
            env_model,
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama-3.2-11b-vision-preview",
            "llama-3.2-3b-preview",
            "llama3-70b-8192",
            "openai/gpt-oss-120b"
        ] if m]

        seen = set()
        unique_models = []
        for m in models_to_try:
            if m not in seen:
                seen.add(m)
                unique_models.append(m)

        messages = [{"role": "system", "content": system_prompt}]
        if chat_history:
            for msg in chat_history[-4:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        user_prompt = f"Question: {question}\n\nPlease provide a clear, accurate answer strictly following the required output format and grounded in the document context."
        messages.append({"role": "user", "content": user_prompt})

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        last_err = None

        for model in unique_models:
            payload = {"model": model, "messages": messages, "temperature": 0.0, "max_tokens": 1500}
            try:
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    msg_obj = data["choices"][0]["message"]
                    content = (msg_obj.get("content") or "").strip()
                    if content:
                        return content
                else:
                    err_msg = res.json().get("error", {}).get("message", f"HTTP {res.status_code}")
                    last_err = Exception(f"Groq [{model}] failed: {err_msg}")
            except Exception as e:
                last_err = e

        raise last_err or Exception("All Groq models failed.")

    @classmethod
    def _call_gemini(cls, system_prompt: str, question: str, chat_history: list) -> str:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        model = os.getenv("LLM_MODEL", "gemini-1.5-flash")
        combined_prompt = f"{system_prompt}\n\nUser Question: {question}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": combined_prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1000}}
        res = requests.post(url, json=payload, timeout=15)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    @classmethod
    def _call_openai(cls, system_prompt: str, question: str, chat_history: list) -> str:
        api_key = os.getenv("OPENAI_API_KEY", "dummy")
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": messages, "temperature": 0.1}
        res = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=15)
        return res.json()["choices"][0]["message"]["content"].strip()

    # --------------------------------------------------------------------------
    # OFFLINE GROUNDED RAG ENGINE
    # --------------------------------------------------------------------------
    @classmethod
    def _call_offline_rag(cls, retrieved_chunks: list, question: str, summary_data: dict, qtype: str = "GENERAL_DOCUMENT_QUESTION") -> str:
        if not retrieved_chunks and not summary_data:
            return "I could not locate this information in the uploaded tender document."

        # 1. Summary intent
        if qtype == "TENDER_SUMMARY":
            doc_name = summary_data.get("filename", "this tender document").replace(".pdf", "") if summary_data else "this tender document"
            doc_id = summary_data.get("doc_id", "") if summary_data else ""

            # --- Pull stored deadline data if available ---
            submission_deadline_str = ""
            opening_datetime_str = ""
            tender_title = ""
            organization = ""
            try:
                from deadlines.database import DeadlineDatabase
                if doc_id:
                    stored = DeadlineDatabase.get_tender_deadline(doc_id)
                    if stored:
                        sub_iso = stored.get("submission_deadline", "")
                        op_iso = stored.get("opening_datetime", "")
                        tender_title = stored.get("tender_title", "")
                        organization = stored.get("organization", "")
                        if sub_iso:
                            from datetime import datetime
                            try:
                                dt = datetime.fromisoformat(sub_iso)
                                submission_deadline_str = dt.strftime("%B %d, %Y at %I:%M %p")
                            except Exception:
                                submission_deadline_str = sub_iso
                        if op_iso:
                            try:
                                dt = datetime.fromisoformat(op_iso)
                                opening_datetime_str = dt.strftime("%B %d, %Y at %I:%M %p")
                            except Exception:
                                opening_datetime_str = op_iso
            except Exception:
                pass

            # --- Extract from retrieved chunks if not in DB ---
            all_text = " ".join([c.get("text", "") for c in retrieved_chunks])

            if not submission_deadline_str:
                dl_match = re.search(
                    r'(?:reach|submitted?|submission|deadline|last\s+date|closing\s+date|close\s+of\s+office)[^\n]{0,80}?'
                    r'(\d{1,2}[/\-. ]\d{1,2}[/\-. ]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})',
                    all_text, re.IGNORECASE
                )
                if dl_match:
                    submission_deadline_str = dl_match.group(1).strip()

            # --- Bid Security ---
            bs_match = re.search(
                r'(?:bid\s+security|earnest\s+money|call\s+deposit|cdr)[^\n]{0,120}?(\d+(?:\.\d+)?\s*%[^\n.]{0,60})',
                all_text, re.IGNORECASE
            )
            if not bs_match:
                bs_match = re.search(
                    r'(\d+(?:\.\d+)?\s*%)[^\n]{0,60}?(?:bid\s+security|earnest\s+money|call\s+deposit|cdr)',
                    all_text, re.IGNORECASE
                )
            bid_security_str = bs_match.group(0).strip() if bs_match else ""

            # --- Scope extraction from first section summaries ---
            scope_text = ""
            if summary_data and summary_data.get("section_summaries"):
                intro_sections = [s for s in summary_data["section_summaries"] if s.get("page_start", 99) <= 4]
                if intro_sections:
                    scope_text = intro_sections[0].get("text", "") or intro_sections[0].get("summary", "")

            if not scope_text and retrieved_chunks:
                # Use earliest-page chunk text as scope
                sorted_chunks = sorted(retrieved_chunks, key=lambda c: c.get("page_start", 99))
                scope_text = sorted_chunks[0].get("text", "")

            # Clean scope to 2-3 sentences
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', scope_text) if len(s.strip()) > 15]
            scope_summary = " ".join(sentences[:3])

            # --- Build title and org strings ---
            if not tender_title and summary_data:
                tender_title = summary_data.get("title", "") or summary_data.get("tender_title", "")
            if not organization and summary_data:
                organization = summary_data.get("organization", "")

            # --- Build response ---
            heading_parts = []
            if tender_title:
                heading_parts.append(f"**{tender_title}**")
            heading_parts.append(f"issued by **{organization}**" if organization else "")
            heading = " ".join(p for p in heading_parts if p)

            overview_line = scope_summary if scope_summary else f"This tender document outlines the requirements and procurement guidelines for **{doc_name}**."
            if heading:
                overview_line = f"{heading}\n\n{overview_line}"

            details = []
            # Source pages for key info
            p_dl = next((c.get("page_start", 1) for c in retrieved_chunks if any(w in c.get("text","").lower() for w in ["submission","deadline","last date","closing"])), 1)
            p_bs = next((c.get("page_start", 1) for c in retrieved_chunks if any(w in c.get("text","").lower() for w in ["bid security","earnest money","call deposit","cdr"])), 1)

            if submission_deadline_str:
                details.append(f"- **Tender submission deadline:** **{submission_deadline_str}** *(Source: Page {p_dl})*")
            else:
                details.append("- **Tender submission deadline:** Not found — please check the tender notice (Page 1–4) of the document.")

            if opening_datetime_str and opening_datetime_str != submission_deadline_str:
                details.append(f"- **Bid opening date/time:** **{opening_datetime_str}** *(Source: Page {p_dl})*")

            if bid_security_str:
                details.append(f"- **Earnest money / bid security:** **{bid_security_str}** *(Source: Page {p_bs})*")
            else:
                details.append("- **Earnest money / bid security:** Not specified in retrieved sections.")

            details.append("- **Bid validity:** As specified in the tender document.")
            details.append("- **Eligibility:** As per instructions to bidders.")
            details.append("- **Delivery schedule:** As per schedule of requirements.")
            details.append("- **Payment terms:** As per tender terms and conditions.")
            details.append("- **Warranty:** As per technical specifications.")

            return f"## TENDER SUMMARY\n\n### Overview\n{overview_line}\n\n### Important Details\n" + "\n".join(details)

        # 2. Deadline intent — check stored deadline first, then scan chunks
        elif qtype == "TENDER_DEADLINE":
            # First: try stored deadline from DeadlineDatabase
            doc_id = summary_data.get("doc_id", "") if summary_data else ""
            if doc_id:
                try:
                    from deadlines.database import DeadlineDatabase
                    stored = DeadlineDatabase.get_tender_deadline(doc_id)
                    if stored and stored.get("submission_deadline"):
                        from datetime import datetime
                        sub_iso = stored["submission_deadline"]
                        try:
                            dt = datetime.fromisoformat(sub_iso)
                            friendly_date = dt.strftime("%B %d, %Y at %I:%M %p")
                        except Exception:
                            friendly_date = sub_iso
                        pg = stored.get("submission_deadline_source_page", 1)
                        return f"The tender submission deadline is **{friendly_date}**.\n**Source: Page {pg}**"
                except Exception:
                    pass

            # Second: scan retrieved chunks with broad date patterns
            MONTH_RE = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
            date_patterns = [
                # "reach ... by 11:00 AM on or before August 24, 2026"
                rf'(?:reach|submitted?|submission|deadline|last\s+date|closing\s+date|close\s+of\s+office|on\s+or\s+before)[^\n]{{0,120}}?({MONTH_RE}\s+\d{{1,2}},?\s+\d{{4}}[^\n]{{0,30}})',
                # "August 24, 2026 ... by 11:00 AM"
                rf'({MONTH_RE}\s+\d{{1,2}},?\s+\d{{4}})[^\n]{{0,60}}?(?:by|before|upto|at)',
                # Numeric date with surrounding keyword
                r'(?:last\s+date|submission\s+deadline|closing\s+date|bid\s+closing|submitted\s+by)[^\n]{0,120}?(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})',
                # "DD Month YYYY"
                rf'(\d{{1,2}}\s+{MONTH_RE}\s+\d{{4}})',
            ]
            for c in retrieved_chunks:
                t = c.get("text", "")
                for pat in date_patterns:
                    m = re.search(pat, t, re.IGNORECASE)
                    if m:
                        p = c.get("page_start", c.get("page_number", 1))
                        matched = m.group(1).strip() if m.lastindex else m.group(0).strip()
                        return f"The tender submission deadline is **{matched}**.\n**Source: Page {p}**"
            return "I could not locate the exact submission deadline in the retrieved sections. Please check the tender notice (usually Page 1–3) of the uploaded document."

        # 3. Bid Opening intent
        elif qtype == "BID_OPENING":
            open_patterns = [
                r'(?:bids\s+will\s+be\s+opened|opening\s+of\s+(?:technical\s+)?bids|bid\s+opening)[^\n]{0,120}?(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'(?:opened\s+on|opening\s+date)[^\n]{0,80}(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})',
            ]
            for c in retrieved_chunks:
                t = c.get("text", "")
                for pat in open_patterns:
                    m = re.search(pat, t, re.I)
                    if m:
                        p = c.get("page_start", c.get("page_number", 1))
                        return f"The tender bids will be opened at **{m.group(0).strip()}**.\n**Source: Page {p}**"
            return "I could not locate the bid opening date/time in the retrieved sections. Please check the tender notice of the uploaded document."

        # 4. Bid Security intent
        elif qtype == "BID_SECURITY":
            bs_patterns = [
                r'(?:bid\s+security|earnest\s+money|call\s+deposit|security\s+deposit|cdr)[^\n]{0,120}?(\d+(?:\.\d+)?\s*%\s*(?:of\s+(?:the\s+)?(?:bid|total\s+bid|contract)[^\n]{0,40})?|rs\.?\s*[\d,]+(?:\s*\/?\s*-)?)',
                r'(\d+(?:\.\d+)?\s*%)[^\n]{0,60}?(?:bid\s+security|earnest\s+money|security\s+deposit)',
            ]
            for c in retrieved_chunks:
                t = c.get("text", "")
                for pat in bs_patterns:
                    m = re.search(pat, t, re.I)
                    if m:
                        p = c.get("page_start", c.get("page_number", 1))
                        return f"The required bid security / earnest money is **{m.group(0).strip()}**, submitted in the specified form according to the tender document.\n**Source: Page {p}**"
            return "I could not locate the exact bid security amount in the retrieved sections. Please check the tender notice or financial requirements section."

        # 5. Equipment Specifications intent
        elif qtype == "EQUIPMENT_SPECIFICATIONS":
            structured_items = summary_data.get("structured_equipment", []) if summary_data else []
            if structured_items:
                return cls._format_structured_equipment_response(structured_items)

            # If no pre-extracted structured equipment, check if table markdown is available in chunks
            table_chunks = [c for c in retrieved_chunks if c.get("is_table") or "table" in c.get("content_type", "")]
            if table_chunks:
                p = table_chunks[0].get("page_start", 1)
                t_text = table_chunks[0].get("text", "").strip()
                # Parse lines looking for items
                lines = [l.strip() for l in t_text.split("\n") if l.strip() and not l.startswith("| ---")]
                if len(lines) >= 3:
                    items_found = []
                    for line in lines:
                        if "|" in line:
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if len(parts) >= 2 and not any(h in parts[0].lower() for h in ["s#", "item", "description", "sr."]):
                                name = parts[1] if len(parts) > 2 and parts[0].isdigit() else parts[0]
                                qty = parts[2] if len(parts) > 2 else "As specified"
                                items_found.append(f"### {len(items_found)+1}. {name}\n- **Quantity:** {qty}\n- **Source:** Page {p}")
                    if items_found:
                        return "## EQUIPMENT SCHEDULE\n\n" + "\n\n".join(items_found[:15])

            p = retrieved_chunks[0].get("page_start", 1) if retrieved_chunks else 1
            return f"I could not locate an equipment schedule or technical specification table in the retrieved sections.\n\n**Source: Page {p}**"

        # 6. General fallback
        if not retrieved_chunks:
            return "I could not locate this information in the uploaded tender document."

        top_chunk = retrieved_chunks[0]
        p = top_chunk.get("page_start", top_chunk.get("page_number", 1))
        snippet = top_chunk.get("text", "").strip()
        # Clean sentences
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', snippet) if len(s.strip()) > 10]
        clean_text = " ".join(sentences[:3]) if sentences else snippet[:300]
        return f"{clean_text}\n\n**Source: Page {p}**"
