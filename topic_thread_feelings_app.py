
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
EXPERIMENT_VARIANT = "TOPIC_THREAD_FEELINGS_V1"

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

# CSV source (3 columns recommended: topic, post, comment)
# - topic: must match one of the subtopics above (e.g., "Financing")
# - post: first line treated as title; remaining lines treated as body
# - comment: comment text
DEFAULT_THREADS_CSV = "topic_threads.csv"

# Google Sheet target
DEFAULT_SPREADSHEET_NAME = "ETP-TOPIC-FEELINGS"
GSHEET_KEYS = ["id", "start", "variant", "timestamp", "type", "title", "url"]

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
  padding: 0 4px;
  border-radius: 4px;
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
        qp = st.experimental_get_query_params()
        vals = qp.get(name, [])
        return vals[0] if vals else None


def scroll_to_top_once() -> None:
    components.html(
        """
        <script>
        try { document.activeElement && document.activeElement.blur(); } catch(e) {}
        const doc = window.parent.document;
        const main = doc.querySelector('section.main');
        if (main) { main.scrollTo({ top: 0, left: 0, behavior: 'instant' }); }
        else { window.parent.scrollTo(0, 0); }
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
    if not local_path.exists():
        return ""
    suffix = local_path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        suffix, "image/png"
    )
    b64 = base64.b64encode(local_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


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
    with st.expander("Debug (Google Sheet status)", expanded=False):
        err = st.session_state.get("_gsheet_error")
        if err:
            st.error(err)
        else:
            st.success("No Google Sheet error recorded in this session.")
        st.caption(
            "If your Google Sheet isn’t updating, the most common cause is: "
            "the spreadsheet is not shared with the service account email in your credentials."
        )


# =============================================================================
# REDDIT-LIKE UI
# =============================================================================
APP_DIR = Path(__file__).parent
REDDIT_LOGO_PATH = APP_DIR / "reddit_logo.png"
AVATAR_PATH = APP_DIR / "avatar.jpg"


def render_banner():
    logo_uri = to_data_uri(REDDIT_LOGO_PATH)
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;width:100%;padding:16px 0 24px 0;">
            <img src="{logo_uri}" style="width:36px;height:36px;">
            <span style="font-family:Roboto,Arial,sans-serif;font-size:var(--banner-font-size);line-height:1.1;font-weight:700;color:#FF4500;">reddit</span>
        </div>
        <hr style="margin:0 0 20px 0;">
        """,
        unsafe_allow_html=True,
    )


