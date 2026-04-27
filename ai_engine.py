# ═══════════════════════════════════════════════════════════
#  ai_engine.py — LLM Client, Classification & Card Generation
# ═══════════════════════════════════════════════════════════

import json
from openai import OpenAI
from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL

client = OpenAI(
    api_key  = LLM_API_KEY,
    base_url = LLM_API_URL.rstrip("/") + "/v1"
)

# ── Auto-Classification ─────────────────────────────────────
# PDH is now a standalone module with 5 submodules

MODULE_MAP = {
    # Finance
    "accounts receivable":  ("Finance", "AR"),
    " ar ":                 ("Finance", "AR"),
    "accounts payable":     ("Finance", "AP"),
    " ap ":                 ("Finance", "AP"),
    "supplier invoice":     ("Finance", "AP"),
    "general ledger":       ("Finance", "GL"),
    " gl ":                 ("Finance", "GL"),
    "journal":              ("Finance", "GL"),
    "chart of accounts":    ("Finance", "GL"),
    "coa":                  ("Finance", "GL"),
    "project":              ("Finance", "Projects"),
    "revenue recognition":  ("Finance", "Projects"),
    # SCM
    "inventory":            ("SCM",     "Inventory"),
    "on-hand":              ("SCM",     "Inventory"),
    "procurement":          ("SCM",     "Procurement"),
    "purchase order":       ("SCM",     "Procurement"),
    " po ":                 ("SCM",     "Procurement"),
    # PDH — standalone module, matched BEFORE generic "item" keywords
    "item revision":        ("PDH",     "ItemRevisions"),
    "item structure":       ("PDH",     "ItemStructure"),
    "bom":                  ("PDH",     "ItemStructure"),
    "bill of material":     ("PDH",     "ItemStructure"),
    "item relationship":    ("PDH",     "ItemRelationship"),
    "item categor":         ("PDH",     "ItemCategories"),
    "item effectiv":        ("PDH",     "ItemEff"),
    "item eff":             ("PDH",     "ItemEff"),
    "egp_system_items":     ("PDH",     "ItemMaster"),
    "item import":          ("PDH",     "ItemMaster"),
    "item master":          ("PDH",     "ItemMaster"),
    "item number":          ("PDH",     "ItemMaster"),
    "pdh":                  ("PDH",     "ItemMaster"),
    "product data hub":     ("PDH",     "ItemMaster"),
    "pim":                  ("PDH",     "ItemMaster"),
    "uom":                  ("PDH",     "ItemMaster"),
    # HCM
    "employee":             ("HCM",     "Employees"),
    "hire date":            ("HCM",     "Employees"),
    "national id":          ("HCM",     "Employees"),
    "payroll":              ("HCM",     "Payroll"),
    "salary":               ("HCM",     "Payroll"),
    "bank account":         ("HCM",     "Payroll"),
    "benefit":              ("HCM",     "Benefits"),
    "enrollment":           ("HCM",     "Benefits"),
    "dependent":            ("HCM",     "Benefits"),
}

CATEGORY_MAP = {
    "quality": [
        "date format", "special character", "validation", "format",
        "regex", "null", "duplicate", "mandatory", "field value",
        "blank", "error", "violation", "invalid", "attribute"
    ],
    "load": [
        "batch", "load", "sequence", "import", "timeout",
        "prerequisite", "order", "fbdi", "ess", "schedule",
        "column", "template", "interface", "process", "step"
    ],
    "lineage": [
        "lineage", "impact", "dependency", "downstream",
        "blocks", "chain", "cross-module", "reconcil",
        "flow", "sequence", "before", "after"
    ],
}


def classify(question: str, answer: str) -> tuple:
    """
    Classify question + answer into (module, submodule, category).
    Falls back to ("PDH", "ItemMaster", "quality") for PDH questions.
    """
    text = f"{question} {answer}".lower()

    mod, sub = "All", "All"
    for kw, (m, s) in MODULE_MAP.items():
        if kw in text:
            mod, sub = m, s
            break

    best_cat, best_score = "quality", 0
    for cat, keywords in CATEGORY_MAP.items():
        score = sum(1 for k in keywords if k in text)
        if score > best_score:
            best_cat, best_score = cat, score

    return mod, sub, best_cat


# ── Knowledge Card Generation ───────────────────────────────

CARD_GEN_SYSTEM = """You are a knowledge extraction engine for the Oracle Data Conversion Intelligence Hub.

Given a question, external search results, and the AI-generated answer, produce a structured knowledge card.

Return ONLY a valid JSON object — no markdown fences, no backticks, no explanation text:

{
  "title":        "Short descriptive title (max 10 words)",
  "module":       "One of: AR, AP, GL, Projects, Inventory, Procurement, ItemMaster, ItemEff, ItemCategories, ItemStructure, ItemRevisions, ItemRelationship, Employees, Payroll, Benefits, All",
  "tab":          "One of: quality, load, lineage",
  "severity":     "One of: Critical, High, Medium, Info",
  "description":  "2-3 sentence explanation of the finding",
  "code_block":   "Key rules or examples using \\n for line breaks, or empty string if not applicable",
  "tip":          "One specific, actionable recommendation",
  "source_url":   "Most relevant URL from search results, or empty string",
  "source_label": "Short label e.g. Oracle Docs, Oracle Blog, or empty string"
}

IMPORTANT: For PDH-related questions (item master, item revisions, item structure, item categories, item effectivity, item relationships), 
use the specific submodule name: ItemMaster, ItemEff, ItemCategories, ItemStructure, ItemRevisions, or ItemRelationship.
"""


def generate_card(question: str, search_context: str, answer: str) -> dict | None:
    try:
        prompt = (
            f"Question: {question}\n\n"
            + (f"Search results:\n{search_context}\n\n" if search_context else "")
            + f"Answer:\n{answer}\n\n"
            f"Generate a knowledge card based on the above."
        )
        resp = client.chat.completions.create(
            model       = LLM_MODEL,
            messages    = [
                {"role": "system", "content": CARD_GEN_SYSTEM},
                {"role": "user",   "content": prompt}
            ],
            max_tokens  = 600,
            temperature = 0.2
        )
        raw  = resp.choices[0].message.content.strip()
        raw  = raw.replace("```json", "").replace("```", "").strip()
        card = json.loads(raw)

        required = ["title", "module", "tab", "severity", "description", "tip"]
        return card if all(k in card for k in required) else None

    except Exception as e:
        print(f"[Card gen error] {e}")
        return None


# ── Chat System Prompt ──────────────────────────────────────

CHAT_SYSTEM = """You are the AI Assistant in the Oracle Data Conversion Intelligence Hub.

You are a Senior Oracle Cloud Solution Architect specializing in data conversion for:
- Oracle Fusion Finance  : AR, AP, GL, Projects
- Oracle Fusion SCM      : Inventory, Procurement
- Oracle Fusion PDH      : Item Master, Item Effectivity, Item Categories, Item Structure (BOM), Item Revisions, Item Relationships
- Oracle Fusion HCM      : Employees, Payroll, Benefits

STRICT RULES:
1. Answer directly — no preamble like "Great question", "Certainly", or "Of course"
2. Use internal knowledge base context if provided — cite card IDs (e.g. PDH-IM-Q1) where relevant
3. Incorporate external search results naturally if provided
4. NEVER mention search steps, tiers, sources, or internal reasoning to the user
5. Format: **bold** for key terms, bullet lists for steps/rules, code blocks for examples
6. Keep responses under 450 words
7. End with 2–3 proactive follow-up considerations the user may not have thought of

TONE: Authoritative, precise, consultative — like a senior Oracle conversion consultant.
"""
