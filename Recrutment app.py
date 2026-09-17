from __future__ import annotations

import io
import hashlib
import hmac
import os
import re
import sqlite3
from pathlib import Path
from secrets import token_hex
from urllib.parse import urlparse
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
import streamlit as st

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

st.set_page_config(
    page_title="EGY-CRETE | Recruitment Analysis",
    page_icon="EC",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "egy_crete.db"
AUTH_PATH = APP_DIR / ".streamlit" / "auth.toml"


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialise_database() -> None:
    with db_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate TEXT NOT NULL,
                role TEXT NOT NULL,
                score REAL DEFAULT 0,
                cv_score REAL DEFAULT 0,
                years_experience REAL DEFAULT 0,
                assessment REAL DEFAULT 0,
                interview REAL DEFAULT 0,
                references_score REAL DEFAULT 0,
                salary_low INTEGER,
                salary_high INTEGER,
                recommendation TEXT,
                source TEXT,
                status TEXT,
                profile_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate TEXT NOT NULL,
                review_date TEXT NOT NULL,
                supervisor_rating REAL,
                retained TEXT,
                primary_outcome REAL,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def candidate_records() -> list[dict[str, Any]]:
    with db_connection() as connection:
        records = []
        for row in connection.execute("SELECT * FROM candidates ORDER BY score DESC, id DESC"):
            item = dict(row)
            item.update({"Candidate": item["candidate"], "Role": item["role"], "Score": item["score"], "CV score": item["cv_score"], "Years experience": item["years_experience"], "Assessment": item["assessment"], "Interview": item["interview"], "References": item["references_score"], "Salary low": item["salary_low"], "Salary high": item["salary_high"], "Recommendation": item["recommendation"], "Source": item["source"], "Status": item["status"], "Profile URL": item["profile_url"], "Created at": item["created_at"], "Updated at": item["updated_at"]})
            records.append(item)
        return records


def outcome_records() -> list[dict[str, Any]]:
    with db_connection() as connection:
        return [{"Candidate": row["candidate"], "Review date": row["review_date"], "Supervisor rating": row["supervisor_rating"], "Retained": row["retained"], "Primary outcome": row["primary_outcome"], "Notes": row["notes"], "Created at": row["created_at"]} for row in connection.execute("SELECT * FROM outcomes ORDER BY review_date DESC, id DESC")]


def save_candidate(candidate: dict[str, Any]) -> None:
    timestamp = now_iso()
    with db_connection() as connection:
        connection.execute(
            """INSERT INTO candidates
            (candidate, role, score, cv_score, years_experience, assessment, interview, references_score,
             salary_low, salary_high, recommendation, source, status, profile_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate.get("Candidate", ""), candidate.get("Role", ""), candidate.get("Score", 0), candidate.get("CV score", 0), candidate.get("Years experience", 0), candidate.get("Assessment", 0), candidate.get("Interview", 0), candidate.get("References", 0), candidate.get("Salary low"), candidate.get("Salary high"), candidate.get("Recommendation", ""), candidate.get("Source", ""), candidate.get("Status", ""), candidate.get("Profile URL", ""), timestamp, timestamp),
        )


def save_outcome(outcome: dict[str, Any]) -> None:
    with db_connection() as connection:
        connection.execute(
            "INSERT INTO outcomes (candidate, review_date, supervisor_rating, retained, primary_outcome, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (outcome["Candidate"], outcome["Review date"], outcome["Supervisor rating"], outcome["Retained"], outcome["Primary outcome"], outcome["Notes"], now_iso()),
        )


def password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def auth_config() -> dict[str, str]:
    if not AUTH_PATH.exists():
        AUTH_PATH.parent.mkdir(exist_ok=True)
        salt = token_hex(16)
        default_password = os.environ.get("EGY_CRETE_ADMIN_PASSWORD", "change-me-now")
        AUTH_PATH.write_text(f"username = \"admin\"\nsalt = \"{salt}\"\npassword_hash = \"{password_hash(default_password, salt)}\"\n", encoding="utf-8")
    values: dict[str, str] = {}
    for line in AUTH_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def login_gate() -> bool:
    if st.session_state.get("authenticated"):
        return True
    config = auth_config()
    st.markdown("<div class='hero'><div class='eyebrow'>EGY-CRETE secure workspace</div><h1>Sign in to Recruitment Analysis</h1><p>Candidate and hiring data is stored locally for your team.</p></div>", unsafe_allow_html=True)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and hmac.compare_digest(username, config.get("username", "")) and hmac.compare_digest(password_hash(password, config.get("salt", "")), config.get("password_hash", "")):
        st.session_state.authenticated = True
        st.rerun()
    elif submitted:
        st.error("Invalid username or password.")
    st.caption("First-run default: username `admin`, password `change-me-now`. Change the generated .streamlit/auth.toml before sharing the app.")
    return False

BASE_ROLES: dict[str, dict[str, Any]] = {
    "Production / Plant Technician": {
        "short": "Plant technician",
        "description": "Find dependable operators who can protect uptime, quality, and safety on the factory floor.",
        "criteria": [
            ("Mechanical aptitude", "Can diagnose equipment and reason through mechanical problems.", 25),
            ("Downtime reduction track record", "Evidence of reducing stoppages, waste, or changeover time.", 20),
            ("Reliability & attendance", "Consistent attendance, ownership, and follow-through.", 20),
            ("Safety mindset", "Recognizes hazards and follows safe operating practices.", 15),
            ("Quality & attention to detail", "Catches defects and protects ASTM/BS quality standards.", 10),
            ("Teamwork & communication", "Works effectively across shifts, maintenance, and quality.", 10),
        ],
        "outcomes": ["Supervisor rating (1-5)", "Attendance %", "Downtime owned (hours)", "Retained at 90 days"],
    },
    "Sales & Project Engineer": {
        "short": "Sales engineer",
        "description": "Find commercially-minded engineers who can translate technical value into profitable projects.",
        "criteria": [
            ("Deal track record", "Measurable deals won with contractors, developers, or project owners.", 25),
            ("Technical specification fluency", "Can read and influence architectural and paving specifications.", 20),
            ("Construction network", "Relevant relationships with contractors, consultants, and developers.", 15),
            ("Negotiation", "Protects margin while moving complex deals to close.", 15),
            ("Communication", "Makes technical value clear to different stakeholders.", 15),
            ("Follow-through & CRM discipline", "Keeps commitments, next steps, and pipeline data current.", 10),
        ],
        "outcomes": ["Supervisor rating (1-5)", "Deals closed", "Gross margin %", "Retained at 90 days"],
    },
}

ROLE_FAMILIES = {
    "Production": ["Production Supervisor", "Production Planner", "Plant Manager", "Shift Supervisor", "Production Coordinator", "Process Improvement Engineer", "Industrial Engineer", "Lean Manufacturing Specialist"],
    "Maintenance": ["Maintenance Engineer", "Maintenance Supervisor", "Mechanical Maintenance Technician", "Electrical Maintenance Technician", "Automation Engineer", "Instrumentation Technician", "Reliability Engineer", "Utilities Engineer"],
    "Quality": ["Quality Control Inspector", "Quality Assurance Engineer", "Quality Manager", "Laboratory Technician", "Materials Testing Engineer", "Continuous Improvement Specialist"],
    "Engineering": ["Mechanical Engineer", "Civil Engineer", "Project Engineer", "Design Engineer", "Technical Office Engineer", "Site Engineer", "R&D Engineer", "Technical Support Engineer"],
    "Commercial": ["Sales Engineer", "Project Sales Manager", "Key Account Manager", "Business Development Executive", "Export Sales Specialist", "Estimation Engineer", "Contracts Engineer", "Sales Operations Coordinator"],
    "Supply Chain": ["Procurement Specialist", "Strategic Sourcing Manager", "Warehouse Supervisor", "Inventory Controller", "Logistics Coordinator", "Fleet Supervisor", "Demand Planner", "Supply Chain Manager"],
    "Corporate": ["HR Specialist", "Recruitment Specialist", "Finance Accountant", "Cost Accountant", "Financial Controller", "IT Support Specialist", "Data Analyst", "Health & Safety Officer"],
}

FAMILY_KEYWORDS = {
    "Production": ["production", "manufacturing", "OEE", "downtime", "shift", "output", "lean", "5S"],
    "Maintenance": ["maintenance", "preventive", "predictive", "PLC", "troubleshooting", "MTTR", "CMMS", "electrical"],
    "Quality": ["quality", "inspection", "ISO 9001", "ASTM", "BS", "root cause", "nonconformance", "audit"],
    "Engineering": ["engineering", "AutoCAD", "technical drawings", "concrete", "construction", "specification", "project", "BIM"],
    "Commercial": ["sales", "business development", "contractors", "developers", "pipeline", "negotiation", "tender", "CRM"],
    "Supply Chain": ["procurement", "inventory", "warehouse", "logistics", "sourcing", "ERP", "fleet", "forecasting"],
    "Corporate": ["Excel", "reporting", "compliance", "stakeholder", "analysis", "policy", "KPI", "documentation"],
}

STAGES = ["CV screening", "Technical assessment", "Structured interview", "Reference check"]
STAGE_WEIGHTS = {"CV screening": 20, "Technical assessment": 30, "Structured interview": 30, "Reference check": 20}


def build_role_catalog() -> dict[str, dict[str, Any]]:
    roles = dict(BASE_ROLES)
    for family, titles in ROLE_FAMILIES.items():
        for title in titles:
            role_name = title if title not in roles else f"{title} (EGY-CRETE)"
            keywords = FAMILY_KEYWORDS[family] + [title.lower(), family.lower()]
            roles[role_name] = {
                "short": title,
                "family": family,
                "description": f"Evaluate {title.lower()} candidates against evidence that matters to EGY-CRETE's {family.lower()} work.",
                "keywords": keywords,
                "criteria": [(keyword.title(), f"Evidence of {keyword.lower()} capability.", max(5, 20 - index * 2)) for index, keyword in enumerate(keywords[:6])],
                "outcomes": ["Supervisor rating (1-5)", "Retained at 90 days", "Role-specific KPI"],
            }
    return roles


ROLES = build_role_catalog()

SAMPLE_CANDIDATES = [
    {"Candidate": "Mariam Hassan", "Role": "Production / Plant Technician", "Score": 4.35, "Recommendation": "Strong hire", "Source": "Employee referral", "Status": "Shortlisted"},
    {"Candidate": "Karim Adel", "Role": "Production / Plant Technician", "Score": 3.62, "Recommendation": "Consider", "Source": "Technical institute", "Status": "Interview"},
    {"Candidate": "Nour El Din", "Role": "Sales & Project Engineer", "Score": 4.12, "Recommendation": "Strong hire", "Source": "LinkedIn", "Status": "Final review"},
]


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        :root { --ink:#16212b; --navy:#183a59; --teal:#0b8276; --mint:#e5f4ef; --sand:#f5f1e8; --line:#d7e0df; --muted:#607079; }
        html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; color: var(--ink); }
        h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: 0 !important; }
        h1 { font-size: 2.35rem !important; line-height: 1.05 !important; }
        h2 { font-size: 1.45rem !important; }
        .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }
        [data-testid="stSidebar"] { background: #102c43; }
        [data-testid="stSidebar"] * { color: #eef7f5 !important; }
        [data-testid="stSidebar"] .stRadio label { background: rgba(255,255,255,.07); padding: .65rem .75rem; border-radius: 6px; margin-bottom: .35rem; }
        .eyebrow { color: var(--teal); text-transform: uppercase; font-size: .72rem; font-weight: 700; letter-spacing: .12em; margin-bottom: .35rem; }
        .hero { background: linear-gradient(120deg, #edf7f2 0%, #f8f4eb 100%); border: 1px solid #d9e9e2; padding: 1.7rem 1.8rem; border-radius: 10px; margin-bottom: 1.2rem; }
        .hero p { color: #4b5d63; max-width: 720px; font-size: 1.02rem; margin-bottom: 0; }
        .metric { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.1rem; height: 100%; }
        .metric .label { color: var(--muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .08em; }
        .metric .value { font-family: 'Space Grotesk'; font-size: 1.7rem; color: var(--navy); font-weight: 700; margin-top: .25rem; }
        .metric .detail { color: var(--muted); font-size: .82rem; }
        .section-label { color: var(--navy); border-bottom: 2px solid #dbe5e4; padding-bottom: .55rem; margin: 1.2rem 0 .85rem; }
        .signal { border-left: 4px solid var(--teal); background: var(--mint); padding: .8rem 1rem; border-radius: 0 7px 7px 0; }
        .recommendation { border-radius: 8px; padding: 1rem 1.15rem; border: 1px solid; }
        .strong { background:#e7f5ee; border-color:#9dd4bd; color:#176244; }
        .consider { background:#fff6df; border-color:#e8c66b; color:#785600; }
        .pass { background:#fae9e6; border-color:#e4aaa0; color:#8c3027; }
        .recommendation .big { font-family:'Space Grotesk'; font-weight:700; font-size:1.35rem; }
        .small-note { color: var(--muted); font-size: .82rem; }
        div[data-testid="stDataFrame"] { border: 1px solid var(--line); }
        .stButton button[kind="primary"] { background: var(--teal); border-color: var(--teal); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def score_label(score: float) -> tuple[str, str]:
    if score >= 4:
        return "Strong hire", "strong"
    if score >= 3:
        return "Consider", "consider"
    return "Not a fit", "pass"


def extract_cv_text(uploaded_file: Any) -> str:
    if uploaded_file is None:
        return ""
    if uploaded_file.name.lower().endswith(".pdf"):
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(uploaded_file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            st.session_state.cv_read_error = f"PDF extraction failed: {exc}"
            return ""
    return uploaded_file.getvalue().decode("utf-8", errors="ignore")


def evaluate_cv(text: str, role: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    normalized = text.lower()
    keywords = role.get("keywords", [criterion.lower() for criterion, _, _ in role["criteria"]])
    matched = [keyword for keyword in keywords if keyword.lower() in normalized]
    missing = [keyword for keyword in keywords if keyword.lower() not in normalized]
    score = (len(matched) / len(keywords) * 5) if keywords else 0
    return round(score, 2), matched, missing


def extract_years_experience(text: str, explicit_value: Any = None) -> float:
    if explicit_value is not None and str(explicit_value).strip() and str(explicit_value).lower() != "nan":
        try:
            return max(0.0, float(explicit_value))
        except ValueError:
            pass
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", text.lower())
    return max((float(value) for value in matches), default=0.0)


def rank_lead(text: str, role: dict[str, Any], target_experience: int, explicit_experience: Any = None) -> dict[str, Any]:
    cv_score, matched, missing = evaluate_cv(text, role)
    years = extract_years_experience(text, explicit_experience)
    experience_score = min(5.0, years / target_experience * 5) if target_experience else 0.0
    final_score = round(cv_score * 0.7 + experience_score * 0.3, 2)
    recommendation, _ = score_label(final_score)
    return {"Keyword score": cv_score, "Experience score": round(experience_score, 2), "Years experience": years, "Rank score": final_score, "Matched keywords": ", ".join(matched), "Missing keywords": ", ".join(missing), "Recommendation": recommendation}


def role_keywords(role_name: str) -> list[str]:
    role = ROLES[role_name]
    defaults = role.get("keywords", [criterion for criterion, _, _ in role["criteria"]])
    custom = st.session_state.get("hr_keywords", {}).get(role_name, [])
    return list(dict.fromkeys(defaults + custom))


def role_with_hr_keywords(role_name: str) -> dict[str, Any]:
    role = dict(ROLES[role_name])
    role["keywords"] = role_keywords(role_name)
    return role


def salary_recommendation(role_name: str, experience: int, salary_text: str = "") -> tuple[int, int, str]:
    family = ROLES[role_name].get("family", "Engineering")
    family_baseline = {"Production": 11000, "Maintenance": 14000, "Quality": 13000, "Engineering": 16000, "Commercial": 18000, "Supply Chain": 14000, "Corporate": 13000}
    midpoint = family_baseline.get(family, 14000) + max(0, experience - 2) * 1800
    figures = [int(value.replace(",", "")) for value in re.findall(r"(?:EGP|E£|جنيه)?\s*([1-9]\d{3,6})", salary_text, flags=re.IGNORECASE)]
    if figures:
        midpoint = round((midpoint + sum(figures) / len(figures)) / 2)
        basis = "blended with figures extracted from the supplied public salary sources"
    else:
        basis = "prototype market baseline; add public source URLs to ground it"
    return round(midpoint * 0.85), round(midpoint * 1.15), basis


def fetch_salary_sources(urls: str) -> str:
    snippets = []
    for raw_url in urls.splitlines():
        url = raw_url.strip()
        if not url or urlparse(url).scheme not in {"http", "https"}:
            continue
        try:
            response = requests.get(url, timeout=8, headers={"User-Agent": "EGY-CRETE-Recruitment-Prototype/1.0"})
            response.raise_for_status()
            snippets.append(re.sub(r"<[^>]+>", " ", response.text)[:50000])
        except requests.RequestException:
            continue
    return "\n".join(snippets)


def initialise_state() -> None:
    initialise_database()
    if "salary_sources" not in st.session_state:
        st.session_state.salary_sources = ""
    if "hr_keywords" not in st.session_state:
        st.session_state.hr_keywords = {}


def candidate_analysis(role_name: str) -> None:
    role = role_with_hr_keywords(role_name)
    st.markdown(f"<div class='eyebrow'>Candidate workbench / {role['short']}</div>", unsafe_allow_html=True)
    st.header("Build a complete candidate profile")
    st.caption(role["description"])

    left, right = st.columns([1, 1.5], gap="large")
    with left:
        st.markdown("<div class='section-label'><b>1 / Candidate and CV</b></div>", unsafe_allow_html=True)
        candidate_name = st.text_input("Candidate name", placeholder="e.g. Ahmed Mostafa")
        source = st.selectbox("Source channel", ["Employee referral", "Technical institute", "LinkedIn", "Job board", "Direct outreach", "Public profile / career page", "Other"])
        cv_file = st.file_uploader("Upload CV", type=["pdf", "txt"], help="The prototype reads the file locally and matches it against the selected role's keywords.")
        cv_text = extract_cv_text(cv_file)
        cv_score, matched, missing = evaluate_cv(cv_text, role)
        if cv_file and not cv_text:
            st.warning("This file could not be read. Install pypdf for PDF support or use a text CV.")
        elif cv_file:
            st.markdown(f"<div class='recommendation {'strong' if cv_score >= 3.5 else 'consider'}'><div class='small-note'>CV keyword signal</div><div class='big'>{cv_score:.2f} / 5.00</div><div class='small-note'>{len(matched)} matched · {len(missing)} missing or unverified</div></div>", unsafe_allow_html=True)
            st.caption("Matched: " + (", ".join(matched) if matched else "none"))
            st.caption("Verify: " + (", ".join(missing) if missing else "none"))
        experience = st.number_input("Relevant experience (years)", min_value=0, max_value=50, value=2)
        current_stage = st.selectbox("Current stage", STAGES + ["Final review"])
        st.markdown("<div class='section-label'><b>2 / Salary intelligence</b></div>", unsafe_allow_html=True)
        salary_urls = st.text_area("Public salary source URLs (optional)", placeholder="One public job-market or salary page URL per line", height=75)
        if st.button("Research salary sources"):
            st.session_state.salary_sources = fetch_salary_sources(salary_urls)
            st.info("Public source text fetched. Review the figures before using them; blocked or inaccurate pages are ignored.")
        low, high, salary_basis = salary_recommendation(role_name, experience, st.session_state.salary_sources)
        st.markdown(f"<div class='metric'><div class='label'>Recommended monthly range</div><div class='value'>EGP {low:,} – {high:,}</div><div class='detail'>{salary_basis}</div></div>", unsafe_allow_html=True)
        st.markdown("<div class='signal'><b>Responsible use:</b> salary data is a negotiation aid, not a gate. Do not use protected characteristics or opaque scraped data in a hiring decision.</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='section-label'><b>3 / Stage-specific evaluations</b></div>", unsafe_allow_html=True)
        st.caption("Each stage has its own score and evidence. A missing stage stays missing instead of silently becoming a good score.")
        stage_scores: dict[str, float] = {"CV screening": cv_score if cv_file else 0}
        stage_evidence: dict[str, str] = {}
        tabs = st.tabs(STAGES)
        for tab, stage_name in zip(tabs, STAGES):
            with tab:
                if stage_name == "CV screening":
                    st.metric("CV score", f"{cv_score:.2f} / 5" if cv_file else "Not assessed")
                    stage_evidence[stage_name] = st.text_area("CV evidence", value="; ".join(matched), key=f"evidence-{role_name}-{stage_name}", height=90)
                else:
                    stage_score = st.slider("Stage score", 0.0, 5.0, 0.0, 0.5, key=f"stage-score-{role_name}-{stage_name}", help="Use 0 when this stage has not happened yet.")
                    stage_scores[stage_name] = stage_score
                    st.write("Evaluate:")
                    for criterion, description, _ in role["criteria"][:4]:
                        st.checkbox(criterion, key=f"check-{role_name}-{stage_name}-{criterion}", help=description)
                    stage_evidence[stage_name] = st.text_area("Evidence and decision notes", key=f"evidence-{role_name}-{stage_name}", height=80, placeholder="Observed result, answer, test score, or reference quote")
        st.markdown("<div class='section-label'><b>4 / Human judgment layer</b></div>", unsafe_allow_html=True)
        human_signal = st.slider("Motivation and role fit", 1, 5, 3, help="Keep this separate from the evidence-based criteria. It informs discussion but does not override missing evidence.")
        concern = st.text_area("Open concern or context", placeholder="Anything the panel should verify before making a decision...", height=75)
        assessed_weight = sum(STAGE_WEIGHTS[stage] for stage, value in stage_scores.items() if value > 0)
        total_score = sum(stage_scores[stage] * STAGE_WEIGHTS[stage] for stage in STAGE_WEIGHTS if stage_scores.get(stage, 0) > 0) / assessed_weight if assessed_weight else 0
        recommendation, style = score_label(total_score)
        st.markdown(f"<div class='recommendation {style}'><div class='small-note'>Current evidence score · {assessed_weight}% of pipeline assessed</div><div class='big'>{total_score:.2f} / 5.00 · {recommendation}</div><div class='small-note'>Ranking uses CV, assessment, interview, and references separately; it never treats an uncompleted stage as a pass.</div></div>", unsafe_allow_html=True)
        if st.button("Save complete candidate profile", type="primary", use_container_width=True):
            if not candidate_name.strip():
                st.warning("Add a candidate name before saving.")
            elif not cv_file:
                st.warning("Upload a CV or add a text CV before saving this complete profile.")
            else:
                save_candidate({"Candidate": candidate_name.strip(), "Role": role_name, "Score": round(total_score, 2), "CV score": cv_score, "Years experience": experience, "Assessment": stage_scores.get("Technical assessment", 0), "Interview": stage_scores.get("Structured interview", 0), "References": stage_scores.get("Reference check", 0), "Salary low": low, "Salary high": high, "Recommendation": recommendation, "Source": source, "Status": current_stage})
                st.success(f"Saved {candidate_name.strip()} with a {recommendation.lower()} signal.")


def compare_view() -> None:
    st.markdown("<div class='eyebrow'>Decision room / compare</div>", unsafe_allow_html=True)
    st.header("Rank the shortlist")
    st.caption("Ranking combines completed pipeline stages and keeps CV, assessment, interview, references, and salary visible as separate signals.")
    df = pd.DataFrame(candidate_records())
    if df.empty:
        st.info("Save a candidate analysis first.")
        return
    role_filter = st.selectbox("Role", ["All roles"] + list(ROLES.keys()))
    filtered = df if role_filter == "All roles" else df[df["Role"] == role_filter]
    columns = [column for column in ["Candidate", "Role", "Score", "CV score", "Years experience", "Assessment", "Interview", "References", "Salary low", "Salary high", "Recommendation", "Source", "Status", "Created at", "Updated at"] if column in filtered.columns]
    st.dataframe(filtered.sort_values("Score", ascending=False)[columns], use_container_width=True, hide_index=True, column_config={"Score": st.column_config.NumberColumn(format="%.2f / 5"), "CV score": st.column_config.NumberColumn(format="%.2f / 5")})
    st.markdown("<div class='section-label'><b>Score distribution</b></div>", unsafe_allow_html=True)
    chart = filtered.set_index("Candidate")["Score"] if not filtered.empty else pd.Series(dtype=float)
    st.bar_chart(chart, y_label="Weighted score / 5")
    export = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("Download shortlist CSV", export, "egy-crete-shortlist.csv", "text/csv")


def sourcing_view() -> None:
    st.markdown("<div class='eyebrow'>Talent discovery / sourcing</div>", unsafe_allow_html=True)
    st.header("Build a reviewable talent pool")
    st.caption("Import leads from approved public sources, then evaluate them in the same workbench. The prototype does not bypass logins, CAPTCHAs, robots rules, or platform terms.")
    role_name = st.selectbox("Target role", list(ROLES.keys()), key="sourcing-role")
    role = role_with_hr_keywords(role_name)
    target_experience = st.number_input("Minimum target experience (years)", min_value=0, max_value=50, value=2, key="sourcing-experience")
    st.markdown("<div class='section-label'><b>LinkedIn sourcing workflow</b></div>", unsafe_allow_html=True)
    st.caption("Create a focused LinkedIn search, review profiles in LinkedIn, then import only candidates you are permitted to contact. The app does not automate LinkedIn login or scrape profile pages.")
    linkedIn_query = " OR ".join(f'\"{keyword}\"' for keyword in role.get("keywords", [])[:10])
    location = st.text_input("Search location", value="Egypt", key="linkedin-location")
    query = st.text_input("LinkedIn keyword query", value=linkedIn_query, key="linkedin-query")
    linkedin_url = f"https://www.linkedin.com/search/results/people/?keywords={requests.utils.quote(query)}&location={requests.utils.quote(location)}"
    st.link_button("Open this search in LinkedIn", linkedin_url, use_container_width=False)
    template = pd.DataFrame(columns=["Candidate", "Profile URL", "Headline", "Location", "Years experience", "CV text", "Source", "Consent status", "Notes"])
    st.download_button("Download LinkedIn review template", template.to_csv(index=False).encode("utf-8"), "linkedin-candidate-review-template.csv", "text/csv")
    st.info("Workflow: open the search, review results manually in LinkedIn, record permitted leads in the template, then upload it below. This keeps the source and consent trail attached to every candidate.")

    st.markdown("<div class='section-label'><b>Import LinkedIn review results</b></div>", unsafe_allow_html=True)
    linkedin_file = st.file_uploader("Upload LinkedIn review CSV", type=["csv"], key="linkedin-csv", help="Use the downloaded template. Profile URL and Candidate are required.")
    if linkedin_file:
        try:
            linkedin_leads = pd.read_csv(linkedin_file)
            required = {"Candidate", "Profile URL"}
            if not required.issubset(linkedin_leads.columns):
                st.error("LinkedIn CSV must include Candidate and Profile URL columns. Download the template above.")
            else:
                linkedin_leads = linkedin_leads.head(50).copy()
                linkedin_leads["Role"] = role_name
                linkedin_leads["Source"] = "LinkedIn"
                if "Consent status" not in linkedin_leads.columns:
                    linkedin_leads["Consent status"] = "Not recorded"
                linkedin_leads["Status"] = "Needs CV/consent review"
                if "CV text" not in linkedin_leads:
                    linkedin_leads["CV text"] = ""
                linkedin_leads["CV text"] = linkedin_leads["CV text"].fillna("")
                scores = linkedin_leads.apply(lambda row: pd.Series(rank_lead(f"{row.get('Headline', '')} {row.get('CV text', '')} {row.get('Notes', '')}", role, target_experience, row.get("Years experience"))), axis=1)
                linkedin_leads = pd.concat([linkedin_leads, scores], axis=1).sort_values("Rank score", ascending=False)
                st.dataframe(linkedin_leads, use_container_width=True, hide_index=True)
                if st.button("Add LinkedIn leads to review queue", type="primary"):
                    for lead in linkedin_leads.to_dict("records"):
                        save_candidate({"Candidate": lead["Candidate"], "Role": role_name, "Score": lead["Rank score"], "CV score": lead["Keyword score"], "Years experience": lead["Years experience"], "Recommendation": lead["Recommendation"], "Source": "LinkedIn", "Status": lead["Status"], "Profile URL": lead["Profile URL"]})
                    st.success(f"Added {len(linkedin_leads)} LinkedIn leads. Upload a CV and complete the stage evaluations before ranking.")
        except Exception as exc:
            st.error(f"Could not read the LinkedIn CSV: {exc}")

    st.markdown("<div class='section-label'><b>Other approved lead imports</b></div>", unsafe_allow_html=True)
    leads_file = st.file_uploader("Import a permitted candidate-leads CSV", type=["csv"], help="Expected columns: Candidate, Profile URL, Source. Do not upload sensitive personal data you do not have permission to process.")
    if leads_file:
        try:
            leads = pd.read_csv(leads_file)
            required = {"Candidate", "Profile URL"}
            if not required.issubset(leads.columns):
                st.error("The CSV needs Candidate and Profile URL columns.")
            else:
                leads = leads.head(50).copy()
                leads["Role"] = role_name
                leads["Status"] = "Needs CV/consent review"
                if "CV text" not in leads:
                    leads["CV text"] = ""
                leads["CV text"] = leads["CV text"].fillna("")
                scores = leads.apply(lambda row: pd.Series(rank_lead(f"{row.get('Headline', '')} {row.get('CV text', '')} {row.get('Notes', '')}", role, target_experience, row.get("Years experience"))), axis=1)
                leads = pd.concat([leads, scores], axis=1).sort_values("Rank score", ascending=False)
                st.dataframe(leads, use_container_width=True, hide_index=True)
                st.download_button("Download review queue", leads.to_csv(index=False).encode("utf-8"), "egy-crete-review-queue.csv", "text/csv")
        except Exception as exc:
            st.error(f"Could not read this CSV: {exc}")
    st.markdown("<div class='section-label'><b>Public source inspection</b></div>", unsafe_allow_html=True)
    public_urls = st.text_area("Approved public source URLs", placeholder="One public career page or talent-community URL per line", height=90)
    if st.button("Inspect public pages"):
        source_text = fetch_salary_sources(public_urls)
        if source_text:
            matched = [keyword for keyword in role.get("keywords", []) if keyword.lower() in source_text.lower()]
            st.success(f"Inspected public page text. Role signals found: {', '.join(matched) if matched else 'none'}.")
            st.info("Use the source page's permitted contact or application flow. The next step is to obtain consent and a CV before scoring an individual.")
        else:
            st.warning("No readable public page was returned. Check the URL and access permissions.")
    st.markdown("<div class='signal'><b>Human review required:</b> public availability does not equal permission to store or contact someone. Keep a source URL, consent status, retention policy, and opt-out path for every lead.</div>", unsafe_allow_html=True)


def outcomes_view() -> None:
    st.markdown("<div class='eyebrow'>Learning loop / outcomes</div>", unsafe_allow_html=True)
    st.header("Close the loop at 90 days")
    st.caption("The scorecard becomes a learning system only when predicted signals are compared with real performance.")
    candidate_names = [c["candidate"] for c in candidate_records()]
    with st.form("outcome_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            candidate = st.selectbox("Hired candidate", candidate_names or ["No saved candidates"])
            review_date = st.date_input("Review date", value=date.today())
        with c2:
            supervisor_rating = st.slider("Supervisor rating", 1.0, 5.0, 3.5, 0.5)
            retained = st.selectbox("Still employed at review?", ["Yes", "No"])
        with c3:
            primary_outcome = st.number_input("Primary measurable outcome", min_value=0.0, step=1.0, help="Examples: downtime hours owned, deals closed, or another role-specific measure.")
            notes = st.text_input("Review note", placeholder="What happened in practice?")
        submitted = st.form_submit_button("Log 90-day outcome", type="primary")
    if submitted and candidate_names:
        save_outcome({"Candidate": candidate, "Review date": review_date.isoformat(), "Supervisor rating": supervisor_rating, "Retained": retained, "Primary outcome": primary_outcome, "Notes": notes})
        st.success("Outcome logged. This record is ready for future weight calibration.")
    outcomes = outcome_records()
    if outcomes:
        st.markdown("<div class='section-label'><b>Outcome history</b></div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(outcomes), use_container_width=True, hide_index=True)
    else:
        st.info("No 90-day outcomes logged yet. Start with the next completed review.")


def parse_scorecard_workbook(uploaded_file: Any) -> dict[str, dict[str, Any]]:
    workbook = pd.ExcelFile(uploaded_file)
    loaded: dict[str, dict[str, Any]] = {}
    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(workbook, sheet_name=sheet_name)
        columns = {str(column).strip().lower(): column for column in frame.columns}
        criterion_column = next((columns[name] for name in columns if "criterion" in name or "criteria" in name), None)
        weight_column = next((columns[name] for name in columns if "weight" in name or "percentage" in name), None)
        if criterion_column is None or weight_column is None:
            continue
        criteria = []
        for _, row in frame[[criterion_column, weight_column]].dropna(how="any").iterrows():
            criterion = str(row[criterion_column]).strip()
            try:
                weight = float(str(row[weight_column]).replace("%", "").strip())
            except ValueError:
                continue
            if criterion and weight > 0:
                criteria.append((criterion, f"Workbook criterion: {criterion}.", weight))
        if criteria:
            role_name = next((name for name in ROLES if name.lower() == sheet_name.strip().lower()), sheet_name.strip())
            base = ROLES.get(role_name, {"short": sheet_name.strip(), "description": f"Role criteria imported from {sheet_name}.", "family": "Imported", "outcomes": ["Supervisor rating (1-5)", "Retained at 90 days"]})
            loaded[role_name] = {**base, "criteria": criteria, "keywords": [criterion for criterion, _, _ in criteria]}
    return loaded


def import_template() -> None:
    with st.sidebar.expander("Import workbook", expanded=False):
        uploaded = st.file_uploader("Load an existing scorecard (.xlsx)", type=["xlsx"])
        if uploaded:
            try:
                workbook = pd.ExcelFile(uploaded)
                st.caption(f"Found sheets: {', '.join(workbook.sheet_names)}")
                if st.button("Apply workbook criteria", key="apply-workbook"):
                    imported = parse_scorecard_workbook(uploaded)
                    ROLES.update(imported)
                    st.session_state.workbook_roles = list(imported)
                    st.success(f"Applied {len(imported)} role scorecard(s) from Excel.")
                if st.session_state.get("workbook_roles"):
                    st.caption("Active workbook roles: " + ", ".join(st.session_state.workbook_roles))
            except Exception as exc:
                st.error(f"Could not read workbook: {exc}")


def main() -> None:
    inject_css()
    initialise_state()
    if not login_gate():
        return
    st.sidebar.markdown("## EGY-CRETE")
    st.sidebar.caption("People intelligence prototype")
    page = st.sidebar.radio("Workspace", ["Recruitment analysis", "Rank shortlist", "Talent sourcing", "90-day outcomes", "How this works"], label_visibility="collapsed")
    import_template()
    if st.sidebar.button("Sign out"):
        st.session_state.authenticated = False
        st.rerun()
    st.sidebar.divider()
    st.sidebar.caption("Prototype · Phase 1 scorecard")

    if page == "Recruitment analysis":
        st.markdown("<div class='hero'><div class='eyebrow'>Recruitment analysis</div><h1>Hire for the signals that matter.</h1><p>A transparent, role-specific scorecard for EGY-CRETE's production and commercial teams. Start with evidence, then use judgment with intention.</p></div>", unsafe_allow_html=True)
        role = st.selectbox("Choose a role", list(ROLES.keys()))
        current_keywords = ", ".join(role_keywords(role))
        keyword_text = st.text_area("HR lookup keywords", value=current_keywords, help="Write the terms HR wants the CV scanner and candidate sourcing ranking to use. Separate keywords with commas.", height=80)
        st.session_state.hr_keywords[role] = [keyword.strip() for keyword in keyword_text.split(",") if keyword.strip()]
        m1, m2, m3, m4 = st.columns(4)
        metrics = [("2", "role scorecards", "ready to test"), ("1–5", "evidence scale", "same for every candidate"), ("90 days", "review loop", "turn scores into learning"), ("30–50+", "future model", "minimum useful history")]
        for col, (value, label, detail) in zip([m1, m2, m3, m4], metrics):
            with col:
                st.markdown(f"<div class='metric'><div class='label'>{label}</div><div class='value'>{value}</div><div class='detail'>{detail}</div></div>", unsafe_allow_html=True)
        candidate_analysis(role)
    elif page == "Rank shortlist":
        compare_view()
    elif page == "Talent sourcing":
        sourcing_view()
    elif page == "90-day outcomes":
        outcomes_view()
    else:
        st.markdown("<div class='eyebrow'>Operating model</div>", unsafe_allow_html=True)
        st.header("A practical Brighton-style loop")
        st.caption("The useful idea is disciplined learning, not a secret algorithm.")
        steps = [
            ("01", "Define success", "Agree role-specific criteria and weights before sourcing starts."),
            ("02", "Measure directly", "Use practical tests, structured interviews, and evidence instead of CV impressions."),
            ("03", "Keep judgment visible", "Record motivation, safety mindset, and concerns as a separate human layer."),
            ("04", "Review outcomes", "At 90 days, compare the predicted score with supervisor results and retention."),
            ("05", "Refine carefully", "After 30–50+ hires, test whether the weights actually predict success."),
        ]
        for number, title, text in steps:
            st.markdown(f"<div class='metric' style='margin-bottom:.65rem'><span style='color:#0b8276;font-weight:700'>{number}</span>&nbsp;&nbsp;<b>{title}</b><br><span class='small-note' style='margin-left:2.1rem'>{text}</span></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