def render_post_meta():
    avatar_uri = to_data_uri(AVATAR_PATH)
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <img src="{avatar_uri}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">
            <div style="line-height:1.1;">
                <div style="font-weight:700;">{SUBREDDIT} &middot; {POST_DAYS_AGO} days ago</div>
                <div style="color:#6e6e6e;font-size:0.95rem;">{AUTHOR_USERNAME}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_comment(comment_text: str):
    # Simple neutral avatar (first letter)
    letter = (COMMENTER_USERNAME[:1] or "?").upper()
    safe_text = html.escape(comment_text or "").replace("\n", "<br>")

    st.markdown(
        f"""
        <div style="display:flex; gap:10px; margin-top:8px;">
            <div style="width:34px;height:34px;border-radius:50%;background:#e9ecef;
                        display:flex;align-items:center;justify-content:center;font-weight:800;">
                {letter}
            </div>
            <div style="flex:1;">
                <div style="font-size:0.95rem; color:#6e6e6e;">
                    <span style="font-weight:800; color:#111;">{COMMENTER_USERNAME}</span>
                    &nbsp;&middot;&nbsp; {COMMENT_DAYS_AGO} days ago
                </div>
                <div style="margin-top:4px; font-size:1rem; line-height:1.45; color:#111;">
                    {safe_text}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# CSV LOADER
# =============================================================================
def _pick_column(keys: List[str], candidates: List[str]) -> Optional[str]:
    lower_map = {k.lower().strip(): k for k in keys}
    for c in candidates:
        if c.lower().strip() in lower_map:
            return lower_map[c.lower().strip()]
    return None


def load_threads_csv(path: str, *, uploaded_bytes: Optional[bytes] = None) -> List[Dict[str, str]]:
    """
    Supports:
      - Named columns (recommended): topic, post, comment
      - Alternative names: Topic/Post/Comment; post_md; comment_md; etc.
      - If unnamed/unknown but exactly 3 columns: assumes topic, post, comment by order.
    The 'post' field: first line -> title; remainder -> body.
    """
    if uploaded_bytes is not None:
        text = uploaded_bytes.decode("gb18030")
        f = text.splitlines()
        reader = csv.reader(f)
        rows = list(reader)
        if not rows:
            return []
        headers = rows[0]
        data_rows = rows[1:]
        # Build DictReader-like structure
        dict_rows = [dict(zip(headers, r)) for r in data_rows if any(cell.strip() for cell in r)]
        keys = headers
    else:
        with open(path, "r", encoding="gb18030", newline="") as fh:
            dr = csv.DictReader(fh)
            dict_rows = list(dr)
            keys = dr.fieldnames or []

    if not dict_rows:
        return []

    # detect columns
    topic_col = _pick_column(keys, ["topic", "subtopic", "topic_name"])
    post_col = _pick_column(keys, ["post", "thread", "post_md", "post_text", "postcontent"])
    comment_col = _pick_column(keys, ["comment", "reply", "comment_md", "comment_text", "response"])

    # fallback: if exactly 3 columns and any of above missing
    if (topic_col is None or post_col is None or comment_col is None) and len(keys) == 3:
        topic_col = topic_col or keys[0]
        post_col = post_col or keys[1]
        comment_col = comment_col or keys[2]

    # optional split columns
    title_col = _pick_column(keys, ["post_title", "title"])
    body_col = _pick_column(keys, ["post_body", "body"])

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

        threads.append(
            {
                "topic": topic,
                "title": title,
                "body": body,
                "comment": comment,
            }
        )

    return threads


def get_threads_data() -> Tuple[List[Dict[str, str]], str]:
    """
    Returns (threads, source_description).
    Tries:
      1) session_state['uploaded_threads_csv_bytes'] if present
      2) file path from secrets/env/default in same directory
    """
    # 1) uploaded
    uploaded = st.session_state.get("uploaded_threads_csv_bytes")
    if uploaded:
        return load_threads_csv("uploaded", uploaded_bytes=uploaded), "uploaded CSV"

    # 2) file path
    csv_path = (
        st.secrets.get("TOPIC_CSV_PATH", None)
        if hasattr(st, "secrets")
        else None
    )
    csv_path = csv_path or os.getenv("TOPIC_CSV_PATH") or DEFAULT_THREADS_CSV
    abs_path = Path(csv_path)
    if not abs_path.is_absolute():
        abs_path = (APP_DIR / csv_path).resolve()

    if abs_path.exists():
        return load_threads_csv(str(abs_path)), str(abs_path)

    return [], f"missing ({abs_path})"


def ensure_thread_selected() -> Optional[Dict[str, str]]:
    """Pick (and freeze) a single thread record based on selected topic."""
    chosen_topic = st.session_state.get("chosen_subtopic")
    if not chosen_topic:
        return None

    # keep existing selection stable
    current = st.session_state.get("selected_thread")
    if current and current.get("topic") == chosen_topic:
        return current

    threads, source = get_threads_data()
    if not threads:
        st.session_state["_threads_source"] = source
        return None

    # filter
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
    return picked


# =============================================================================
# SURVEY HELPERS
# =============================================================================
def likert8(question: str, key: str) -> Optional[int]:
    st.markdown(f"**{question}**")
    return st.radio(
        "",
        options=[1, 2, 3, 4, 5, 6, 7, 8],
        horizontal=True,
        index=None,
        key=key,
        label_visibility="collapsed",
    )


def blank(x: Any) -> bool:
    return x is None or (isinstance(x, str) and x.strip() == "")


# =============================================================================
# SESSION STATE DEFAULTS
# =============================================================================
st.session_state.setdefault("stage", "consent")  # consent -> pid -> practice -> topic_select -> experiment -> survey -> done / failed_attention
st.session_state.setdefault("session_id", str(uuid.uuid4()))
st.session_state.setdefault("start_time", utc_now_iso())
st.session_state.setdefault("prolific_id", None)

st.session_state.setdefault("practice_attempts", 0)
st.session_state.setdefault("attention_attempt_history", [])
st.session_state.setdefault("chosen_category", None)
st.session_state.setdefault("chosen_subtopic", None)
st.session_state.setdefault("selected_thread", None)
st.session_state.setdefault("exp_view_start_ts", None)
st.session_state.setdefault("thread_read_elapsed_seconds", None)

st.session_state.setdefault("survey_step", 1)
st.session_state.setdefault("survey_answers", {})

# =============================================================================
# PAGES
# =============================================================================
def consent_page():
    st.title("Study Information and Consent")

    st.markdown(
        """
