# file: female_wlb.py
# Female WLB condition (single-app version) — matches Female BD flow & survey
#
# What you asked for in the latest message:
#   ✅ One Google Sheet (sheet1) for everything
#   ✅ PID enter page (like your example)
#   ✅ Record start time + timestamps
#   ✅ Reduce logging noise: by default ONLY log
#        - session_start
#        - comment_posted
#        - survey_submitted
#      (you can switch on vote logging via LOG_VOTES = True)
#   ✅ Use the SAME function names/pattern as your example:
#        - get_credentials_from_secrets()
#        - save_to_gsheet(data)
#      with: client.open("SeEn Ads").sheet1.append_row(...)
#   ✅ Local testing friendly: if Google Sheets fails, ALWAYS save to
#      fallback_event_log.csv (UTF-8) and show the error in a small
#      “Debug” expander.

import base64
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

import gspread
from oauth2client.service_account import ServiceAccountCredentials
# Prefer oauth2client (matches your example). If not available, fall back.
# try:
#     from oauth2client.service_account import ServiceAccountCredentials  # type: ignore
#     _USE_OAUTH2CLIENT = True
# except Exception:  # pragma: no cover
#     _USE_OAUTH2CLIENT = False
#     from google.oauth2.service_account import Credentials  # type: ignore


# =============================================================================
# EXPERIMENT SETTINGS (Female WLB)
# =============================================================================
CONDITION = "F_WLB"

SUBREDDIT = "r/business"
DAYS_AGO = 7
AUTHOR_USERNAME = "HiddenBadger74"
POSTED_BY_NAME = "Maria"

POST_TITLE = "My husband told me this on my birthday (yesterday) and I think – I need to improve my work-life balance."
POST_BODY_MD = """
My husband told me this on my birthday (yesterday) and I think – I need to improve my work-life balance. A little bit of context. My husband and son had each bought presents for me about 2 weeks prior to my birthday and placed it around my home office. I use the office daily and did not even notice the gifts. Looking back now, they tried hinting and drawing my attention to the presents but as you guys know I was blinded by work.

My son got tired of the cat and mouse game and pointed the gifts out on my birthday. While opening the gift, my husband said you are chasing the things you want and fail to enjoy the things you have. He is right (he always is :) The funny part is that the gift he offered me was going to be my December bonus for achieving my quarterly goals.

Lesson learned: over the next year I want to structure some time to enjoy what I have. Starting with looking around my home office every time I use it. I don’t want to miss an early bonus again. :) My birthday wish for all of us is to find the balance between chasing our goals and enjoying the ones we have already achieved.
""".strip()


TOPIC_LABEL = "work-life balance difficulties"
PRONOUN_POSSESSIVE = "her"
DEFAULT_SCORE = 5

# --- logging controls (reduce "too many logs") ---
LOG_VOTES = False  # set True if you also want vote events

st.session_state.setdefault("stage", "consent")

# =============================================================================
# SURVEY CONTENT
# =============================================================================
ATTENTION_CHECK_1_SENTENCE = "Bobby is very happy because he is going to the movies."
ATTENTION_CHECK_1_OPTIONS = ["very", "happy", "going", "because", "movies", "is", "the"]
ATTENTION_CHECK_1_CORRECT = "because"

ATTENTION_CHECK_2_OPTIONS = ["Grape", "Apple", "Pear", "Orange", "Strawberry"]
ATTENTION_CHECK_2_CORRECT = "Orange"

ONLINE_SITES = ["Facebook", "Instagram", "Twitter", "YouTube", "Pinterest", "Reddit", "LinkedIn", "WhatsApp"]
ONLINE_SCALE = ["Never", "Rarely", "Sometimes", "Often", "Always"]

# =============================================================================
# STREAMLIT PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="Reddit-style Study (F_WLB)", page_icon="🧪", layout="centered")

st.markdown(
    """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header [data-testid="stToolbar"] {display: none !important;}
header [data-testid="stToolbarActions"] {display: none !important;}
.emph { background-color: #fff3cd; padding: 0 4px; border-radius: 4px; text-decoration: underline; font-weight: 700; }
</style>
""",
    unsafe_allow_html=True,
)

import streamlit.components.v1 as components

# ===== Survey helpers =====
LIKERT_1_7 = [1, 2, 3, 4, 5, 6, 7]

def likert7_row(statement: str, key: str):
    """1–7 Likert row with no default selection."""
    return st.radio(
        statement,
        options=LIKERT_1_7,
        index=None,          # required (no pre-selection)
        horizontal=True,
        key=key,
    )

