# ═══════════════════════════════════════════════════════════
#  database.py — SQLite Knowledge Base
#  Handles: DB init, schema creation, seeding, get/close
# ═══════════════════════════════════════════════════════════

import sqlite3
from datetime import datetime
from flask import g
from config import DB_PATH


# ── Thread-local DB connection ──────────────────────────────

def get_db():
    """Return the thread-local SQLite connection (creates if needed)."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    """Close DB connection at end of request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ── Schema ──────────────────────────────────────────────────

def init_db():
    """Create tables and seed built-in knowledge on first run."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            module       TEXT NOT NULL,           -- Finance | SCM | HCM | All
            submodule    TEXT NOT NULL,           -- AR | AP | GL | Projects | Inventory | etc.
            category     TEXT NOT NULL,           -- quality | load | lineage
            severity     TEXT DEFAULT 'Medium',   -- Critical | High | Medium | Info
            title        TEXT NOT NULL,
            description  TEXT NOT NULL,
            code_block   TEXT DEFAULT '',
            tip          TEXT DEFAULT '',
            source       TEXT DEFAULT 'internal', -- internal | ai_discovered | manual
            source_url   TEXT DEFAULT '',
            source_label TEXT DEFAULT '',
            card_id      TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            query_text   TEXT DEFAULT ''          -- original query that generated this entry
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            query      TEXT NOT NULL,
            tier_used  TEXT NOT NULL,   -- tier1 | tier2_external | tier3_expertise
            answered   INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()

    # Seed only if table is empty
    cur.execute("SELECT COUNT(*) as cnt FROM knowledge")
    if cur.fetchone()["cnt"] == 0:
        _seed(conn)

    conn.close()
    print(f"[DB] SQLite ready: {DB_PATH}")


# ── Seed data ───────────────────────────────────────────────

SEED_DATA = [
    # ── Finance / AR ──────────────────────────────────────────────────────────
    ("Finance","AR","quality","Critical",
     "Date Format Standardisation — FBDI",
     "All FBDI date fields must use DD-MON-YYYY format. Incorrect formats cause silent rejections during import.",
     "Expected: DD-MON-YYYY → e.g., 15-JAN-2024\nReject:   2024-01-15 / 15/01/2024 / Jan-15-24",
     "Cleanse at source: TO_CHAR(date_col, 'DD-MON-YYYY'). Validate all date columns in staging.",
     "QC-AR-001"),

    ("Finance","AR","quality","Critical",
     "Special Characters in Customer Name Fields",
     "Oracle rejects name/address fields with unsupported special characters. Common in international ERP migrations.",
     "Reject: O'Brien & Sons / Müller GmbH / Léa Corp\nReplace: OBrien and Sons / Mueller GmbH / Lea Corp",
     "Run regex scan — allow only A–Z, 0–9, comma, period, hyphen, space. Agree cleansing matrix before migration.",
     "QC-AR-002"),

    ("Finance","AR","quality","High",
     "Customer Account & Site Completeness",
     "Every AR customer must have at least one active Bill-To site. Customers without sites load but cannot be invoiced.",
     "Validate: COUNT(sites) WHERE customer_id = X >= 1\nVerify:   primary_bill_to_flag = 'Y' per customer",
     "Flag customers with zero sites — may be dormant accounts to exclude rather than migrate.",
     "QC-AR-003"),

    ("Finance","AR","load","Critical",
     "Batch Volume Management — Avoiding Timeout",
     "Oracle Cloud FBDI import is subject to timeout thresholds. Large single batches frequently time out.",
     "Recommended:  500–2,000 rows per FBDI file\nAR Invoices:  Max 1,000 per batch\nAP Invoices:  Max 500 per batch",
     "Schedule loads during off-peak hours. Maintain a load tracker for every batch run.",
     "LC-ALL-001"),

    ("Finance","AR","load","Critical",
     "Mandatory Load Sequencing — Parent Before Child",
     "Oracle enforces strict referential integrity. Load transactional data only after master data is complete.",
     "Sequence:\n1. Legal Entities & Business Units\n2. Chart of Accounts / Ledger\n3. Customer / Supplier Master\n4. Sites / Banks\n5. Open Balances / Transactions",
     "Get formal sign-off on load sequence from Solution Architect and Finance Lead before any production loads.",
     "LC-FIN-001"),

    ("Finance","AR","lineage","Critical",
     "AR Customer Sites → Project Contract Conversion",
     "Project contracts require a valid AR customer account and Bill-To site. Incomplete AR site conversion blocks project contracts.",
     "Impact:  Missing AR site → Contract load failure\nError:   'Bill-to customer site does not exist'\nResult:  Projects team blocked until AR remediation complete",
     "AR and Projects workstreams must agree a shared data readiness date. AR fully validated before Projects begins.",
     "LIN-AR-PRJ-001"),

    # ── Finance / AP ──────────────────────────────────────────────────────────
    ("Finance","AP","quality","Critical",
     "Supplier Tax Registration Numbers",
     "Tax registration fields must be validated for format and uniqueness. Duplicate or malformed TRNs cause supplier creation failures.",
     "IN (GSTIN): 15 alphanumeric characters\nUK (VAT):   GB + 9 digits\nCheck:      No duplicate TRNs across supplier records",
     "Work with Tax and Finance teams to obtain a validated list of active TRNs.",
     "QC-AP-001"),

    ("Finance","AP","quality","High",
     "Bank Account & Payment Method Validation",
     "Supplier bank account details require strict validation. Invalid IBANs prevent payment processing.",
     "IBAN:      Must pass MOD-97 checksum validation\nSort Code: NN-NN-NN (UK)\nRouting:   9-digit ABA number (US)",
     "Use third-party bank validation APIs during cleansing. Escalate unvalidated accounts to Finance.",
     "QC-AP-002"),

    ("Finance","AP","load","High",
     "Prepayment & Invoice Status Management",
     "AP invoices with prepayment applications require careful strategy. Loading net-settled invoices without prepayments inflates payables.",
     "Strategy A: Load gross invoice + prepayment + application\nStrategy B: Load net balance only\nDecision:   Must be agreed with Finance Controller pre go-live",
     "Model both approaches in sandbox with Oracle Payables consultant before committing.",
     "LC-AP-001"),

    ("Finance","AP","lineage","High",
     "GL COA Setup → AP Invoice Distribution Lines",
     "Every AP invoice distribution line requires a valid GL account code combination. Incomplete COA causes silent distribution failures.",
     "Failure: Invoice loads (header level) ✓\nBUT:     Distribution line creation fails silently ✗\nResult:  Invoice NOT reflected in GL trial balance",
     "Run GL distribution reconciliation report after every AP batch. AP distributions MUST equal AP invoice amounts.",
     "LIN-AP-GL-001"),

    # ── Finance / GL ──────────────────────────────────────────────────────────
    ("Finance","GL","quality","Critical",
     "Chart of Accounts Segment Mapping",
     "Every GL account segment value must map to a valid Oracle Cloud COA value. Unmapped segments cause journal import failures.",
     "Validate: (Company.Dept.Account.Product) in FND_FLEX_VALUES\nReject:   Null segments, deactivated values, invalid combos",
     "Generate crosswalk between legacy GL codes and Oracle COA. Finance Controller sign-off mandatory.",
     "QC-GL-001"),

    ("Finance","GL","load","High",
     "Opening Balance Reconciliation Before Load",
     "GL opening balances must be reconciled to a signed-off trial balance before upload. Unreconciled balances create statutory divergence.",
     "Pre-load: TB agreed = TB in file (to 2 decimal places)\nValidate: Debit total = Credit total\nConfirm:  FX balances align with agreed rates",
     "No GL balance loads proceed without a dated, countersigned reconciliation from Finance team.",
     "LC-GL-001"),

    ("Finance","GL","lineage","High",
     "Project Cost Transactions → GL Period-End Reporting",
     "Project costs not fully loaded by cut-off create a GL trial balance that understates costs.",
     "Validate: SUM(Project cost txns) = SUM(GL project cost balances)\nRun:      Cross-ledger reconciliation pre and post load\nTarget:   Zero variance",
     "Schedule cross-module reconciliation checkpoint between Projects and GL teams at end of each rehearsal.",
     "LIN-GL-PRJ-001"),

    # ── Finance / Projects ────────────────────────────────────────────────────
    ("Finance","Projects","quality","High",
     "Project Start / End Date Logic Validation",
     "Project records must pass date logic checks. Tasks with dates outside parent project window cause billing errors.",
     "Rule 1: project_end_date > project_start_date\nRule 2: task_start_date >= project_start_date\nRule 3: task_end_date <= project_completion_date",
     "Build date hierarchy validation script across all project-task-resource combinations.",
     "QC-PRJ-001"),

    ("Finance","Projects","load","High",
     "Project Transaction Load Order — Cost Before Revenue",
     "Costs must be loaded before revenue recognition records. Loading revenue without costs creates irreconcilable positions.",
     "Projects Load Order:\n1. Templates & Types\n2. Project Master (Headers)\n3. Tasks & WBS\n4. Resources\n5. Actual Costs\n6. Revenue / Billing Events",
     "Separate T&M and fixed-price projects into distinct load batches.",
     "LC-PRJ-001"),

    ("Finance","Projects","lineage","Critical",
     "Project Contracts → Revenue Recognition Schedules",
     "Revenue recognition schedules are derived directly from contract data. Incomplete conversion produces erroneous revenue schedules.",
     "Chain: AR Site → Contract Header → Contract Line\n     → Performance Obligation → Revenue Schedule",
     "Validate post-load revenue schedules in UAT for at least 10% of converted contracts.",
     "LIN-AR-PRJ-002"),

    # ── SCM / Inventory ───────────────────────────────────────────────────────
    ("SCM","Inventory","quality","Critical",
     "Item Number Format Validation",
     "Item numbers must follow the company segment structure defined in PDH. Special characters are not permitted.",
     "Max 40 characters\nNo mixed case or special characters\nMust match PDH segment structure",
     "Validate item numbers against PDH master list before extraction.",
     "SCM-INV-Q1"),

    ("SCM","Inventory","quality","High",
     "UOM Code Standardisation",
     "Unit of Measure values must reference valid Oracle UOM codes. Free-text UOM values cause receiving failures.",
     "Legacy: 'pcs' / 'ea' / 'nos' / 'Kg'\nOracle: 'Each' / 'Kilogram' / 'Dozen'\nAction: Build complete legacy-to-Oracle UOM mapping matrix",
     "Extract Oracle UOM lookup table from target environment. Engage Procurement for any UOM without a clear equivalent.",
     "QC-P2P-001"),

    ("SCM","Inventory","load","Critical",
     "PDH Item Master Required Before Inventory Load",
     "All items must be defined and approved in PDH before loading inventory transactions or on-hand balances.",
     "Sequence: PDH Item Master → Inventory Orgs → On-Hand Balances → Transactions",
     "PDH is foundational for all SCM modules. Never load inventory without PDH being fully validated.",
     "SCM-INV-L1"),

    ("SCM","Inventory","lineage","Critical",
     "PDH → All SCM Module Dependency",
     "PDH is the single source of truth for item master data. All downstream SCM modules have a hard dependency on PDH.",
     "Impact: Missing PDH items → Inventory, Procurement, and Order Management all blocked\nRisk:   No partial loads possible",
     "Load PDH fully and validate before beginning any other SCM module migration.",
     "SCM-PDH-L1"),

    # ── SCM / Procurement ─────────────────────────────────────────────────────
    ("SCM","Procurement","quality","Critical",
     "PO Line Amount = Quantity × Unit Price",
     "PO line amounts must equal QUANTITY × UNIT_PRICE exactly. Rounding enforced to 2 decimal places.",
     "Validate: AMOUNT = QUANTITY * UNIT_PRICE (to 2 d.p.)\nReject:   Any variance, even rounding differences",
     "Build a pre-validation script to flag PO lines with amount mismatches before FBDI generation.",
     "SCM-PR-Q2"),

    ("SCM","Procurement","load","Critical",
     "Approved Supplier List Before PO Load",
     "Suppliers must appear in the Approved Supplier List for controlled items before Purchase Orders can be created.",
     "Pre-load ASL data before PO migration\nValidate: supplier_id IN (SELECT supplier_id FROM asl WHERE status='APPROVED')",
     "Extract project-referenced suppliers and validate their ASL status first.",
     "SCM-PR-L1"),

    # ── HCM / Employees ───────────────────────────────────────────────────────
    ("HCM","Employees","quality","Critical",
     "National ID Format Validation",
     "National Identifier must match country-specific format. Invalid IDs cause record rejection.",
     "Indian PAN:  AAAAA9999A (10 chars)\nAadhaar:     12 digits\nUS SSN:      9 digits (no dashes in FBDI)",
     "Build country-specific regex validation for all National ID fields before extraction.",
     "HCM-EMP-Q1"),

    ("HCM","Employees","load","Critical",
     "Org Hierarchy Must Exist Before Employee Load",
     "Business Units, Legal Entities, Departments, and Locations must all be configured before loading employee records.",
     "Sequence:\n1. Legal Entities\n2. Business Units\n3. Departments\n4. Locations\n5. Jobs & Grades\n6. Employee Records",
     "Most critical HCM sequencing dependency. No employee loads without complete org hierarchy.",
     "HCM-EMP-L1"),

    ("HCM","Employees","lineage","Critical",
     "Org Hierarchy → All HCM Module Dependency",
     "Missing org hierarchy is a hard blocker — prevents all employee record loading and cascades to payroll and benefits.",
     "Impact: Missing org → Employee records blocked\n        Employee records → Payroll blocked\n        Payroll → Benefits blocked",
     "Build and validate org hierarchy in a dedicated sprint before any other HCM conversion work.",
     "HCM-EMP-L1-LIN"),

    # ── HCM / Payroll ─────────────────────────────────────────────────────────
    ("HCM","Payroll","quality","Critical",
     "Employee Bank Account Validation",
     "Bank account number and IFSC/routing code must be validated before payroll processing. Invalid accounts block EFT payments.",
     "IFSC Code: 11 characters (India)\nRouting:   9-digit ABA (US)\nValidate:  Bank master reference check",
     "Use third-party bank validation APIs during cleansing phase.",
     "HCM-PAY-Q1"),

    ("HCM","Payroll","load","Critical",
     "Employee Assignments Required Before Payroll Load",
     "Valid employee assignments must exist before any payroll elements can be loaded.",
     "Sequence: Employee Records → Assignments → Payroll Elements → Bank Accounts",
     "Missing assignments is the #1 payroll conversion blocker. Validate assignment completeness before payroll load.",
     "HCM-PAY-L1"),

    # ── HCM / Benefits ────────────────────────────────────────────────────────
    ("HCM","Benefits","quality","High",
     "Enrollment Date Within Plan Year",
     "Benefits enrollment dates must fall within the plan year and open enrollment window.",
     "Validate: effective_start_date BETWEEN plan_start AND plan_end\nBackdated enrollments require HR director approval",
     "Build date range validation against Oracle Benefits plan configuration before enrollment load.",
     "HCM-BEN-Q1"),

    ("HCM","Benefits","load","Critical",
     "Benefits Plan Design Must Be Published First",
     "Plans, options, coverage structures, and cost tiers must be fully published before enrollment data can be loaded.",
     "Pre-requisite: Plan Design → Published\nThen: Demographics → Enrollment → Life Events → Payroll Deductions",
     "Benefits plan design is the foundational dependency for all enrollment loading.",
     "HCM-BEN-L1"),

    # ── All modules ───────────────────────────────────────────────────────────
    ("All","All","load","Medium",
     "Error Log Monitoring & Rejection Analysis",
     "Every FBDI import generates an error log. Teams that skip log review compound errors across batches.",
     "After each batch:\n1. Download import output report\n2. Count: Submitted vs Imported vs Rejected\n3. Categorise every rejection by error code\n4. Remediate before re-submitting",
     "Appoint a dedicated Load Monitor during migration weekend with direct escalation rights.",
     "LC-ALL-002"),
]


def _seed(conn):
    """Insert built-in knowledge rows."""
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    for row in SEED_DATA:
        mod, sub, cat, sev, title, desc, code, tip, card_id = row
        cur.execute("""
            INSERT INTO knowledge
              (module, submodule, category, severity, title, description,
               code_block, tip, source, card_id, created_at)
            VALUES (?,?,?,?,?,?,?,?,'internal',?,?)
        """, (mod, sub, cat, sev, title, desc, code, tip, card_id, now))
    conn.commit()
    print(f"[DB] Seeded {len(SEED_DATA)} built-in knowledge entries")