**Study Overview and Consent**

You are invited to participate in a research study about **entrepreneurial experiences and online interactions**.
You must be **18 years or older** to participate.

In this study, you will:
- Enter your Prolific ID,
- Answer two short attention-check questions,
- Select **one topic** that best matches something you have encountered recently,
- Read a short **online thread** (a post and a comment),
- Answer questions about **how you would feel** if you were the entrepreneur who posted the thread.

The study will take approximately **5–8 minutes**.

Your participation is **voluntary**. You may stop participating at any time without penalty.
All responses are **anonymous**, and no identifying information will be collected or reported.
De-identified data may be shared with other researchers for academic purposes.

There are **no known risks** associated with this study and no direct benefits to you.
You will receive compensation **as described on Prolific** for completing the study.

For scientific reasons, full details about the research purpose cannot be provided at this time.
You will be **fully debriefed** after completing the study.

If you have any questions about our research, please contact our team member Hongfei Li (Email: hongfei.li@cuhk.edu.hk) from CUHK.
"""
    )

    agree = st.checkbox("I am at least 18 years old and I agree to participate in this study.")

    st.session_state.setdefault("consent_start_ts", time.time())
    elapsed = int(time.time() - st.session_state.consent_start_ts)
    remaining = max(0, MIN_SECONDS_CONSENT - elapsed)

    st.caption(
        f"Please stay on this page for at least {MIN_SECONDS_CONSENT} seconds. Remaining: {remaining}s"
    )

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

    # Form: submit together
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

    # Require answers before counting as an attempt
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
    # Keep an in-session copy (so the final submission has everything in one payload)
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
        "Really sorry, but you failed the attention check twice and are not qualified for this study."
    )
    st.caption("You may now close this tab.")
    # render_debug_box()


def topic_select_page():
    render_banner()
    st.title("Topic selection")

    st.markdown(
        "To help you immerse in the scenario, please select the **one topic** that best matches something you have encountered recently."
    )

    # Load availability info (optional)
    threads, source = get_threads_data()
    st.session_state["_threads_source"] = source

    cat = st.radio("Select a broad area:", list(TOPIC_GROUPS.keys()), index=None, horizontal=True)

    sub = None
    if cat:
        sub = st.radio("Select one topic (choose one):", TOPIC_GROUPS[cat], index=None)

    # Optional: show a small hint if csv missing
    if not threads:
        st.info(
            f"⚠️ Topic CSV not loaded ({source}). "
            "For researchers: place the CSV next to this app as 'topic_threads.csv' "
            "or set TOPIC_CSV_PATH in Streamlit secrets."
        )
        # Only show uploader if missing (so participants won't see it normally)
        uploaded = st.file_uploader("Upload topic CSV (researcher only)", type=["csv"])
        if uploaded is not None:
            st.session_state.uploaded_threads_csv_bytes = uploaded.read()
            st.success("CSV uploaded. You can proceed with topic selection.")
            st.rerun()

    if st.button("Continue"):
        if not cat or not sub:
            st.error("Please select one topic before continuing.")
            return

        st.session_state.chosen_category = cat
        st.session_state.chosen_subtopic = sub

        # reset any previous thread selection
        st.session_state.selected_thread = None
        st.session_state.exp_view_start_ts = None

        # Reset logging flags if participant goes back and re-selects a topic
        st.session_state.pop("_logged_thread_shown", None)

        log_event(
            "topic_selected",
            title=sub,
            payload={
                "category": cat,
                "subtopic": sub,
                "threads_source": source,
            },
        )

        st.session_state.stage = "experiment"
        st.session_state.scroll_top_next = True
        st.rerun()


def experiment_page():
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
                "chosen_category": st.session_state.get("chosen_category"),
                "chosen_subtopic": subtopic,
                "thread_id": thread.get("thread_id"),
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
""",
        unsafe_allow_html=True,
    )

    render_post_meta()

    # Post content
    st.title(thread.get("title", ""))
    if thread.get("body"):
        st.markdown(thread.get("body", ""))

    st.divider()

    # Comment content (mimic a reply)
    st.markdown("**Comment**")
    render_comment(thread.get("comment", ""))

    st.markdown("---")

    # Timing gate (20s)
    if st.session_state.exp_view_start_ts is None:
        st.session_state.exp_view_start_ts = time.time()

    elapsed = int(time.time() - st.session_state.exp_view_start_ts)
    remaining = max(0, MIN_SECONDS_THREAD - elapsed)
    st.caption(f"Please stay on this page for at least {MIN_SECONDS_THREAD} seconds. Remaining: {remaining}s")

    if st.button("Continue to survey"):
        if remaining > 0:
            st.warning(f"Please wait {remaining}s before continuing.")
            return

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

        st.session_state.stage = "survey"
        st.session_state.survey_step = 1
        st.session_state.scroll_top_next = True
        st.rerun()


