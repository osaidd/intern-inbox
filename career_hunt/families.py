# Deterministic role-family classification by title keyword, first match wins,
# checked in this order (target families; data analysis de-prioritized).
# Specific families (gtm, product, ai) outrank the broad "engineering intern" net,
# else "GTM Engineering Intern" would read as software engineering.
ROLE_FAMILIES = [
    ("gtm / growth", ["gtm", "growth", "sales", "marketing", "customer"]),
    ("product", ["product manager", "product management", "pm intern",
                 "product analyst"]),
    ("ai engineering", ["ai engineer", "machine learning", "ml engineer",
                        "gen ai", "genai"]),
    ("software engineering", ["software engineer", "engineering intern", "developer",
                              "swe", "full stack", "backend", "frontend"]),
    ("operations", ["operations", "ops", "founders associate", "chief of staff",
                    "business operations"]),
    ("data / analytics", ["data analyst", "data science", "analytics",
                          "business intelligence", "business analyst"]),
]


def role_family(title: str) -> str:
    t = (title or "").lower()
    return next((fam for fam, kws in ROLE_FAMILIES if any(k in t for k in kws)),
                "other")
