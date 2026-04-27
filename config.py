# ═══════════════════════════════════════════════════════════
#  config.py — Oracle Conversion Hub Configuration
# ═══════════════════════════════════════════════════════════

# ── LLM (PwC Internal Gateway — OpenAI-compatible) ─────────
LLM_API_URL = "https://genai-sharedservice-americas.pwcinternal.com"
LLM_API_KEY = "sk-Bix99DXfd7V5H8T5WMvT7Q"   # ← replace with your key
LLM_MODEL   = "azure.gpt-4o-mini"

# ── Google Custom Search (optional) ────────────────────────
# Enables Tier 2 (Oracle Docs) and Tier 3 (Web) search
# Get API key : console.developers.google.com → Enable "Custom Search API"
# Get CX ID   : programmablesearchengine.google.com → New engine
GOOGLE_API_KEY = "AIzaSyDQ_XMyNwzPy0-nhVXMcg592m-A7EqqTcU"
GOOGLE_CX      = "1203edf038cbd4bc8"

# ── Database ────────────────────────────────────────────────
DB_PATH = "oracle_hub.db"

# ── Server ──────────────────────────────────────────────────
PORT  = 3000
DEBUG = True
