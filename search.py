# ═══════════════════════════════════════════════════════════
#  search.py — Knowledge Search (Tier 1, 2, 3)
# ═══════════════════════════════════════════════════════════

import re
import requests
from config import GOOGLE_API_KEY, GOOGLE_CX


STOPWORDS = {
    'the','for','and','are','that','this','with','from','have',
    'how','what','when','does','will','can','should','which',
    'oracle','please','give','tell','explain','show','list',
    'need','want','get','find','know','about','into','data'
}

# Minimum score for a Tier 1 hit to be considered a REAL match.
# Score = 3 per title match + 1 per body match.
# A question must score >= MIN_SCORE to be answered from KB only.
# If score is lower, it goes to Tier 2/3 even if there are weak matches.
MIN_SCORE = 5


def search_internal_kb(db, question: str) -> list:
    """
    Keyword-scored full-text search.
    Only returns results if the best match scores >= MIN_SCORE.
    This prevents generic keyword matches from blocking Tier 2/3.
    """
    q     = question.lower()
    words = [w for w in re.findall(r'\b\w{3,}\b', q) if w not in STOPWORDS]

    if not words:
        return []

    rows   = db.execute("SELECT * FROM knowledge ORDER BY created_at DESC").fetchall()
    scored = []

    for row in rows:
        text       = f"{row['title']} {row['description']} {row['code_block']} {row['tip']}".lower()
        title_text = row['title'].lower()
        score      = 0
        for word in words:
            if word in title_text:
                score += 3   # strong signal — word in title
            elif word in text:
                score += 1   # weak signal — word in body only
        if score >= MIN_SCORE:
            scored.append((score, dict(row)))

    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:5]]


# ── Tier 2 & 3: Google Custom Search ───────────────────────

def _google_search(query: str) -> list:
    """
    Search using your Custom Search Engine (CSE).
    Your CSE is already configured to search Oracle domains only
    (docs.oracle.com, blogs.oracle.com, community.oracle.com etc.)
    No need for site: restriction here — CSE handles it.
    """
    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx":  GOOGLE_CX,      # ← your CSE already restricts to Oracle domains
                "q":   query,
                "num": 4
            },
            timeout=8
        )
        if resp.status_code != 200:
            return []
        return [
            {
                "title":   item.get("title", ""),
                "link":    item.get("link", ""),
                "snippet": item.get("snippet", "")
            }
            for item in resp.json().get("items", [])
        ]
    except Exception as e:
        print(f"[Search error] {e}")
        return []


def search_oracle_docs(query: str) -> list:
    """
    Tier 2 — search Oracle domains via your CSE.
    CSE already configured to search:
      docs.oracle.com, blogs.oracle.com,
      community.oracle.com, support.oracle.com
    """
    return _google_search(query)


def search_web(query: str) -> list:
    """
    Also uses your Oracle CSE — just adds
    'Oracle Cloud Fusion' to keep results relevant.
    """
    return _google_search(f"Oracle Cloud Fusion {query}")


def format_results(results: list, label: str) -> str:
    if not results:
        return ""
    lines = [f"\n--- {label} ---"]
    for r in results:
        lines.append(f"• {r['title']}\n  URL: {r['link']}\n  {r['snippet']}")
    return "\n".join(lines)