def _is_blank(x):
    return x is None or (isinstance(x, str) and x.strip() == "")

# ===== New scales (1–7) =====
IDENTITY_THREAT_ITEMS = [
    "This post makes me feel that there is a negative value attached to my identity as an entrepreneur.",
    "This post makes me feel that being an entrepreneur is viewed less positively.",
    "This interaction makes me feel that the value of my entrepreneurial identity is being diminished.",
    "This interaction makes me feel that others might see my entrepreneurial identity as less legitimate.",
]

IDENTITY_VERIFICATION_ITEMS = [
    "This post makes me feel more confident in my identity as an entrepreneur.",
    "This interaction strengthens my sense of value in my role as an entrepreneur.",
    "After this interaction, I feel my entrepreneurial identity is positively reinforced.",
    "This post makes me feel recognized as a legitimate business owner.",
]

ENTREPRENEUR_ID_SALIENCE_ITEMS = [
    "Being an entrepreneur is an important part of who I am.",
    "I would feel a great sense of loss if I were forced to give up my entrepreneurial role.",
    "I have very clear feelings about being an entrepreneur.",
    "For me, being an entrepreneur is more than just a job; it is a vital part of my life.",
    "I strongly identify with being an entrepreneur.",
]

GENDER_ID_SALIENCE_ITEMS = [
    "I would feel like a significant part of me was missing if I could no longer identify with my gender.",
    "My gender is an important part of my overall sense of self.",
    "I have a very clear and defined sense of what my gender means to me.",
    "My gender is a vital lens through which I experience and navigate my life.",
    "I feel a strong sense of connection to the shared experiences associated with my gender.",
]

def scroll_to_top_once():
    components.html(
        """
        <script>
        // Blur whatever has focus (often the Continue button)
        try { document.activeElement && document.activeElement.blur(); } catch(e) {}

        // Streamlit main scroll container is usually section.main
        const doc = window.parent.document;
        const main = doc.querySelector('section.main');
        if (main) {
            main.scrollTo({ top: 0, left: 0, behavior: 'instant' });
        } else {
            window.parent.scrollTo(0, 0);
        }
        </script>
        """,
        height=0,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_query_param(name: str) -> Optional[str]:
    try:
        v = st.query_params.get(name)
        if isinstance(v, list):
            return v[0] if v else None
        return v
    except Exception:
        qp = st.experimental_get_query_params()
        vals = qp.get(name, [])
        return vals[0] if vals else None


def to_data_uri(local_path: Path) -> str:
    if not local_path.exists():
        return ""
    suffix = local_path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix,
                                                                                                         "image/png")
    b64 = base64.b64encode(local_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# =============================================================================
# GOOGLE SHEET LOGGING (same pattern / same function names as your example)
# =============================================================================
GSHEET_KEYS = ["id", "start", "variant", "timestamp", "type", "title", "url"]
MIN_SECONDS = 10


def get_credentials_from_secrets():
    # 还原成 dict
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return creds_dict


@st.cache_resource(show_spinner=False)
def _get_sheet1():
    """Connect once and keep the handle."""
    # scopes
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds_dict = get_credentials_from_secrets()

    if _USE_OAUTH2CLIENT:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
    else:
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

    # spreadsheet name (defaults to your example)
    spreadsheet_name = (
        st.secrets.get("SPREADSHEET_NAME", None)
        if hasattr(st, "secrets")
        else None
    )
    spreadsheet_name = spreadsheet_name or os.getenv("SPREADSHEET_NAME") or "SeEn Ads"

    sh = client.open(spreadsheet_name)
    ws = sh.sheet1

    # ensure header row exists
    first_row = ws.row_values(1)
    if not first_row:
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


# def save_to_gsheet(data: Dict[str, Any]) -> str:
#     """Append to Google Sheet with retries. If it fails, write to local CSV.
#
#     Returns "" (empty string) to match the style of your example.
#     """
#     data = dict(data)
#     data.setdefault("variant", CONDITION)
#
#     row = [data.get(k, "") for k in GSHEET_KEYS]
#
#     # Always keep a local backup too (so you have 2 copies: Google + local)
#     _append_local(row)
#
#     try:
#         ws = _get_sheet1()
#     except Exception as e:
#         st.session_state["_gsheet_error"] = f"Init error: {e}"
#         return ""
#
#     for i in range(3):
#         try:
#             ws.append_row(row)
#             return ""
#         except Exception as e:
#             st.session_state["_gsheet_error"] = f"Append error: {e}"
#             time.sleep(0.5)
#
#     return ""
def save_to_gsheet(data):
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        get_credentials_from_secrets(), scope
    )
    client = gspread.authorize(creds)

    sheet = client.open("ETP-FEMALE-WLB").sheet1
    sheet.append_row([
        data.get("id", ""),
        data.get("start", ""),
        data.get("variant", ""),
        data.get("timestamp", ""),
        data.get("type", ""),
        data.get("title", ""),
        data.get("url", "")
    ])