def survey_page():
    render_banner()
    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()

    step = int(st.session_state.get("survey_step", 1))
    st.title(f"Survey ({step}/2)")
    st.caption("Please answer all questions.")

    if step == 1:
        survey_step1()
    else:
        survey_step2()


def survey_step1():
    # Instructions
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

        # st.markdown("**Hope**")
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

        # st.markdown("**Loneliness**")
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

        # st.markdown("**Perceived supportedness**")
        ps_items = [
            "This response made me feel understood.",
            "This response made me feel supported.",
            "This response made me feel supported about my situation.",
        ]
        for i, q in enumerate(ps_items, start=1):
            answers[f"supported_{i}"] = likert8(q, f"supported_{i}")

        st.divider()

        # st.markdown("**Level of negativity of venting posts**")
        answers["vent_negativity"] = likert8(
            "To what extent does this post express frustrations and negative experiences?",
            "vent_negativity",
        )

        submitted = st.form_submit_button("Continue")

    if not submitted:
        return

    # Validate
    missing = [k for k, v in answers.items() if v is None]
    if missing:
        st.error("Please answer all questions before continuing.")
        return

    # Store + log
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
        # Manipulation check
        mc_topic = st.radio(
            "**The post was mainly about:**",
            ["Work-life balance", "Business difficulty"],
            index=None,
            horizontal=True,
        )

        st.divider()

        # Demographics
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

    # Validate required
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

    # Validate numeric
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

    # Compute manipulation-check correctness (based on the topic category the participant selected)
    chosen_category = st.session_state.get("chosen_category")
    expected_mc_topic = "Business difficulty" if chosen_category == "Business" else "Work-life balance"
    mc_topic_correct = (mc_topic == expected_mc_topic)

    # Store
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

    # Build final payload
    final_payload = {
        "pid": st.session_state.get("prolific_id"),
        "session_id": st.session_state.get("session_id"),
        "chosen_category": st.session_state.get("chosen_category"),
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


def done_page():
    render_banner()
    st.title("Finished")
    st.success("Thanks — your responses have been recorded.")
    st.caption("You may now close this tab.")
    # render_debug_box()


# =============================================================================
# ROUTER
# =============================================================================
def main():
    stage = st.session_state.stage

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
    if stage == "survey":
        survey_page()
        return
    done_page()


if __name__ == "__main__":
    main()
