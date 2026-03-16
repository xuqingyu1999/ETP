import base64
import csv
import html
import json
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =============================================================================
# EXPERIMENT SETTINGS
# =============================================================================
EXPERIMENT_VARIANT = "TOPIC_THREAD_FEELINGS_V2"

# Reddit-like UI meta
SUBREDDIT = "r/business"
POST_DAYS_AGO = 7

# Neutral poster identity shown in the prompt (not necessarily inside the post text)
POSTED_BY_NAME = "Alex"
AUTHOR_USERNAME = "HiddenBadger74"

# Commenter identity (neutral)
COMMENTER_USERNAME = "SageOtter21"
COMMENT_DAYS_AGO = 5

# Timing gates
MIN_SECONDS_CONSENT = 10
MIN_SECONDS_THREAD = 20

# Attention check
ATTENTION_MAX_ATTEMPTS = 2
ATTENTION_CHECK_1_SENTENCE = "Bobby is very happy because he is going to the movies."
ATTENTION_CHECK_1_OPTIONS = ["very", "happy", "going", "because", "movies", "is", "the"]
ATTENTION_CHECK_1_CORRECT = "because"

ATTENTION_CHECK_2_OPTIONS = ["Grape", "Apple", "Pear", "Orange", "Strawberry"]
ATTENTION_CHECK_2_CORRECT = "Orange"

# Topic choices
TOPIC_GROUPS: Dict[str, List[str]] = {
    "Business": [
        "Financing",
        "Customers",
        "Growth challenges",
        "Employee",
        "Legal",
        "Operations",
    ],
    "Worklife balance": [
        "Family responsibilities",
        "Time management",
        "Emotional strain",
        "Social Relationships",
        "Well-being",
        "Boundary management",
    ],
}

# CSV source (recommended columns: topic, post_title, post_body, comment; optional: link_id)
DEFAULT_THREADS_CSV_CANDIDATES = ["topic_threads_cleaned.csv", "topic_threads.csv"]

# Google Sheet target
DEFAULT_SPREADSHEET_NAME = "ETP-TOPIC-FEELINGS"
GSHEET_KEYS = ["id", "start", "variant", "timestamp", "type", "title", "url"]

APP_DIR = Path(__file__).parent
REDDIT_LOGO_PATH = APP_DIR / "reddit_logo.png"
AVATAR_PATH = APP_DIR / "avatar.jpg"

# =============================================================================
# STREAMLIT PAGE CONFIG + GLOBAL CSS
# =============================================================================
st.set_page_config(page_title="Thread Feelings Study", page_icon="🧪", layout="centered")

st.markdown(
    """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header [data-testid="stToolbar"] {display: none !important;}
header [data-testid="stToolbarActions"] {display: none !important;}

/* Emphasis styling for name/topic */
.emph {
  font-weight: 800;
  text-decoration: underline;
  background: #fff3bf;
  color: #111 !important; /* ensure readable on the highlight in both light/dark themes */
  padding: 0 4px;
  border-radius: 4px;
}

/* Make meta text "muted" without hard-coding colors (works in light/dark) */
.muted { opacity: 0.75; }
.muted-2 { opacity: 0.6; }

/* Post typography */
.post-title {
  font-size: 1.45rem;
  font-weight: 800;
  margin: 0.2rem 0 0.55rem 0;
  line-height: 1.25;
}
.post-body {
  font-size: 1.02rem;
  line-height: 1.55;
  margin-bottom: 0.2rem;
}

/* Comment typography */
.comment-label {
  font-weight: 800;
  margin: 0.2rem 0 0.4rem 0;
}
.comment-container {
  display:flex;
  gap:10px;
  margin-top: 4px;
  margin-bottom: 8px;
}
.avatar-circle {
  width:34px;
  height:34px;
  border-radius:50%;
  background: rgba(127,127,127,0.22);
  display:flex;
  align-items:center;
  justify-content:center;
  font-weight: 800;
  color: inherit;
  border: 1px solid rgba(127,127,127,0.25);
}
.comment-header {
  font-size:0.95rem;
}
.comment-body {
  margin-top:4px;
  font-size:1rem;
  line-height:1.45;
}

/* Slightly more Reddit-y typography */
:root { --banner-font-size: 2rem; }
</style>
""",
    unsafe_allow_html=True,
)

# =============================================================================
# UTILITIES
# =============================================================================
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_query_param(name: str) -> Optional[str]:
    """Compatibility wrapper across Streamlit versions."""
    try:
        v = st.query_params.get(name)
        if isinstance(v, list):
            return v[0] if v else None
        return v
    except Exception:
        try:
            params = st.experimental_get_query_params()
            v2 = params.get(name)
            return v2[0] if v2 else None
        except Exception:
            return None