def log_event(event_type: str, *, title: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
    """One unified logger. 'url' column stores JSON payload."""
    pid = st.session_state.get("prolific_id") or ""
    start = st.session_state.get("start_time") or ""
    save_to_gsheet(
        {
            "id": pid,
            "start": start,
            "variant": CONDITION,
            "timestamp": utc_now_iso(),
            "type": event_type,
            "title": title,
            "url": json.dumps(payload or {}, ensure_ascii=False),
        }
    )


# =============================================================================
# REDDIT-LIKE UI (banner + meta + compact vote)
# =============================================================================
APP_DIR = Path(__file__).parent
REDDIT_LOGO_PATH = APP_DIR / "reddit_logo.png"
AVATAR_PATH = APP_DIR / "avatar.jpg"


def render_banner():
    logo_uri = to_data_uri(REDDIT_LOGO_PATH)
    st.markdown(
        f"""
        <style>:root {{ --banner-font-size: 2rem; }}</style>
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
                <div style="font-weight:700;">{SUBREDDIT} &middot; {DAYS_AGO} days ago</div>
                <div style="color:#6e6e6e;font-size:0.95rem;">{AUTHOR_USERNAME}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


PALETTE = {
    "neutral_bg": "#ECEFF1",
    "neutral_fg": "#000000",
    "up_bg": "#FF4500",
    "down_bg": "#6E4AFF",
    "active_fg": "#FFFFFF",
}


def inject_vote_css(user_vote: int):
    up_bg = PALETTE["up_bg"] if user_vote == 1 else PALETTE["neutral_bg"]
    down_bg = PALETTE["down_bg"] if user_vote == -1 else PALETTE["neutral_bg"]
    up_fg = PALETTE["active_fg"] if user_vote == 1 else PALETTE["neutral_fg"]
    down_fg = PALETTE["active_fg"] if user_vote == -1 else PALETTE["neutral_fg"]
    score_c = up_bg if user_vote == 1 else (down_bg if user_vote == -1 else PALETTE["neutral_fg"])

    st.markdown(
        f"""
        <style>
        div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] {{ column-gap: 0 !important; }}
        div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{ padding: 0 !important; margin: 0 !important; }}
        div:has(> #vote-row-anchor) button {{ min-width: auto !important; }}

        div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(1) button {{
            border-radius: 9999px !important; padding: 4px 10px !important; border: none !important;
            background: {up_bg} !important; color: {up_fg} !important;
        }}
        div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(3) button {{
            border-radius: 9999px !important; padding: 4px 10px !important; border: none !important;
            background: {down_bg} !important; color: {down_fg} !important;
        }}
        span.vote-score {{ font-weight: 600; color: {score_c}; padding: 0 2px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SESSION STATE
# =============================================================================
st.session_state.setdefault("stage", "pid")  # pid -> experiment -> survey -> done
st.session_state.setdefault("session_id", str(uuid.uuid4()))
st.session_state.setdefault("start_time", utc_now_iso())
st.session_state.setdefault("prolific_id", None)

# st.session_state.setdefault("vote_count", DEFAULT_SCORE)
# st.session_state.setdefault("user_vote", 0)
st.session_state.setdefault("comments", [])  # list[(ts, txt)]


def render_debug_box():
    """Small optional panel to see why Google didn’t update."""
    with st.expander("Debug (Google Sheet status)", expanded=False):
        err = st.session_state.get("_gsheet_error")
        if err:
            st.error(err)
        else:
            st.success("No Google Sheet error recorded in this session.")

        st.caption(
            "If your Google Sheet isn’t updating, the #1 cause is: the sheet is not shared with the service account email.")

        if st.button("Test Google Sheet write"):
            log_event("debug_test", title="hello", payload={"ts": utc_now_iso()})
            st.info("Wrote a test row (also saved locally). Refresh your Google Sheet.")


def render_consent_page():
    st.title("Study Information and Consent")

    st.markdown("""
    **Study Overview and Consent**

    You are invited to participate in a research study about **how entrepreneurs interact on social media**.
    You must be **18 years or older** to participate.

    In this study, you will read a short post from a Reddit discussion thread in which an entrepreneur shares their experience
    (e.g., business challenges or work–life balance issues). After reading the post, you will be asked
    to **write a brief comment as if replying in the thread** and then **answer several questions** about your reactions.

    The study will take approximately **3–5 minutes**. There will be **no follow-up questionnaire**.

    Your participation is **voluntary**. You may stop participating at any time without penalty.
    All responses are **anonymous**, and no identifying information will be collected or reported.
    De-identified data may be shared with other researchers for academic purposes.

    There are **no known risks** associated with this study and no direct benefits to you.
    You will receive **$0.50** for completing the study.

    For scientific reasons, full details about the research purpose cannot be provided at this time.
    You will be **fully debriefed** after completing the study.

    If you have any questions about our research, please contact our team member Hongfei Li (Email: hongfei.li@cuhk.edu.hk) from CUHK.
    """)

    agree = st.checkbox("I am at least 18 years old and I agree to participate in this study.")

    st.session_state.setdefault("instr_start_ts", time.time())

    # elapsed = int(time.time() - st.session_state.instr_start_ts)
    # remaining = max(0, MIN_SECONDS - elapsed)

    st.session_state.setdefault("instr_start_ts", time.time())
    elapsed = int(time.time() - st.session_state.instr_start_ts)
    remaining = max(0, MIN_SECONDS - elapsed)
    
    countdown = st.empty()
    countdown.caption(
        f"Please stay on this page for at least {MIN_SECONDS} seconds. Remaining: {remaining}s"
    )
    
    if remaining > 0:
        st.button("I agree and continue", disabled=True, key="consent_continue")
        time.sleep(1)
        st.rerun()
        return


    if st.button("I agree and continue"):
        if remaining > 0:
            st.warning(f"Please wait {remaining}s before continuing.")
            return
        if agree:
            st.session_state.stage = "pid"
            st.rerun()
        else:
            st.warning("You must agree to participate before continuing.")

# =============================================================================
# PID PAGE
# =============================================================================
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

    # render_debug_box()


# =============================================================================
# ATTENTION CHECK PAGE (2 att questions)
# =============================================================================
def practice_questions_page():
    st.title("PRACTICE QUESTIONS")

    st.markdown(
        "Before starting the study, please answer the practice questions below. "
        "These questions help ensure the study is working properly and that responses are attentive."
    )

    st.session_state.setdefault("practice_attempts", 0)

    with st.form("practice_form", clear_on_submit=False):
        st.markdown("**What is the fifth word in the following sentence:**")
        st.markdown(f"> {ATTENTION_CHECK_1_SENTENCE}")
        att1 = st.radio("", ATTENTION_CHECK_1_OPTIONS, index=None, horizontal=True, label_visibility="collapsed")

        st.divider()

        att2 = st.radio(
            "**What is your favorite fruit? Please select Orange to show that you are paying attention to this question.**",
            ATTENTION_CHECK_2_OPTIONS,
            index=None,
            horizontal=True,
        )

        submitted = st.form_submit_button("Continue")

    if not submitted:
        return

    # Require both answers (do not count as an attempt if they didn't answer)
    if att1 is None or att2 is None:
        st.error("Please answer both practice questions before continuing.")
        return

    st.session_state.practice_attempts += 1

    ans1 = att1
    ans2 = att2

    pass1 = (str(ans1).strip().lower() == str(ATTENTION_CHECK_1_CORRECT).strip().lower())
    pass2 = (ans2 == ATTENTION_CHECK_2_CORRECT)
    passed = pass1 and pass2

    # Log each attempt (pass/fail)
    log_event(
        "practice_questions",
        title=f"practice_attempt_{st.session_state.practice_attempts}",
        payload={
            "q1_answer": ans1,
            "q2_answer": ans2,
            "pass_q1": pass1,
            "pass_q2": pass2,
            "passed": passed,
        },
    )

    if passed:
        st.session_state.stage = "experiment"
        st.session_state.scroll_top_next = True
        st.rerun()

    # Failed
    if st.session_state.practice_attempts == 1:
        # First failure: show a pop-up alert + on-page warning
        components.html(
            f"<script>window.parent.alert({json.dumps('Please read the questions carefully and try again.')});</script>",
            height=0,
        )
        st.warning("One or more answers were incorrect. Please read the questions carefully and try again.")
        return

    # Second failure: end the study
    log_event(
        "attention_check_failed",
        title="failed_twice",
        payload={"attempts": st.session_state.practice_attempts, "q1": ans1, "q2": ans2},
    )
    st.session_state.stage = "failed_attention"
    st.session_state.scroll_top_next = True
    st.rerun()


# =============================================================================
# EXPERIMENT PAGE (post + vote + comment)
# =============================================================================
def apply_vote(action: str):
    before_vote = st.session_state.user_vote
    before_score = st.session_state.vote_count

    if action == "up":
        if before_vote == 1:
            st.session_state.vote_count -= 1
            st.session_state.user_vote = 0
            event = "undo_upvote"
        else:
            if before_vote == -1:
                st.session_state.vote_count += 1
            st.session_state.vote_count += 1
            st.session_state.user_vote = 1
            event = "upvote"
    else:
        if before_vote == -1:
            st.session_state.vote_count += 1
            st.session_state.user_vote = 0
            event = "undo_downvote"
        else:
            if before_vote == 1:
                st.session_state.vote_count -= 1
            st.session_state.vote_count -= 1
            st.session_state.user_vote = -1
            event = "downvote"

    # Optional: log votes (OFF by default)
    if LOG_VOTES:
        log_event(
            event,
            payload={
                "user_vote_before": before_vote,
                "user_vote_after": st.session_state.user_vote,
                "score_before": before_score,
                "score_after": st.session_state.vote_count,
            },
        )


import re

MIN_WORDS = 50


def count_words(text: str) -> int:
    # More robust than split(): counts word-like tokens
    return len(re.findall(r"\b\w+\b", text or ""))


def experiment_page():
    render_banner()

    st.markdown(
        f"<div style='font-weight:700;'>Below, you will read a thread posted by <span class='emph'>{POSTED_BY_NAME}</span> on social media about <span class='emph'>{TOPIC_LABEL}</span>.</div>",
        unsafe_allow_html=True,
    )
    render_post_meta()

    st.title(POST_TITLE)
    st.markdown(POST_BODY_MD)
    st.divider()

    st.subheader("Add your comment")

    st.markdown(
        f"**Task:** How would you comment on **{POSTED_BY_NAME}**'s thread about **{PRONOUN_POSSESSIVE}** **{TOPIC_LABEL}**?"
    )
    st.caption(
        "Note: Please write the comment independently, without using AI assistance. Responses that do not reflect independent effort may not qualify for the reward."
    )

    # Make sure these exist
    st.session_state.setdefault("comment_draft", "")
    st.session_state.setdefault("has_commented", False)
    st.session_state.setdefault("comment_n", 0)  # just for numbering/log titles

    feedback = st.empty()  # message area (updates when they click buttons)

    with st.form("comment_form", clear_on_submit=False):
        comment_txt = st.text_area(
            "Write your comment:",
            key="comment_draft",
            height=180,
            placeholder=("Minimum 50 words."),
            help="You must write at least 50 words before submitting."
        )

        # Two buttons INSIDE the form → text will not disappear
        c1, c2 = st.columns([1, 1])
        with c1:
            check_wc = st.form_submit_button("Check word count")
        with c2:
            submitted = st.form_submit_button("Post comment")

    # Evaluate the latest committed text (after either button is clicked)
    clean = (comment_txt or "").strip()
    wc = count_words(clean)
    remaining = max(0, MIN_WORDS - wc)

    if check_wc:
        if not clean:
            feedback.info(f"Current word count: **0**. Please write at least **{MIN_WORDS}** words.")
        elif wc < MIN_WORDS:
            feedback.info(f"Current word count: **{wc}**. Please add **{remaining}** more words.")
        else:
            feedback.success(f"Great — word count is **{wc}**. You can submit now.")

    if submitted:
        if not clean:
            feedback.warning("Comment cannot be empty.")
        elif wc < MIN_WORDS:
            feedback.warning(
                f"Your comment is **{wc}** words. Please add **{remaining}** more words (minimum {MIN_WORDS}).")
            # IMPORTANT: we do NOT clear comment_draft, so they keep what they wrote
        else:
            # Mark success
            st.session_state.has_commented = True
            st.session_state.comment_n += 1

            # ✅ Log ONLY the comment (minimal logging)
            log_event(
                "comment_posted",
                title=f"comment_{st.session_state.comment_n}",
                payload={
                    "comment_text": clean,
                    "word_count": wc,
                },
            )

            feedback.success("Comment submitted. You can now continue to the survey.")
    st.markdown("---")

    if st.session_state.has_commented:
        if st.button("Continue to survey"):
            st.session_state.stage = "survey"
            st.session_state.scroll_top_next = True  # 👈 add this
            st.rerun()
    else:
        # only show a gentle reminder BEFORE they've commented
        st.caption("You must submit at least **one comment** (minimum **50 words**) before continuing to the survey.")

    # Vote pill (tight spacing via extra columns)
    # with st.container():
    #     st.markdown("<div id='vote-row-anchor'></div>", unsafe_allow_html=True)
    #     cols = st.columns([1, 0.25, 1, 8], gap="small")
    #     with cols[0]:
    #         if st.button("▲", key="up_btn"):
    #             apply_vote("up")
    #             st.rerun()
    #     with cols[1]:
    #         st.markdown(
    #             f"<div style='display:flex;justify-content:center;align-items:center;height:100%;'>"
    #             f"<span class='vote-score'>{st.session_state.vote_count}</span></div>",
    #             unsafe_allow_html=True,
    #         )
    #     with cols[2]:
    #         if st.button("▼", key="down_btn"):
    #             apply_vote("down")
    #             st.rerun()
    #     inject_vote_css(st.session_state.user_vote)

    # st.divider()
    #
    # st.subheader("Add your comment")
    # with st.form("comment_form", clear_on_submit=True):
    #     comment_txt = st.text_area(
    #         "Write your comment (minimum 50 words):",
    #         key="comment_draft",
    #         height=180,
    #         placeholder=(
    #             "Please write at least 50 words.\n"
    #             "Tip: describe what happened, how you feel about it, and what you would suggest."
    #         ),
    #         help="Your comment must be at least 50 words to proceed."
    #     )
    #
    #     # wc = len(comment_txt.)
    #     # remaining = max(0, MIN_WORDS - wc)
    #     # txt = st.text_area("", placeholder="Write something…", height=120)
    #
    #     clean = (comment_txt or "").strip()
    #     wc = len(comment_txt.split())
    #     # remaining = max(0, 50 - wc)
    #     # st.caption(f"Word count: **{wc}**  |  Remaining: **{remaining}**")
    #
    #     # Submit button (enabled only when enough words)
    #     can_submit = wc >= 50 and comment_txt.strip() != ""
    #     submitted = st.form_submit_button("Post comment")
    #
    # if submitted:
    #
    #     if not clean:
    #         st.warning("Comment cannot be empty.")
    #     if not can_submit:
    #         st.warning("Comment must be longer than 50 words.")
    #     else:
    #         ts = utc_now_iso()
    #         st.session_state.comments.append((ts, clean))
    #         # ✅ Minimal logging: log comment only
    #         log_event(
    #             "comment_posted",
    #             title=f"comment_{len(st.session_state.comments)}",
    #             payload={
    #                 "comment_text": clean,
    #                 "comment_length": len(clean),
    #                 "current_score": st.session_state.vote_count,
    #                 "current_vote": st.session_state.user_vote,
    #             },
    #         )
    #         st.success("Comment posted!")

    # if st.session_state.comments:
    #     st.subheader("Your comments (only you can see these)")
    #     for ts, text in reversed(st.session_state.comments):
    #         with st.expander(f"🗨️ {ts}", expanded=False):
    #             st.markdown(text)

    # st.markdown("---")
    # if st.button("Continue to survey"):
    #     if not st.session_state.has_commented:
    #         st.info("Please post at least **one comment** to continue to the survey.")
    #         return
    #     st.session_state.stage = "survey"
    #     st.rerun()
    # else:
    #     st.info("Please post at least **one comment** to continue to the survey.")

    # render_debug_box()


# =============================================================================
# SURVEY PAGE
# =============================================================================
def likert7(question: str, key: str) -> Optional[int]:
    st.markdown(f"**{question}**")
    return st.radio("", options=[1, 2, 3, 4, 5, 6, 7], horizontal=True, index=None, key=key,
                    label_visibility="collapsed")

LIKERT_1_7 = [1, 2, 3, 4, 5, 6, 7]

ESS_ITEMS = [
    "Online, I would pay attention to this thread.",
    "Online, I would like to say things to make her feel good.",
    "Online, I would like to leave her positive comments.",
    "Online, I would like to show my care about her.",
    "Online, I would like to show my interests in this post.",
    "Online, I would like to show support to her.",
    "Online, I would like to give her likes, favorites, upvotes, views, etc.",
    "Online, I would like to encourage her.",
    "Online, I would like to tell her I like the things she says or does.",
    "Online, I would like to make her feel good about herself.",
]

ISS_ITEMS = [
    "Online, I would like to provide her with helpful information.",
    "Online, I would like to help her by saying what I would do.",
    "Online, I would tell her where to find help.",
    "Online, I would like to offer suggestions to her.",
    "Online, I would like to tell her things she want to know.",
    "Online, I would like to help her understand her situation better.",
    "Online, I would like to share my point of view with her.",
    "Online, I would like to help her see things in new ways.",
    "Online, I would like to give her useful advice.",
    "Online, I would like to help her by saying what she would do.",
]


def survey_page():
    render_banner()

    # Scroll to top when entering this page or switching between survey pages
    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()

    st.session_state.setdefault("survey_step", 1)      # 1, 2, 3
    st.session_state.setdefault("survey_answers", {})  # cumulative across pages

    # -------------------------
    # PAGE 1/3: ESS + ISS
    # -------------------------
    if st.session_state.survey_step == 1:
        st.title("Survey (1/3)")
        st.markdown("This page asks your opinion about the thread you just read.")
        st.caption("Scale: 1 = Strongly disagree, 7 = Strongly agree")

        with st.form("survey_p1", clear_on_submit=False):
            ess_vals = {}
            for i, item in enumerate(ESS_ITEMS, start=1):
                key = f"ESS{i}"
                ess_vals[key] = st.radio(
                    f"{item}",
                    options=LIKERT_1_7,
                    index=None,
                    horizontal=True,
                    key=key,
                )

            st.divider()

            st.caption("Scale: 1 = Strongly disagree, 7 = Strongly agree")

            iss_vals = {}
            for i, item in enumerate(ISS_ITEMS, start=1):
                key = f"ISS{i}"
                iss_vals[key] = st.radio(
                    f"{item}",
                    options=LIKERT_1_7,
                    index=None,
                    horizontal=True,
                    key=key,
                )

            next_btn = st.form_submit_button("Next")

        if next_btn:
            combined = {**ess_vals, **iss_vals}
            missing = [k for k, v in combined.items() if v is None]
            if missing:
                st.error("Please answer all questions on this page before continuing.")
                return

            # Save + log page 1
            st.session_state.survey_answers.update(combined)
            log_event("survey_page1_complete", title="survey_p1", payload=combined)

            st.session_state.survey_step = 2
            st.session_state.scroll_top_next = True
            st.rerun()

        return

    # -------------------------
    # PAGE 2/3: Manipulation + frustration
    # -------------------------
    if st.session_state.survey_step == 2:
        st.title("Survey (2/3)")
        st.caption("Please answer all questions on this page to continue.")

        with st.form("survey_p2", clear_on_submit=False):
            mc_gender = st.radio("The entrepreneur in the post was:", ["Female", "Male"], index=None,
                                 horizontal=True)
            mc_topic = st.radio(
                "The post was mainly about:",
                ["Work-life balance", "Business difficulty"],
                index=None,
                horizontal=True,
                key="mc_topic",
            )

            st.divider()

            st.caption("Scale: 1 = Not at all, 7 = Very strongly")
            frustration = st.radio(
                "To what extent does this post express frustrations and negative experiences?",
                options=LIKERT_1_7,
                index=None,
                horizontal=True,
                key="frustration_strength",
            )

            next_btn = st.form_submit_button("Next")

        if next_btn:
            if mc_gender is None or mc_topic is None or frustration is None:
                st.error("Please answer all questions on this page before continuing.")
                return

            page2 = {
                "mc_gender": mc_gender,
                "mc_topic": mc_topic,
                "frustration_strength": frustration,
            }
            st.session_state.survey_answers.update(page2)
            log_event("survey_page2_complete", title="survey_p2", payload=page2)

            st.session_state.survey_step = 3
            st.session_state.scroll_top_next = True
            st.rerun()

        return

    # -------------------------
    # PAGE 3/3: Identity scales + demographics (GV removed)
    # -------------------------
    st.title("Survey (3/3)")
    st.caption("Scale: 1 = Strongly disagree, 7 = Strongly agree")

    with st.form("survey_p3", clear_on_submit=False):
        # Identity Threat (PIT1–PIT4)
        pit_items = [
            "This post makes me feel that there is a negative value attached to my identity as an entrepreneur.",
            "This post makes me feel that being an entrepreneur is viewed less positively.",
            "This interaction makes me feel that the value of my entrepreneurial identity is being diminished.",
            "This interaction makes me feel that others might see my entrepreneurial identity as less legitimate.",
        ]
        pit_vals = {}
        for i, item in enumerate(pit_items, start=1):
            key = f"PIT{i}"
            pit_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Identity Verification (PIV1–PIV4)
        piv_items = [
            "This post makes me feel more confident in my identity as an entrepreneur.",
            "This interaction strengthens my sense of value in my role as an entrepreneur.",
            "After this interaction, I feel my entrepreneurial identity is positively reinforced.",
            "This post makes me feel recognized as a legitimate business owner.",
        ]
        piv_vals = {}
        for i, item in enumerate(piv_items, start=1):
            key = f"PIV{i}"
            piv_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Entrepreneur identity salience (ES1–ES5)
        es_items = [
            "Being an entrepreneur is an important part of who I am.",
            "I would feel a great sense of loss if I were forced to give up my entrepreneurial role.",
            "I have very clear feelings about being an entrepreneur.",
            "For me, being an entrepreneur is more than just a job; it is a vital part of my life.",
            "I strongly identify with being an entrepreneur.",
        ]
        es_vals = {}
        for i, item in enumerate(es_items, start=1):
            key = f"ES{i}"
            es_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Gender identity salience (GS1–GS5)
        gs_items = [
            "I would feel like a significant part of me was missing if I could no longer identify with my gender.",
            "My gender is an important part of my overall sense of self.",
            "I have a very clear and defined sense of what my gender means to me.",
            "My gender is a vital lens through which I experience and navigate my life.",
            "I feel a strong sense of connection to the shared experiences associated with my gender.",
        ]
        gs_vals = {}
        for i, item in enumerate(gs_items, start=1):
            key = f"GS{i}"
            gs_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Demographics (required)
        birth_year = st.selectbox(
            "What is your birth year?",
            list(range(1960, 2006)),
            index=None,
            placeholder="Select…",
            key="birth_year",
        )
        gender = st.selectbox(
            "What is your gender?",
            ["female", "male", "third gender", "transgender"],
            index=None,
            placeholder="Select…",
            key="demo_gender",
        )
        education = st.selectbox(
            "What’s your highest level of formal education?",
            [
                "High school degree or below",
                "Associated or technical degree",
                "Bachelor degree",
                "Master degree",
                "Doctorate degree",
            ],
            index=None,
            placeholder="Select…",
            key="education",
        )
        ent_years = st.selectbox(
            "How many years of entrepreneurial experience do you have?",
            list(range(0, 51)),
            index=None,
            placeholder="Select…",
            key="ent_years",
        )
        work_years = st.selectbox(
            "How many years of work experience do you have?",
            list(range(0, 51)),
            index=None,
            placeholder="Select…",
            key="work_years",
        )

        submit_btn = st.form_submit_button("Submit survey")

    if not submit_btn:
        return

    # Validate Page 3 required items
    missing = []
    for d, label in [
        (pit_vals, "PIT"),
        (piv_vals, "PIV"),
        (es_vals, "ES"),
        (gs_vals, "GS"),
    ]:
        for k, v in d.items():
            if v is None:
                missing.append(k)

    for k, v in [
        ("birth_year", birth_year),
        ("demo_gender", gender),
        ("education", education),
        ("ent_years", ent_years),
        ("work_years", work_years),
    ]:
        if v is None:
            missing.append(k)

    if missing:
        st.error("Please answer all questions on this page before submitting.")
        return

    page3 = {
        **pit_vals,
        **piv_vals,
        **es_vals,
        **gs_vals,
        "birth_year": birth_year,
        "gender": gender,
        "education": education,
        "entrepreneurial_years": ent_years,
        "work_years": work_years,
    }

    # Combine all pages
    responses = dict(st.session_state.survey_answers)
    responses.update(page3)
    responses["condition"] = CONDITION

    # ✅ Final log (contains EVERYTHING)
    log_event("survey_submitted", title="survey", payload=responses)

    st.session_state.stage = "done"
    st.rerun()


def done_page():
    render_banner()
    st.title("Finished")
    st.success("Thanks — your responses have been recorded.")
    st.caption("You may now close this tab.")
    # render_debug_box()


def failed_attention_page():
    render_banner()
    st.title("Not qualified")
    st.error("Really sorry, but you failed the attention check twice and are not qualified for this study.")
    st.caption("You may now close this tab.")


# =============================================================================
# ROUTER
# =============================================================================
def main():
    # Auto PID from Prolific URL
    # (We prefill the Prolific ID on the PID page via the URL parameter, but do NOT auto-skip any steps.)

    stage = st.session_state.stage
    if st.session_state.stage == "consent":
        render_consent_page()
        return
    if st.session_state.stage == "practice":
        practice_questions_page()
        return
    if stage == "failed_attention":
        failed_attention_page()
        return
    if stage == "pid":
        pid_page();
        return
    if stage == "experiment":
        experiment_page();
        return
    if stage == "survey":
        survey_page();
        return
    done_page()


if __name__ == "__main__":
    main()
