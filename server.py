# ═══════════════════════════════════════════════════════════
#  server.py — Entry Point
#
#  Run:   python server.py
#  Open:  http://localhost:3000
#
#  Folder structure:
#    oracle_hub/
#    ├── server.py        ← entry point  (this file)
#    ├── config.py        ← LLM keys, DB path, port
#    ├── database.py      ← SQLite init, seed data, get_db()
#    ├── search.py        ← Tier 1 / 2 / 3 search functions
#    ├── ai_engine.py     ← LLM client, classify, card gen
#    ├── routes.py        ← all Flask route handlers
#    ├── requirements.txt
#    ├── oracle_hub.db    ← auto-created on first run
#    └── public/
#        └── index.html
# ═══════════════════════════════════════════════════════════

from flask import Flask, send_from_directory
from flask_cors import CORS

from config   import PORT, DEBUG, LLM_API_URL, LLM_MODEL, LLM_API_KEY, GOOGLE_API_KEY, DB_PATH
from database import init_db, close_db
from routes   import bp

# ── App ─────────────────────────────────────────────────────
app = Flask(__name__, static_folder="public")
CORS(app)

app.register_blueprint(bp)      # all /api/* routes
app.teardown_appcontext(close_db)


# ── Static files ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("public", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("public", path)


# ── Run ──────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()

    key_set    = LLM_API_KEY    not in ("your-llm-api-key", "YOUR_LLM_API_KEY_HERE", "")
    google_set = GOOGLE_API_KEY != "YOUR_GOOGLE_API_KEY_HERE"

    print("═" * 60)
    print("  Oracle Conversion Hub — AI Backend")
    print("═" * 60)
    print(f"  LLM URL    : {LLM_API_URL}")
    print(f"  LLM Model  : {LLM_MODEL}")
    print(f"  LLM Key    : {'✅ Set' if key_set else '❌ NOT SET — edit config.py'}")
    print(f"  Google     : {'✅ Set' if google_set else '⚠️  Not set — Tier 2/3 disabled'}")
    print(f"  Database   : {DB_PATH}")
    print(f"  App        : http://localhost:{PORT}")
    print(f"  Health     : http://localhost:{PORT}/health")
    print(f"  KB API     : http://localhost:{PORT}/api/knowledge")
    print(f"  Stats      : http://localhost:{PORT}/api/stats")
    print(f"  Test LLM   : http://localhost:{PORT}/test-llm")
    print("═" * 60)

    app.run(port=PORT, debug=DEBUG)
