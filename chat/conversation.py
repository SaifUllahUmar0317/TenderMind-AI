class ConversationMemory:
    """
    Manages in-memory chat session history and contextual query reformulation.
    """

    _sessions = {}

    @classmethod
    def get_history(cls, session_id: str = "default") -> list:
        return cls._sessions.get(session_id, [])

    @classmethod
    def add_user_message(cls, question: str, session_id: str = "default"):
        if session_id not in cls._sessions:
            cls._sessions[session_id] = []
        cls._sessions[session_id].append({"role": "user", "content": question})

    @classmethod
    def add_assistant_message(cls, answer: str, citations: list = None, session_id: str = "default"):
        if session_id not in cls._sessions:
            cls._sessions[session_id] = []
        cls._sessions[session_id].append({
            "role": "assistant",
            "content": answer,
            "citations": citations or []
        })

    @classmethod
    def clear_session(cls, session_id: str = "default"):
        cls._sessions[session_id] = []

    @classmethod
    def reformulate_query(cls, question: str, session_id: str = "default") -> str:
        """
        Prevents context contamination between independent questions while preserving
        conversational context only for genuine, short anaphoric follow-ups
        (e.g., 'Why?', 'Explain that in detail', 'Tell me more about it').
        """
        history = cls.get_history(session_id)
        if not history:
            return question

        q_lower = question.lower().strip()
        words = q_lower.split()

        # Standalone intent indicators — NEVER contaminate these with prior context
        standalone_keywords = [
            "deadline", "submission", "opening", "earnest", "bid security",
            "cdr", "call deposit", "eligibility", "qualification", "payment",
            "delivery", "warranty", "equipment", "specification", "specifications",
            "boq", "schedule", "summary", "summarize", "overview", "procuring",
            "agency", "contact", "scope", "link", "links", "url", "urls"
        ]
        if any(k in q_lower for k in standalone_keywords):
            return question

        # Pure follow-up patterns
        pure_followups = [
            "explain that", "tell me more", "why", "how come", "what about that",
            "elaborate", "can you explain", "what else", "details please"
        ]
        is_pure_followup = any(q_lower.startswith(pf) or q_lower == pf for pf in pure_followups)

        # Very short queries with pronouns like 'it', 'them'
        has_anaphora = len(words) <= 5 and any(w in ["it", "them", "that", "those", "these"] for w in words)

        if (is_pure_followup or has_anaphora) and len(history) >= 2:
            last_user_q = ""
            for msg in reversed(history):
                if msg.get("role") == "user":
                    last_user_q = msg.get("content", "")
                    break
            if last_user_q and last_user_q != question:
                return f"{last_user_q} - {question}"

        return question
