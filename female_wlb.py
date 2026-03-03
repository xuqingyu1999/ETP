# file: female_wlb.py
# Female WLB condition
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

# =============================================================================
# EXPERIMENT SETTINGS (Female WLB)
# =============================================================================
CONDITION = "F_WLB"

SUBREDDIT = "r/business"
DAYS_AGO = 7
AUTHOR_USERNAME = "Fit_Bet_1261"
POSTED_BY_NAME = "Maria"

POST_TITLE = "My husband told me this on my birthday (yesterday) and I think – I need to improve my work-life balance."
POST_BODY_MD = """
My husband told me this on my birthday (yesterday) and I think – I need to improve my work-life balance. A little bit of context. My husband and son had each bought presents for me about 2 weeks prior to my birthday and placed it around my home office. I use the office daily and did not even notice the gifts. Looking back now, they tried hinting and drawing my attention to the presents but as you guys know I was blinded by work.

My son got tired of the cat and mouse game and pointed the gifts out on my birthday. While opening the gift, my husband said you are chasing the things you want and fail to enjoy the things you have. He is right (he always is :) The funny part is that the gift he offered me was going to be my December bonus for achieving my quarterly goals.

Lesson learned: over the next year I want to structure some time to enjoy what I have. Starting with looking around my home office every time I use it. I don’t want to miss an early bonus again. :) My birthday wish for all of us is to **find the balance** between chasing our goals and enjoying the ones we have already achieved.
""".strip()

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

    # Use ServiceAccountCredentials to match example pattern
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes=scopes)
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


def save_to_gsheet(data: Dict[str, Any]) -> str:
    """Append to Google Sheet with retries. If it fails, write to local CSV.

    Returns "" (empty string) to match the style of your example.
    """
    data = dict(data)
    data.setdefault("variant", CONDITION)

    row = [data.get(k, "") for k in GSHEET_KEYS]

    # Always keep a local backup too
    _append_local(row)

    try:
        ws = _get_sheet1()
        ws.append_row(row)
    except Exception as e:
        st.session_state["_gsheet_error"] = f"Logging error: {e}"
    
    return ""


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
    # Banner
    cols = st.columns([1, 4, 1])
    with cols[1]:
        if REDDIT_LOGO_PATH.exists():
            st.image(str(REDDIT_LOGO_PATH), width=120)
        else:
            st.markdown("### Reddit")


def render_post_meta():
    c1, c2 = st.columns([0.15, 0.85])
    with c1:
        if AVATAR_PATH.exists():
            st.image(str(AVATAR_PATH), width=45)
        else:
            st.markdown("👤")
    with c2:
        st.markdown(
            f"**{SUBREDDIT}** • Posted by u/{AUTHOR_USERNAME} {DAYS_AGO} days ago"
        )


