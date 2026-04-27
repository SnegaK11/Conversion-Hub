# ═══════════════════════════════════════════════════════════
#  routes.py — Flask Route Handlers
#
#  POST /api/chat                      — AI assistant (3-tier)
#  GET  /api/knowledge                 — list all KB entries
#  GET  /api/knowledge/<mod>/<sub>/<cat> — filter by path
#  POST /api/knowledge                 — manually add entry
#  DELETE /api/knowledge/<id>          — remove entry
#  GET  /api/stats                     — counts for dashboard
#  GET  /health                        — server status
#  GET  /test-llm                      — verify LLM connection
# ═══════════════════════════════════════════════════════════

import requests as req
from datetime import datetime
from flask import Blueprint, request, jsonify
from openai import AuthenticationError, RateLimitError

from config   import LLM_API_URL, LLM_API_KEY, LLM_MODEL, GOOGLE_API_KEY, DB_PATH
from database import get_db
from search   import search_internal_kb, search_oracle_docs, search_web, format_results
from ai_engine import client, classify, generate_card, CHAT_SYSTEM

bp = Blueprint("routes", __name__)


# ═══════════════════════════════════════════════════════════
#  POST /api/chat — 3-tier AI routing
# ═══════════════════════════════════════════════════════════

@bp.route("/api/chat", methods=["POST"])
def chat():
    data     = request.get_json()
    messages = data.get("messages", [])
    question = messages[-1]["content"] if messages else ""

    if not question:
        return jsonify({"error": "No question provided"}), 400

    db        = get_db()
    tier_used = "tier1"
    new_card  = None
    context   = ""

    # Keywords that signal the user wants specific details
    # beyond what a general rule card would cover.
    # These always go to Tier 2/3 even if KB has some hits.
    DETAIL_KEYWORDS = [
        "column", "columns", "mandatory", "required field", "template",
        "steps", "step by step", "how to", "procedure", "format of",
        "list of", "all the", "complete", "full list", "what are all",
        "which fields", "which columns", "error code", "error message",
        "api", "endpoint", "sql", "query", "script"
    ]
    is_detail_question = any(kw in question.lower() for kw in DETAIL_KEYWORDS)

    # ── Tier 1: Internal SQLite ────────────────────────────
    kb_hits = search_internal_kb(db, question)

    if kb_hits and not is_detail_question:
        # Strong KB match and not a detail question → answer from KB only
        context = "\n\nINTERNAL KNOWLEDGE BASE MATCHES:\n"
        for h in kb_hits:
            context += (
                f"\n[{h['card_id'] or h['id']}] {h['title']}"
                f" ({h['module']}/{h['submodule']}/{h['category']}) — {h['severity']}\n"
                f"  {h['description']}\n"
            )
            if h["code_block"]:
                context += f"  Rules: {h['code_block'][:200]}\n"
        print(f"[TIER1] {len(kb_hits)} hits → {question[:60]}")

    else:
        # Either no KB hits, or user is asking for specific details
        # → go external so new knowledge gets stored and injected
        if is_detail_question and kb_hits:
            print(f"[TIER2/3] Detail question — bypassing KB hits → {question[:60]}")
        else:
            print(f"[TIER2/3] No KB hits → {question[:60]}")
        # ── Tier 2: Oracle Docs ────────────────────────────
        print(f"[TIER2/3] searching externally → {question[:60]}")
        tier_used = "tier2_external"

        oracle_res = search_oracle_docs(question)
        web_res    = search_web(question)
        ext        = format_results(oracle_res, "Oracle Documentation")
        ext       += format_results(web_res,    "Web Search")

        if ext:
            context = "\n\nEXTERNAL SEARCH RESULTS:\n" + ext
        else:
            # ── Tier 3: Built-in expertise only ───────────
            tier_used = "tier3_expertise"
            context   = "\n\n(No external search configured — answering from built-in Oracle Fusion expertise)"

    # ── Call LLM ──────────────────────────────────────────
    system_prompt = CHAT_SYSTEM + context

    try:
        response = client.chat.completions.create(
            model       = LLM_MODEL,
            messages    = [{"role": "system", "content": system_prompt}, *messages],
            max_tokens  = 1024,
            temperature = 0.3
        )
        answer = response.choices[0].message.content

        # ── Self-learning: ONLY for external answers (Tier 2 / Tier 3) ──
        # Tier 1 answers come from the existing KB — nothing new to store.
        # Tier 2/3 answers are genuinely new knowledge — classify, store, inject.
        if tier_used in ("tier2_external", "tier3_expertise") and answer:
            mod, sub, cat = classify(question, answer)

            # Try to generate a rich structured card from the LLM
            search_ctx_for_card = context if "EXTERNAL SEARCH RESULTS" in context else ""
            generated = generate_card(question, search_ctx_for_card, answer)

            now     = datetime.utcnow().isoformat()
            card_id = f"AI-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

            # Resolve module/submodule/category — prefer generated card values
            card_mod = mod
            card_sub = sub
            card_cat = cat
            sev      = "Medium"
            title    = question[:80]
            code_blk = ""
            tip      = ""

            if generated:
                # PDH submodules map directly — PDH is its own module now
                pdh_subs = {"ItemMaster","ItemEff","ItemCategories",
                            "ItemStructure","ItemRevisions","ItemRelationship"}
                fin_mods = {"AR","AP","GL","Projects"}
                scm_mods = {"Inventory","Procurement"}
                hcm_mods = {"Employees","Payroll","Benefits"}

                gen_mod = generated.get("module", "")

                if gen_mod in pdh_subs:
                    # LLM returned a PDH submodule name as "module"
                    card_mod = "PDH"
                    card_sub = gen_mod
                elif gen_mod in fin_mods:
                    card_mod = "Finance"
                    card_sub = gen_mod
                elif gen_mod in scm_mods:
                    card_mod = "SCM"
                    card_sub = gen_mod
                elif gen_mod in hcm_mods:
                    card_mod = "HCM"
                    card_sub = gen_mod
                elif gen_mod == "PDH":
                    # LLM returned "PDH" — use classify() result for submodule
                    card_mod = "PDH"
                    card_sub = sub if sub in pdh_subs else "ItemMaster"
                else:
                    # Fallback to classify() result
                    card_mod = mod
                    card_sub = sub

                card_cat = generated.get("tab", cat)
                sev      = generated.get("severity", "Medium")
                title    = generated.get("title", question[:80])
                code_blk = generated.get("code_block", "")
                tip      = generated.get("tip", "")

            # Store in SQLite so future Tier 1 searches find it
            db.execute("""
                INSERT INTO knowledge
                  (module, submodule, category, severity, title, description,
                   code_block, tip, source, card_id, created_at, query_text)
                VALUES (?,?,?,?,?,?,?,?,'ai_discovered',?,?,?)
            """, (card_mod, card_sub, card_cat, sev, title, answer[:2000],
                  code_blk, tip, card_id, now, question))
            db.commit()
            print(f"[LEARN] Stored: {title[:50]} → {card_mod}/{card_sub}/{card_cat}")

            # Always build new_card so the frontend can inject it into the correct tab
            # Even if generate_card() failed, we still have enough info to inject
            new_card = {
                "title":       title,
                "description": answer[:500],   # first 500 chars as the card description
                "severity":    sev,
                "tab":         card_cat,        # quality | load | lineage
                "module":      card_mod,        # Finance | SCM | HCM
                "submodule":   card_sub,        # AR | AP | GL | etc.
                "code_block":  code_blk,
                "tip":         tip,
                "card_id":     card_id,
                "source_url":  generated.get("source_url","") if generated else "",
            }

        # ── Log query ──────────────────────────────────────
        db.execute(
            "INSERT INTO query_log (query, tier_used, answered, created_at) VALUES (?,?,1,?)",
            (question, tier_used, datetime.utcnow().isoformat())
        )
        db.commit()

        return jsonify({
            "content":  [{"type": "text", "text": answer}],
            "new_card": new_card,
            "model":    response.model
        })

    except AuthenticationError:
        return jsonify({"error": "Authentication failed — check LLM_API_KEY in config.py"}), 401
    except RateLimitError:
        return jsonify({"error": "Rate limit reached — please wait and try again"}), 429
    except Exception as e:
        print(f"[LLM error] {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════
#  GET /api/knowledge — list / filter entries
# ═══════════════════════════════════════════════════════════

@bp.route("/api/knowledge", methods=["GET"])
def get_knowledge():
    """
    Query params (all optional):
      module, submodule, category, source, limit (default 100)
    """
    db     = get_db()
    mod    = request.args.get("module")
    sub    = request.args.get("submodule")
    cat    = request.args.get("category")
    source = request.args.get("source")
    limit  = int(request.args.get("limit", 100))

    sql    = "SELECT * FROM knowledge WHERE 1=1"
    params = []
    if mod:    sql += " AND module=?";    params.append(mod)
    if sub:    sql += " AND submodule=?"; params.append(sub)
    if cat:    sql += " AND category=?";  params.append(cat)
    if source: sql += " AND source=?";    params.append(source)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ── GET /api/knowledge/<mod>/<sub>/<cat> ───────────────────

@bp.route("/api/knowledge/<mod>/<sub>/<cat>", methods=["GET"])
def get_knowledge_by_path(mod, sub, cat):
    """Fetch entries for a specific module / submodule / category path."""
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM knowledge WHERE module=? AND submodule=? AND category=? ORDER BY created_at DESC",
        (mod, sub, cat)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── POST /api/knowledge — manually add entry ───────────────

@bp.route("/api/knowledge", methods=["POST"])
def add_knowledge():
    """
    Required body fields: module, submodule, category, title, description
    Optional: severity, code_block, tip, source_url
    """
    data     = request.get_json()
    required = ["module", "submodule", "category", "title", "description"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required fields: {required}"}), 400

    db      = get_db()
    now     = datetime.utcnow().isoformat()
    card_id = f"MAN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    cur = db.execute("""
        INSERT INTO knowledge
          (module, submodule, category, severity, title, description,
           code_block, tip, source, source_url, card_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,'manual',?,?,?)
    """, (
        data["module"], data["submodule"], data["category"],
        data.get("severity", "Medium"),
        data["title"],
        data["description"],
        data.get("code_block", ""),
        data.get("tip", ""),
        data.get("source_url", ""),
        card_id, now
    ))
    db.commit()
    return jsonify({"id": cur.lastrowid, "card_id": card_id, "status": "created"}), 201


# ── DELETE /api/knowledge/<id> ─────────────────────────────

@bp.route("/api/knowledge/<int:entry_id>", methods=["DELETE"])
def delete_knowledge(entry_id):
    db = get_db()
    db.execute("DELETE FROM knowledge WHERE id=?", (entry_id,))
    db.commit()
    return jsonify({"status": "deleted", "id": entry_id})


# ═══════════════════════════════════════════════════════════
#  GET /api/stats — dashboard counts
# ═══════════════════════════════════════════════════════════

@bp.route("/api/stats", methods=["GET"])
def get_stats():
    db       = get_db()
    total    = db.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
    ai_disc  = db.execute("SELECT COUNT(*) as c FROM knowledge WHERE source='ai_discovered'").fetchone()["c"]
    queries  = db.execute("SELECT COUNT(*) as c FROM query_log").fetchone()["c"]
    modules  = db.execute("SELECT COUNT(DISTINCT module) as c FROM knowledge").fetchone()["c"]
    return jsonify({
        "total_rules":     total,
        "ai_discovered":   ai_disc,
        "total_queries":   queries,
        "modules_covered": modules
    })


# ═══════════════════════════════════════════════════════════
#  GET /health
# ═══════════════════════════════════════════════════════════

@bp.route("/health", methods=["GET"])
def health():
    db       = get_db()
    kb_count = db.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
    ai_count = db.execute("SELECT COUNT(*) as c FROM knowledge WHERE source='ai_discovered'").fetchone()["c"]
    key_set  = LLM_API_KEY not in ("your-llm-api-key", "YOUR_LLM_API_KEY_HERE", "")
    return jsonify({
        "status":        "ok",
        "llm_url":       LLM_API_URL,
        "llm_model":     LLM_MODEL,
        "llm_key":       "✅ set"    if key_set else "❌ NOT SET — edit config.py",
        "google_search": "✅ set"    if GOOGLE_API_KEY != "YOUR_GOOGLE_API_KEY_HERE" else "⚠️  not set — Tier 2/3 disabled",
        "db_path":       DB_PATH,
        "kb_entries":    kb_count,
        "ai_discovered": ai_count,
        "test_llm":      "http://localhost:3000/test-llm"
    })


# ═══════════════════════════════════════════════════════════
#  GET /test-llm — verify LLM connection
# ═══════════════════════════════════════════════════════════

@bp.route("/test-llm", methods=["GET"])
def test_llm():
    results = {}

    # Step 1: ping /v1/models
    try:
        url  = LLM_API_URL.rstrip("/") + "/v1/models"
        resp = req.get(url, headers={"Authorization": f"Bearer {LLM_API_KEY}"}, timeout=10)
        results["models_endpoint"] = {"url": url, "status": resp.status_code}
    except Exception as e:
        results["models_endpoint"] = {"error": str(e)}

    # Step 2: quick chat test
    try:
        r = client.chat.completions.create(
            model    = LLM_MODEL,
            messages = [{"role": "user", "content": "Reply with exactly: LLM connection OK"}],
            max_tokens = 20
        )
        results["chat_test"] = {
            "status": "✅ SUCCESS",
            "reply":  r.choices[0].message.content,
            "tokens": r.usage.total_tokens
        }
    except AuthenticationError as e:
        results["chat_test"] = {"status": "❌ Auth failed", "error": str(e)}
    except Exception as e:
        results["chat_test"] = {"status": "❌ Failed", "error": str(e)}

    return jsonify({
        "config":  {"LLM_API_URL": LLM_API_URL, "LLM_MODEL": LLM_MODEL},
        "results": results
    })