def scroll_to_top_once() -> None:
    components.html(
        """
<script>
  window.scrollTo({ top: 0, behavior: 'instant' });
</script>
""",
        height=0,
    )


def show_alert(message: str) -> None:
    components.html(
        f"""
<script>
  alert({json.dumps(message)});
</script>
""",
        height=0,
    )


def to_data_uri(local_path: Path) -> str:
    """Return a data: URI for an image if it exists; otherwise empty string."""
    if not local_path.exists():
        return ""
    suffix = local_path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        suffix, "image/png"
    )
    b64 = base64.b64encode(local_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _nl2br_escaped(text: str) -> str:
    """Escape HTML and convert newlines to <br>."""
    safe = html.escape(text or "")
    safe = safe.replace("\r\n", "\n").replace("\r", "\n")
    safe = "\n".join(line.rstrip() for line in safe.split("\n"))
    safe = safe.replace("\n", "<br>")
    return safe


def _normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


# =============================================================================
# GOOGLE SHEETS LOGGING
# =============================================================================
def get_credentials_from_secrets() -> Dict[str, Any]:
    creds_dict = {k: v for k, v in st.secrets["GOOGLE_CREDENTIALS"].items()}
    if isinstance(creds_dict.get("private_key"), str):
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    return creds_dict


@st.cache_resource(show_spinner=False)
def _get_sheet1():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(get_credentials_from_secrets(), scope)
    client = gspread.authorize(creds)

    spreadsheet_name = (
        st.secrets.get("SPREADSHEET_NAME", None)
        if hasattr(st, "secrets")
        else None
    )
    spreadsheet_name = spreadsheet_name or os.getenv("SPREADSHEET_NAME") or DEFAULT_SPREADSHEET_NAME
    ws = client.open(spreadsheet_name).sheet1

    # Ensure header exists
    first = ws.row_values(1)
    if not first:
        ws.append_row(GSHEET_KEYS)

    return ws


LOCAL_FALLBACK = "fallback_event_log.csv"


def _append_local(row: List[Any]) -> None:
    exists = Path(LOCAL_FALLBACK).exists()
    with open(LOCAL_FALLBACK, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(GSHEET_KEYS)
        w.writerow(row)


def save_to_gsheet(data: Dict[str, Any]) -> None:
    row = [data.get(k, "") for k in GSHEET_KEYS]
    _append_local(row)

    try:
        ws = _get_sheet1()
        ws.append_row(row)
    except Exception as e:
        # keep error for debug
        st.session_state["_gsheet_error"] = str(e)


def log_event(event_type: str, *, title: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
    pid = st.session_state.get("prolific_id") or ""
    start = st.session_state.get("start_time") or ""
    save_to_gsheet(
        {
            "id": pid,
            "start": start,
            "variant": EXPERIMENT_VARIANT,
            "timestamp": utc_now_iso(),
            "type": event_type,
            "title": title,
            "url": json.dumps(payload or {}, ensure_ascii=False),
        }
    )


def render_debug_box():
    with st.expander("Debug (Google Sheets / CSV)", expanded=False):
        st.write("Variant:", EXPERIMENT_VARIANT)
        st.write("Stage:", st.session_state.get("stage"))
        st.write("Assigned category:", st.session_state.get("assigned_category"))
        st.write("Chosen subtopic:", st.session_state.get("chosen_subtopic"))
        st.write("Thread source:", st.session_state.get("_threads_source"))
        err = st.session_state.get("_gsheet_error")
        if err:
            st.error(f"GSheet error: {err}")
        st.write("Local fallback log:", LOCAL_FALLBACK)


# =============================================================================
# UI COMPONENTS
# =============================================================================
def render_banner():
    logo_uri = to_data_uri(REDDIT_LOGO_PATH)
    img_html = f'<img src="{logo_uri}" style="width:36px;height:36px;">' if logo_uri else ""
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;width:100%;padding:16px 0 24px 0;">
            {img_html}
            <span style="font-family:Roboto,Arial,sans-serif;font-size:var(--banner-font-size);line-height:1.1;font-weight:700;color:#FF4500;">reddit</span>
        </div>
        <hr style="margin:0 0 20px 0;">
        """,
        unsafe_allow_html=True,
    )


def render_post_meta():
    avatar_uri = to_data_uri(AVATAR_PATH)
    img_html = (
        f'<img src="{avatar_uri}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">'
        if avatar_uri
        else '<div class="avatar-circle" style="width:40px;height:40px;">A</div>'
    )
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            {img_html}
            <div style="line-height:1.1;">
                <div style="font-weight:700;">{html.escape(SUBREDDIT)} &middot; {POST_DAYS_AGO} days ago</div>
                <div class="muted" style="font-size:0.95rem;">{html.escape(AUTHOR_USERNAME)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_post_content(title: str, body: str):
    safe_title = _nl2br_escaped(_normalize_text(title))
    safe_body = _nl2br_escaped(_normalize_text(body))
    st.markdown(
        f"""
        <div class="post-title">{safe_title}</div>
        <div class="post-body">{safe_body}</div>
        """,
        unsafe_allow_html=True,
    )


def render_comment(comment_text: str):
    letter = (COMMENTER_USERNAME[:1] or "?").upper()
    safe_text = _nl2br_escaped(_normalize_text(comment_text))

    st.markdown(
        f"""
        <div class="comment-container">
            <div class="avatar-circle">{html.escape(letter)}</div>
            <div style="flex:1;">
                <div class="comment-header muted">
                    <span style="font-weight:800; opacity: 1;">{html.escape(COMMENTER_USERNAME)}</span>
                    &nbsp;&middot;&nbsp; {COMMENT_DAYS_AGO} days ago
                </div>
                <div class="comment-body">
                    {safe_text}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# CSV LOADER + LIGHT CLEANUP
# =============================================================================
def _pick_column(keys: List[str], candidates: List[str]) -> Optional[str]:
    lower_map = {k.lower().strip(): k for k in keys}
    for c in candidates:
        if c.lower().strip() in lower_map:
            return lower_map[c.lower().strip()]
    return None


def _decode_bytes_with_fallback(b: bytes) -> str:
    """Decode bytes to text using a small set of likely encodings."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    # last resort
    return b.decode("utf-8", errors="replace")


def _read_csv_text(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read a CSV from disk with encoding fallback. Returns (rows, headers)."""
    raw = Path(path).read_bytes()
    text = _decode_bytes_with_fallback(raw)
    f = text.splitlines()
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return [], []
    headers = rows[0]
    data_rows = rows[1:]
    dict_rows = [dict(zip(headers, r)) for r in data_rows if any(str(cell).strip() for cell in r)]
    return dict_rows, headers


def clean_thread_fields(topic: str, title: str, body: str, comment: str) -> Tuple[str, str, str, str]:
    """
    Minimal cleanup to avoid formatting issues and remove a few flagged strings.
    - Avoid visible backslashes from prior escaping (e.g., '\\$' -> '$')
    - Remove a specific location string in Growth challenges ("Key West")
    - Redact sensitive / link-heavy segments in Employee comment by replacing with a neutral version
    """
    topic_norm = (topic or "").strip()

    title = _normalize_text(title).replace(r"\$", "$")
    body = _normalize_text(body).replace(r"\$", "$")
    comment = _normalize_text(comment).replace(r"\$", "$")

    # Growth challenges: remove location label
    if topic_norm.lower() == "growth challenges":
        body = body.replace("Key West", "a local area").replace("KEY WEST", "a local area")

    # Employee: replace comment with cleaned version (removes PDF/link + location references)
    if topic_norm.lower() == "employee":
        comment = """Hi there — IT person here, offering some perspective.

An entry-level hardware service technician role is often compared to PC technician / Tier I support roles. If the wage you're offering is below local market rates, it can be very difficult to hire—even for an entry-level position.

A few ideas that may help:
- Re-check what similar roles pay in your area and adjust compensation (or clarify the role as a trainee/apprentice position).
- Tighten the job description so candidates understand the required skills and expectations.
- Broaden recruiting channels (community colleges, trade schools, apprenticeship programs), and make the application process simple.

TL;DR: If pay and expectations don't match the market, you'll keep seeing low-quality applicants or people declining offers."""

    return topic_norm, title, body, comment


def load_threads_csv(path: str, *, uploaded_bytes: Optional[bytes] = None) -> List[Dict[str, str]]:
    """
    Supports:
      - Named columns (recommended): topic, post_title, post_body, comment (optional: link_id)
      - Alternative names: Topic/Post/Comment; post_md; comment_md; etc.
      - If unnamed/unknown but exactly 3 columns: assumes topic, post, comment by order.
    If a single 'post' column is used: first line -> title; remainder -> body.
    """
    if uploaded_bytes is not None:
        text = _decode_bytes_with_fallback(uploaded_bytes)
        f = text.splitlines()
        reader = csv.reader(f)
        rows = list(reader)
        if not rows:
            return []
        headers = rows[0]
        data_rows = rows[1:]
        dict_rows = [dict(zip(headers, r)) for r in data_rows if any(str(cell).strip() for cell in r)]
        keys = headers
    else:
        dict_rows, keys = _read_csv_text(path)

    if not dict_rows:
        return []

    # detect columns
    topic_col = _pick_column(keys, ["topic", "subtopic", "topic_name"])
    post_col = _pick_column(keys, ["post", "thread", "post_md", "post_text", "postcontent"])
    comment_col = _pick_column(keys, ["comment", "reply", "comment_md", "comment_text", "response"])

    # fallback: if exactly 3 columns and any of above missing
    if (topic_col is None or (post_col is None and (_pick_column(keys, ["post_title", "title"]) is None)) or comment_col is None) and len(keys) == 3:
        topic_col = topic_col or keys[0]
        post_col = post_col or keys[1]
        comment_col = comment_col or keys[2]

    # optional split columns
    title_col = _pick_column(keys, ["post_title", "title"])
    body_col = _pick_column(keys, ["post_body", "body"])
    linkid_col = _pick_column(keys, ["link_id", "linkid", "reddit_id"])

    threads: List[Dict[str, str]] = []
    for r in dict_rows:
        topic = (r.get(topic_col or "", "") or "").strip()
        if not topic:
            continue

        if title_col and body_col:
            title = (r.get(title_col, "") or "").strip()
            body = (r.get(body_col, "") or "").strip()
        else:
            post_raw = (r.get(post_col or "", "") or "").strip()
            if "\n" in post_raw:
                first, rest = post_raw.split("\n", 1)
                title = first.strip()
                body = rest.strip()
            else:
                title = post_raw.strip()
                body = ""

        comment = (r.get(comment_col or "", "") or "").strip()
        link_id = (r.get(linkid_col or "", "") or "").strip() if linkid_col else ""

        topic, title, body, comment = clean_thread_fields(topic, title, body, comment)

        threads.append(
            {
                "topic": topic,
                "title": title,
                "body": body,
                "comment": comment,
                "link_id": link_id,
            }
        )

    return threads


def get_threads_data() -> Tuple[List[Dict[str, str]], str]:
    """
    Returns (threads, source_description).
    Tries:
      1) session_state['uploaded_threads_csv_bytes'] if present
      2) file path from secrets/env
      3) fall back to candidate filenames in the app directory
    """
    # 1) uploaded
    uploaded = st.session_state.get("uploaded_threads_csv_bytes")
    if uploaded:
        return load_threads_csv("uploaded", uploaded_bytes=uploaded), "uploaded CSV"

    # 2) explicit path from secrets/env
    csv_path = (
        st.secrets.get("TOPIC_CSV_PATH", None)
        if hasattr(st, "secrets")
        else None
    )
    csv_path = csv_path or os.getenv("TOPIC_CSV_PATH")
    if csv_path:
        abs_path = Path(csv_path)
        if not abs_path.is_absolute():
            abs_path = (APP_DIR / csv_path).resolve()
        if abs_path.exists():
            return load_threads_csv(str(abs_path)), str(abs_path)

    # 3) candidates in app folder
    for cand in DEFAULT_THREADS_CSV_CANDIDATES:
        p = (APP_DIR / cand).resolve()
        if p.exists():
            return load_threads_csv(str(p)), str(p)

    return [], f"missing ({', '.join(DEFAULT_THREADS_CSV_CANDIDATES)})"


def ensure_thread_selected() -> Optional[Dict[str, str]]:
    """Pick (and freeze) a single thread record based on selected topic."""
    chosen_topic = st.session_state.get("chosen_subtopic")
    if not chosen_topic:
        return None

    current = st.session_state.get("selected_thread")
    if current and current.get("topic") == chosen_topic:
        return current

    threads, source = get_threads_data()
    if not threads:
        st.session_state["_threads_source"] = source
        return None

    matches = [t for t in threads if (t.get("topic") or "").strip().lower() == str(chosen_topic).strip().lower()]
    if not matches:
        st.session_state["_threads_source"] = source
        st.session_state["_threads_missing_topic"] = chosen_topic
        return None

    picked = random.choice(matches)
    picked = dict(picked)
    picked["thread_id"] = str(uuid.uuid4())
    picked["source"] = source

    st.session_state.selected_thread = picked
    st.session_state.exp_view_start_ts = None  # reset timer when a new thread is selected
    st.session_state.thread_read_elapsed_seconds = None
    return picked


# =============================================================================
# SURVEY HELPERS
# =============================================================================
def likert8(question: str, key: str) -> Optional[int]:
    st.markdown(f"**{question}**")
    return st.radio(
        "",
        options=[1, 2, 3, 4, 5, 6, 7, 8],
        index=None,
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )


def blank(x: Any) -> bool:
    return x is None or str(x).strip() == ""


# =============================================================================
# SESSION STATE DEFAULTS
# =============================================================================
st.session_state.setdefault("stage", "consent")  # consent -> pid -> practice -> topic_select -> experiment(survey1+2) -> done / failed_attention
st.session_state.setdefault("session_id", str(uuid.uuid4()))
st.session_state.setdefault("start_time", utc_now_iso())
st.session_state.setdefault("prolific_id", None)

st.session_state.setdefault("practice_attempts", 0)
st.session_state.setdefault("attention_attempt_history", [])

st.session_state.setdefault("assigned_category", None)
st.session_state.setdefault("chosen_subtopic", None)

st.session_state.setdefault("selected_thread", None)
st.session_state.setdefault("exp_view_start_ts", None)
st.session_state.setdefault("thread_read_elapsed_seconds", None)

st.session_state.setdefault("survey_step", 1)
st.session_state.setdefault("survey_answers", {})

st.session_state.setdefault("scroll_top_next", False)

# =============================================================================
# PAGES
# =============================================================================
def consent_page():
    st.title("Study Information and Consent")

    st.markdown(
        """
**Study Overview and Consent**

You are invited to participate in a research study about **how entrepreneurs interact on social media**.  
You must be **18 years or older** to participate.

In this study, you will:
- Enter your Prolific ID,
- Answer two short attention-check questions,
- Select **one topic** that best matches something you have encountered recently,
- Read a short **online thread** (a post and a comment) in which an entrepreneur **shares** their experience,
- Answer questions about **how you would feel** if you were the entrepreneur who posted the thread and you had just read the comment.

The study will take approximately **5–8 minutes**.

Your participation is **voluntary**. You may stop participating at any time without penalty.
All responses are **anonymous**, and no identifying information will be collected or reported.
De-identified data may be shared with other researchers for academic purposes.

There are **no known risks** associated with this study and no direct benefits to you.
You will receive compensation **as described on Prolific** for completing the study.

If you have any questions about our research, please contact our team member Hongfei Li (Email: hongfei.li@cuhk.edu.hk) from CUHK.
"""
    )

    agree = st.checkbox("I am at least 18 years old and I agree to participate in this study.")

    st.session_state.setdefault("consent_start_ts", time.time())
    elapsed = int(time.time() - st.session_state.consent_start_ts)
    remaining = max(0, MIN_SECONDS_CONSENT - elapsed)

    st.caption(f"Please stay on this page for at least {MIN_SECONDS_CONSENT} seconds. Remaining: {remaining}s")

    if st.button("I agree and continue"):
        if remaining > 0:
            st.warning(f"Please wait {remaining}s before continuing.")
            return
        if not agree:
            st.warning("You must agree to participate before continuing.")
            return

        st.session_state.stage = "pid"
        st.session_state.scroll_top_next = True
        st.rerun()


def pid_page():
    render_banner()
    st.title("Welcome!")
    st.markdown("Please enter your **Prolific ID** to begin.")

    prefill = get_query_param("PROLIFIC_PID") or ""
    pid = st.text_input("Prolific ID", value=prefill)

    if st.button("Confirm"):
        pid_clean = (pid or "").strip()
        if not pid_clean:
            st.error("Please enter your Prolific ID.")
            return

        st.session_state.prolific_id = pid_clean
        log_event("session_start", payload={"pid": pid_clean, "session_id": st.session_state.session_id})
        st.session_state.stage = "practice"
        st.session_state.scroll_top_next = True
        st.rerun()


def practice_page():
    render_banner()
    st.title("PRACTICE QUESTIONS")

    st.markdown(
        "Before starting, please answer the practice questions below. "
        "These questions help ensure responses are attentive."
    )

    with st.form("practice_form", clear_on_submit=False):
        st.markdown("**What is the fifth word in the following sentence:**")
        st.markdown(f"> {ATTENTION_CHECK_1_SENTENCE}")
        att1 = st.radio("", ATTENTION_CHECK_1_OPTIONS, index=None, horizontal=True, label_visibility="collapsed")
        att2 = st.radio(
            "What is your favorite fruit? Please select Orange to show that you are paying attention to this question.",
            ATTENTION_CHECK_2_OPTIONS,
            index=None,
            horizontal=True,
        )
        submitted = st.form_submit_button("Continue")

    if not submitted:
        return

    if att1 is None or att2 is None:
        st.error("Please answer both questions before continuing.")
        return

    st.session_state.practice_attempts += 1
    attempt_n = st.session_state.practice_attempts

    pass1 = str(att1).strip().lower() == ATTENTION_CHECK_1_CORRECT
    pass2 = str(att2).strip() == ATTENTION_CHECK_2_CORRECT
    passed = pass1 and pass2

    log_event(
        "practice_questions",
        title=f"practice_attempt_{attempt_n}",
        payload={
            "q1_answer": att1,
            "q2_answer": att2,
            "pass_q1": pass1,
            "pass_q2": pass2,
            "passed": passed,
        },
    )
    st.session_state.attention_attempt_history.append(
        {
            "attempt": attempt_n,
            "q1_answer": att1,
            "q2_answer": att2,
            "pass_q1": pass1,
            "pass_q2": pass2,
            "passed": passed,
            "timestamp": utc_now_iso(),
        }
    )

    if passed:
        # Randomly assign to Business vs Worklife balance (once)
        if not st.session_state.get("assigned_category"):
            st.session_state.assigned_category = random.choice(list(TOPIC_GROUPS.keys()))
            log_event(
                "category_assigned",
                title=st.session_state.assigned_category,
                payload={"assigned_category": st.session_state.assigned_category},
            )

        st.session_state.stage = "topic_select"
        st.session_state.scroll_top_next = True
        st.rerun()
        return

    # Not passed
    if attempt_n < ATTENTION_MAX_ATTEMPTS:
        show_alert("Please read the questions carefully and try again.")
        st.warning("One or more answers were incorrect. Please read carefully and try again.")
        return

    # Second failure -> end
    log_event(
        "attention_failed",
        title="failed_twice",
        payload={"attempts": attempt_n, "q1_answer": att1, "q2_answer": att2},
    )
    st.session_state.stage = "failed_attention"
    st.session_state.scroll_top_next = True
    st.rerun()


def failed_attention_page():
    render_banner()
    st.title("Not qualified")
    st.error(
        "Really sorry, but you failed the attention check twice and are not qualified for this study. "
        "You may close this window now."
    )


def topic_select_page():
    render_banner()
    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()

    assigned = st.session_state.get("assigned_category")
    if assigned not in TOPIC_GROUPS:
        # Safety net: assign if somehow missing
        assigned = random.choice(list(TOPIC_GROUPS.keys()))
        st.session_state.assigned_category = assigned
        log_event("category_assigned", title=assigned, payload={"assigned_category": assigned})

    st.title("Topic selection")

    st.markdown(
        "To help you immerse in the scenario, please select the **one topic** that best matches something you have encountered recently."
    )
    st.markdown(f"**Assigned topic area:** {html.escape(assigned)}")

    threads, source = get_threads_data()
    st.session_state["_threads_source"] = source

    sub = st.radio("Select one topic (choose one):", TOPIC_GROUPS[assigned], index=None)

    # Optional: show a small hint if csv missing
    if not threads:
        st.info(
            f"⚠️ Topic CSV not loaded ({source}). "
            "For researchers: place the CSV next to this app as one of: "
            + ", ".join(DEFAULT_THREADS_CSV_CANDIDATES)
            + " or set TOPIC_CSV_PATH in Streamlit secrets."
        )
        uploaded = st.file_uploader("Upload topic CSV (researcher only)", type=["csv"])
        if uploaded is not None:
            st.session_state.uploaded_threads_csv_bytes = uploaded.read()
            st.success("CSV uploaded. You can proceed with topic selection.")
            st.rerun()

    if st.button("Continue"):
        if not sub:
            st.error("Please select one topic before continuing.")
            return

        st.session_state.chosen_subtopic = sub

        # reset any previous thread/survey state
        st.session_state.selected_thread = None
        st.session_state.exp_view_start_ts = None
        st.session_state.thread_read_elapsed_seconds = None
        st.session_state.survey_step = 1
        st.session_state.survey_answers = {}

        st.session_state.pop("_logged_thread_shown", None)

        log_event(
            "topic_selected",
            title=sub,
            payload={
                "assigned_category": assigned,
                "subtopic": sub,
                "threads_source": source,
            },
        )

        st.session_state.stage = "experiment"
        st.session_state.scroll_top_next = True
        st.rerun()


def survey_step1():
    st.markdown(
        """
Please imagine that you are the entrepreneur **who posted the thread** and that you have just read the online **comment**.  
Indicate how you would feel right now.

Please answer each item according to the following scale:  
**1 = Definitely False, 2 = Mostly False, 3 = Somewhat False, 4 = Slightly False, 5 = Slightly True, 6 = Somewhat True, 7 = Mostly True, 8 = Definitely True.**
"""
    )

    with st.form("survey_step1_form"):
        answers: Dict[str, Any] = {}

        st.markdown("**Hope**")
        hope_items = [
            "If I were the entrepreneur, this post would enable me to think of many ways to get out of the current difficulties in the business.",
            "If I were the entrepreneur, this post would enable me to energetically pursue my business goals.",
            "If I were the entrepreneur, this post would make me feel that there are many ways around any problem I am currently facing in my business.",
            "If I were the entrepreneur, this post would make me feel pretty successful in my business.",
            "If I were the entrepreneur, this post would enable me to think of many ways to reach my current business goals.",
            "If I were the entrepreneur, this post would make me feel that I am meeting the business goals I have set for myself.",
        ]
        for i, q in enumerate(hope_items, start=1):
            answers[f"hope_{i}"] = likert8(q, f"hope_{i}")

        st.divider()

        st.markdown("**Loneliness**")
        lonely_items = [
            "If I were the entrepreneur, this post would make me feel that I lack companionship.",
            "If I were the entrepreneur, this post would make me feel that there is no one I can turn to.",
            "If I were the entrepreneur, this post would make me feel like an outgoing person.",
            "If I were the entrepreneur, this post would make me feel left out.",
            "If I were the entrepreneur, this post would make me feel isolated from others.",
            "If I were the entrepreneur, this post would make me feel that I could find companionship when I want it.",
            "If I were the entrepreneur, this post would make me feel unhappy about being so withdrawn.",
            "If I were the entrepreneur, this post would make me feel that people are around me but not really with me.",
        ]
        for i, q in enumerate(lonely_items, start=1):
            answers[f"lonely_{i}"] = likert8(q, f"lonely_{i}")

        st.divider()

        st.markdown("**Perceived supportedness**")
        ps_items = [
            "This response made me feel understood.",
            "This response made me feel supported.",
            "This response made me feel supported about my situation.",
        ]
        for i, q in enumerate(ps_items, start=1):
            answers[f"supported_{i}"] = likert8(q, f"supported_{i}")

        st.divider()

        st.markdown("**Level of negativity of venting posts**")
        answers["vent_negativity"] = likert8(
            "To what extent does this post express frustrations and negative experiences?",
            "vent_negativity",
        )

        submitted = st.form_submit_button("Continue")

    if not submitted:
        return

    missing = [k for k, v in answers.items() if v is None]
    if missing:
        st.error("Please answer all questions before continuing.")
        return

    st.session_state.survey_answers["page1"] = dict(answers)

    log_event(
        "survey_page1_complete",
        title="feelings",
        payload={
            "answers": answers,
            "reverse_coded_items": ["lonely_3", "lonely_6"],
        },
    )

    st.session_state.survey_step = 2
    st.session_state.scroll_top_next = True
    st.rerun()


def survey_step2():
    st.markdown("Please answer the questions below.")

    with st.form("survey_step2_form"):
        mc_topic = st.radio(
            "**The post was mainly about:**",
            ["Work-life balance", "Business difficulty"],
            index=None,
            horizontal=True,
        )

        st.divider()

        birth_year = st.text_input("**What is your birth year?** (1960–2007)", placeholder="e.g., 1998")
        gender = st.selectbox(
            "**What is your gender?**",
            ["female", "male", "third gender", "transgender"],
            index=None,
            placeholder="Select…",
        )
        education = st.selectbox(
            "**What’s your highest level of formal education?**",
            [
                "High school degree or below",
                "Associated or technical degree",
                "Bachelor degree",
                "Master degree",
                "Doctorate degree",
            ],
            index=None,
            placeholder="Select…",
        )
        ent_years = st.text_input("**How many years of entrepreneurial experience do you have?** (0–50)", placeholder="e.g., 3")
        work_years = st.text_input("**How many years of work experience do you have?** (0–50)", placeholder="e.g., 10")

        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    missing_fields = []
    for label, val in [
        ("Manipulation check", mc_topic),
        ("Birth year", birth_year),
        ("Gender", gender),
        ("Education", education),
        ("Entrepreneurial years", ent_years),
        ("Work years", work_years),
    ]:
        if blank(val):
            missing_fields.append(label)
    if missing_fields:
        st.error("Please complete all required questions: " + ", ".join(missing_fields))
        return

    errs = []
    try:
        by = int(str(birth_year).strip())
        if by < 1960 or by > 2007:
            errs.append("Birth year must be 1960–2007")
    except Exception:
        errs.append("Birth year must be an integer")
    try:
        ey = int(str(ent_years).strip())
        if ey < 0 or ey > 50:
            errs.append("Entrepreneurial experience must be 0–50")
    except Exception:
        errs.append("Entrepreneurial experience must be an integer")
    try:
        wy = int(str(work_years).strip())
        if wy < 0 or wy > 50:
            errs.append("Work experience must be 0–50")
    except Exception:
        errs.append("Work experience must be an integer")

    if errs:
        for e in errs:
            st.error(e)
        return

    assigned_category = st.session_state.get("assigned_category")
    expected_mc_topic = "Business difficulty" if assigned_category == "Business" else "Work-life balance"
    mc_topic_correct = (mc_topic == expected_mc_topic)

    st.session_state.survey_answers["page2"] = {
        "manipulation_check_topic": mc_topic,
        "manipulation_check_expected": expected_mc_topic,
        "manipulation_check_correct": mc_topic_correct,
        "demographics": {
            "birth_year": by,
            "gender": gender,
            "education": education,
            "entrepreneurial_years": ey,
            "work_years": wy,
        },
    }

    final_payload = {
        "pid": st.session_state.get("prolific_id"),
        "session_id": st.session_state.get("session_id"),
        "assigned_category": assigned_category,
        "chosen_subtopic": st.session_state.get("chosen_subtopic"),
        "thread": st.session_state.get("selected_thread", {}),
        "attention": {
            "attempts": st.session_state.get("practice_attempts"),
            "history": st.session_state.get("attention_attempt_history", []),
        },
        "timing": {
            "thread_read_elapsed_seconds": st.session_state.get("thread_read_elapsed_seconds"),
            "min_required_seconds": MIN_SECONDS_THREAD,
        },
        "survey": st.session_state.get("survey_answers", {}),
    }

    log_event("survey_submitted", title="survey", payload=final_payload)

    st.session_state.stage = "done"
    st.session_state.scroll_top_next = True
    st.rerun()


def experiment_page():
    """
    Thread + Comment + Survey are presented on the same page (in two survey steps),
    so participants can revisit the comment while answering.
    """
    render_banner()
    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()

    subtopic = st.session_state.get("chosen_subtopic")
    if not subtopic:
        st.error("No topic selected. Please go back and select a topic.")
        if st.button("Back to topic selection"):
            st.session_state.stage = "topic_select"
            st.session_state.scroll_top_next = True
            st.rerun()
        return

    thread = ensure_thread_selected()
    if not thread:
        source = st.session_state.get("_threads_source", "unknown")
        missing = st.session_state.get("_threads_missing_topic")
        if missing:
            st.error(f"No thread found in CSV for topic: {missing}")
        else:
            st.error(f"Could not load topic threads CSV ({source}).")
        if st.button("Back to topic selection"):
            st.session_state.stage = "topic_select"
            st.session_state.scroll_top_next = True
            st.rerun()
        return

    # Log once when the thread is shown
    if not st.session_state.get("_logged_thread_shown"):
        log_event(
            "thread_shown",
            title=thread.get("thread_id", ""),
            payload={
                "assigned_category": st.session_state.get("assigned_category"),
                "chosen_subtopic": subtopic,
                "thread_id": thread.get("thread_id"),
                "link_id": thread.get("link_id"),
                "thread_source": thread.get("source"),
                "post_title": thread.get("title"),
            },
        )
        st.session_state["_logged_thread_shown"] = True

    # Prompt line with emphasis
    st.markdown(
        f"""
<div style="font-weight:800; font-size:1.05rem; margin-bottom:8px;">
  Below, you will read a thread posted by
  <span class="emph">{html.escape(POSTED_BY_NAME)}</span>
  on social media about
  <span class="emph">{html.escape(str(subtopic))}</span>.
</div>
<div class="muted" style="margin-bottom:12px;">
  <span style="font-weight:800;">Task:</span> Please read the thread and the comment below. After reading, answer the questions that follow.
</div>
""",
        unsafe_allow_html=True,
    )

    render_post_meta()
    render_post_content(thread.get("title", ""), thread.get("body", ""))

    st.divider()

    st.markdown('<div class="comment-label">Comment</div>', unsafe_allow_html=True)
    render_comment(thread.get("comment", ""))

    st.markdown("---")

    # Timing gate (20s) with a live countdown (enforced only once).
    if st.session_state.exp_view_start_ts is None:
        st.session_state.exp_view_start_ts = time.time()

    if st.session_state.thread_read_elapsed_seconds is None:
        countdown = st.empty()
        while True:
            elapsed = int(time.time() - st.session_state.exp_view_start_ts)
            remaining = max(0, MIN_SECONDS_THREAD - elapsed)
            if remaining <= 0:
                countdown.caption("Minimum reading time completed. You may now answer the survey questions below.")
                st.session_state.thread_read_elapsed_seconds = elapsed
                log_event(
                    "thread_read_complete",
                    title=thread.get("thread_id", ""),
                    payload={
                        "elapsed_seconds": elapsed,
                        "min_required": MIN_SECONDS_THREAD,
                        "chosen_subtopic": subtopic,
                    },
                )
                break
            countdown.caption(
                f"Please stay on this page for at least {MIN_SECONDS_THREAD} seconds. Remaining: {remaining}s"
            )
            time.sleep(1)

        st.markdown("---")
    # Survey steps (thread+comment remain visible above)
    st.markdown("**Survey**")
    if st.session_state.survey_step == 1:
        survey_step1()
    else:
        survey_step2()


def done_page():
    render_banner()
    st.title("Thank you!")
    st.success("You have completed the study. You may close this window now.")


# =============================================================================
# MAIN ROUTER
# =============================================================================
def main():
    stage = st.session_state.stage

    # Optional debug box for researchers
    if st.secrets.get("SHOW_DEBUG", False) if hasattr(st, "secrets") else False:
        render_debug_box()

    if stage == "consent":
        consent_page()
        return
    if stage == "pid":
        pid_page()
        return
    if stage == "practice":
        practice_page()
        return
    if stage == "failed_attention":
        failed_attention_page()
        return
    if stage == "topic_select":
        topic_select_page()
        return
    if stage == "experiment":
        experiment_page()
        return
    done_page()


if __name__ == "__main__":
    main()
