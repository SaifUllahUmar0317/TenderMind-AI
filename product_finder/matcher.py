import re
from typing import List, Dict, Any

class SpecificationMatcher:
    """
    Evaluates tender requirement specifications against retrieved product specifications.
    Calculates transparent match scores and categorizes compliance status per feature.
    """

    @classmethod
    def match_product(cls, required_specs: List[str], product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compares product specifications against required tender specifications.
        """
        prod_specs = product.get("extracted_specs", [])
        prod_text = " ".join([str(s) for s in prod_specs] + [product.get("name", ""), product.get("highlights", "")]).lower()

        spec_comparisons = []
        matched = 0
        needs_verification = 0
        does_not_meet = 0

        for req in required_specs:
            req_str = str(req).strip()
            if not req_str:
                continue

            req_lower = req_str.lower()
            
            # Extract key tokens and numbers from the requirement
            key_tokens = [w for w in re.findall(r'[a-zA-Z0-9\.\-\/]+', req_lower) if len(w) > 1 and w not in ["minimum", "maximum", "required", "with", "and", "or", "the", "for", "upto", "standard"]]

            status = "needs_verification"
            explanation = "Specification requires manual verification."
            found_evidence = ""

            if not key_tokens:
                status = "meets"
                explanation = "Standard requirement satisfied."
                matched += 1
            else:
                matches = sum(1 for tok in key_tokens if tok in prod_text)
                ratio = matches / len(key_tokens)

                if ratio >= 0.7:
                    status = "meets"
                    explanation = "Product specifications satisfy requirement."
                    # Find closest matching snippet
                    for ps in prod_specs:
                        if any(tok in str(ps).lower() for tok in key_tokens[:2]):
                            found_evidence = str(ps)
                            break
                    matched += 1
                elif ratio >= 0.35:
                    status = "needs_verification"
                    explanation = "Partial match found in product documentation."
                    needs_verification += 1
                else:
                    status = "does_not_meet"
                    explanation = "Requirement not detected in product specifications."
                    does_not_meet += 1

            spec_comparisons.append({
                "requirement": req_str,
                "status": status,  # "meets" | "needs_verification" | "does_not_meet"
                "status_label": "Meets Requirement" if status == "meets" else ("Needs Verification" if status == "needs_verification" else "Does Not Meet"),
                "status_icon": "check" if status == "meets" else ("alert-triangle" if status == "needs_verification" else "x"),
                "explanation": explanation,
                "evidence": found_evidence or "Not explicitly listed"
            })

        total_reqs = len(spec_comparisons)
        if total_reqs > 0:
            # Weighted calculation: Meets=1.0, Needs Verification=0.5, Does Not Meet=0.0
            weighted_score = (matched * 1.0 + needs_verification * 0.5) / total_reqs
            score_percent = int(round(weighted_score * 100))
        else:
            score_percent = 100

        return {
            "score_percent": score_percent,
            "matched_count": matched,
            "partial_count": needs_verification,
            "failed_count": does_not_meet,
            "total_count": total_reqs,
            "summary_label": f"{matched}/{total_reqs} requirements satisfied",
            "comparisons": spec_comparisons
        }

    @classmethod
    def compare_multiple_products(cls, required_specs: List[str], products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Creates a side-by-side comparison matrix for multiple products.
        """
        matrix_rows = []
        for req in required_specs:
            row = {"requirement": req, "product_statuses": []}
            for prod in products:
                matching = cls.match_product([req], prod)
                comp = matching["comparisons"][0] if matching["comparisons"] else {}
                row["product_statuses"].append({
                    "product_name": prod.get("name", "Product"),
                    "status": comp.get("status", "needs_verification"),
                    "status_label": comp.get("status_label", "Needs Verification"),
                    "evidence": comp.get("evidence", "")
                })
            matrix_rows.append(row)

        return {
            "requirements": required_specs,
            "products": products,
            "matrix": matrix_rows
        }
