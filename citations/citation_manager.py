import re

class CitationManager:
    """
    Parses RAG answer text and formats page citations into interactive frontend buttons
    that navigate the PDF previewer directly to the referenced page.
    """

    @classmethod
    def format_citations_in_html(cls, text: str) -> str:
        """
        Replaces text citation patterns like [Page 14] or [Document.pdf — Page 14]
        with interactive HTML buttons.
        """
        if not text:
            return ""

        # Pattern matching [Page X] or [Doc — Page X] or [Page X — Section]
        pattern = r'\[(?:[^\]]*?\bPage\s+(\d+)\b[^\]]*?|Page\s+(\d+))\]'

        def replace_match(match):
            page_num = match.group(1) or match.group(2)
            if page_num:
                return (
                    f'<button type="button" class="citation-btn" data-page="{page_num}" title="Jump to Page {page_num} in PDF">'
                    f'<i data-lucide="bookmark"></i> Page {page_num}'
                    f'</button>'
                )
            return match.group(0)

        formatted_html = re.sub(pattern, replace_match, text, flags=re.IGNORECASE)
        return formatted_html