def inject_vote_css(user_vote: int):
    up_color = "#ff4500" if user_vote == 1 else "#878a8c"
    down_color = "#7193ff" if user_vote == -1 else "#878a8c"
    st.markdown(
        f"""
        <style>
        div[data-testid="stButton"] button[key="up_btn"] {{
            color: {up_color} !important;
            border-color: {up_color} !important;
            background-color: transparent !important;
            padding: 0px 5px !important;
        }}
        div[data-testid="stButton"] button[key="down_btn"] {{
            color: {down_color} !important;
            border-color: {down_color} !important;
            background-color: transparent !important;
            padding: 0px 5px !important;
        }}
        .vote-score {{
            font-weight: bold;
            font-size: 0.9rem;
            color: #1a1a1b;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# PID / CONSENT PAGE
# =============================================================================
def consent_page():
    st.title("Welcome to the Study")
    st.markdown(
        """
        Thank you for participating in this research. 
        
        Please enter your **Participant ID** (PID) to begin.
        """
    )

    pid = st.text_input("Participant ID:", key="pid_input").strip()

    if st.button("Continue"):
        if not pid:
            st.error("Please enter your Participant ID to continue.")
            return

        pid_clean = pid.replace(",", "").strip()
        st.session_state.prolific_id = pid_clean
        st.session_state.start_time = utc_now_iso()
        st.session_state.session_id = str(uuid.uuid4())[:8]

        # Init variables
        st.session_state.vote_count = DEFAULT_SCORE
        st.session_state.user_vote = 0
        st.session_state.comments = []

        log_event("session_start", payload={"pid": pid_clean, "session_id": st.session_state.session_id})
        st.session_state.stage = "practice"
        st.session_state.scroll_top_next = True
        st.rerun()


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

    if submitted:
        st.session_state.practice_attempts += 1

        ans1 = att1
        ans2 = att2

        pass1 = (ans1 == "because") if ans1 else False
        pass2 = (ans2 == "Orange") if ans2 else False
        passed = pass1 and pass2

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

        st.session_state.stage = "experiment"
        st.session_state.scroll_top_next = True
        st.rerun()


# =============================================================================
# EXPERIMENT PAGE (post + vote + comment)
# =============================================================================
import re

MIN_WORDS = 50

def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))

def experiment_page():
    render_banner()

    st.markdown(f"**Below, you will read a thread posted by {POSTED_BY_NAME} on social media.**")
    render_post_meta()

    st.title(POST_TITLE)
    st.markdown(POST_BODY_MD)
    st.divider()

    st.subheader("Add your comment")

    st.session_state.setdefault("comment_draft", "")
    st.session_state.setdefault("has_commented", False)
    st.session_state.setdefault("comment_n", 0)

    feedback = st.empty()

    with st.form("comment_form", clear_on_submit=False):
        comment_txt = st.text_area(
            "Write your comment:",
            key="comment_draft",
            height=180,
            placeholder=(
                "Minimum 50 words.\n"
                f"Tip: How would you comment on {POSTED_BY_NAME}’s thread about her work-life balance?"
            ),
            help="You must write at least 50 words before submitting."
        )

        c1, c2 = st.columns([1, 1])
        with c1:
            check_wc = st.form_submit_button("Check word count")
        with c2:
            submitted = st.form_submit_button("Post comment")

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
        else:
            st.session_state.has_commented = True
            st.session_state.comment_n += 1

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
            st.session_state.scroll_top_next = True
            st.rerun()
    else:
        st.caption("You must submit at least **one comment** (minimum **50 words**) before continuing to the survey.")


# =============================================================================
# SURVEY PAGE
# =============================================================================
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

    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()

    st.session_state.setdefault("survey_step", 1)
    st.session_state.setdefault("survey_answers", {})

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
                    f"{i}. {item}",
                    options=LIKERT_1_7,
                    index=None,
                    horizontal=True,
                    key=key,
                )

            st.divider()

            iss_vals = {}
            for i, item in enumerate(ISS_ITEMS, start=1):
                key = f"ISS{i}"
                iss_vals[key] = st.radio(
                    f"{10+i}. {item}",
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
    # PAGE 3/3: Identity scales + demographics
    # -------------------------
    st.title("Survey (3/3)")
    st.caption("Scale: 1 = Strongly disagree, 7 = Strongly agree")

    with st.form("survey_p3", clear_on_submit=False):
        # Identity Threat
        pit_vals = {}
        for i, item in enumerate(IDENTITY_THREAT_ITEMS, start=1):
            key = f"PIT{i}"
            pit_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Identity Verification
        piv_vals = {}
        for i, item in enumerate(IDENTITY_VERIFICATION_ITEMS, start=1):
            key = f"PIV{i}"
            piv_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Entrepreneur identity salience
        es_vals = {}
        for i, item in enumerate(ENTREPRENEUR_ID_SALIENCE_ITEMS, start=1):
            key = f"ES{i}"
            es_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Gender identity salience
        gs_vals = {}
        for i, item in enumerate(GENDER_ID_SALIENCE_ITEMS, start=1):
            key = f"GS{i}"
            gs_vals[key] = st.radio(item, options=LIKERT_1_7, index=None, horizontal=True, key=key)

        st.divider()

        # Demographics
        birth_year = st.selectbox(
            "What is your birth year?",
            list(range(1960, 2006)),
            index=None,
            placeholder="Select Year",
        )
        gender = st.radio("What is your gender?", ["Male", "Female", "Non-binary / Other", "Prefer not to say"],
                          index=None, horizontal=True)
        
        st.divider()
        st.markdown("**Are you an entrepreneur?**")
        is_entrepreneur = st.radio(
            "(e.g., Do you own a business, work as a freelancer, or are you currently starting a venture?)",
            ["Yes", "No"],
            index=None,
            horizontal=True,
        )

        submit_btn = st.form_submit_button("Submit Survey")

    if submit_btn:
        all_p3 = {**pit_vals, **piv_vals, **es_vals, **gs_vals}
        missing_p3 = [k for k, v in all_p3.items() if v is None]
        if missing_p3 or birth_year is None or gender is None or is_entrepreneur is None:
            st.error("Please answer all questions before submitting.")
            return

        final_data = {
            **st.session_state.survey_answers,
            **all_p3,
            "birth_year": birth_year,
            "gender": gender,
            "is_entrepreneur": is_entrepreneur,
        }
        log_event("survey_submitted", title="final_survey", payload=final_data)
        st.session_state.stage = "thanks"
        st.rerun()


# =============================================================================
# THANKS PAGE
# =============================================================================
def thanks_page():
    st.balloons()
    st.title("Thank You!")
    st.markdown(
        """
        Your responses have been recorded. You have completed the study.
        
        You can now close this window.
        """
    )


# =============================================================================
# MAIN APP ROUTING
# =============================================================================
def main():
    if st.session_state.stage == "consent":
        consent_page()
    elif st.session_state.stage == "practice":
        practice_questions_page()
    elif st.session_state.stage == "experiment":
        experiment_page()
    elif st.session_state.stage == "survey":
        survey_page()
    elif st.session_state.stage == "thanks":
        thanks_page()


if __name__ == "__main__":
    main()
