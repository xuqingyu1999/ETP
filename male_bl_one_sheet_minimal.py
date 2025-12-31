# # file: male_bl_one_sheet_minimal.py
# # Male BL condition (single-app version) — simplified Google Sheet logging
# #
# # What you asked for in the latest message:
# #   ✅ One Google Sheet (sheet1) for everything
# #   ✅ PID enter page (like your example)
# #   ✅ Record start time + timestamps
# #   ✅ Reduce logging noise: by default ONLY log
# #        - session_start
# #        - comment_posted
# #        - survey_submitted
# #      (you can switch on vote logging via LOG_VOTES = True)
# #   ✅ Use the SAME function names/pattern as your example:
# #        - get_credentials_from_secrets()
# #        - save_to_gsheet(data)
# #      with: client.open("SeEn Ads").sheet1.append_row(...)
# #   ✅ Local testing friendly: if Google Sheets fails, ALWAYS save to
# #      fallback_event_log.csv (UTF-8) and show the error in a small
# #      “Debug” expander.

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

# # =============================================================================
# # EXPERIMENT SETTINGS (Male BL)
# # =============================================================================
# CONDITION = "M_BL"

# SUBREDDIT = "r/business"
# DAYS_AGO = 7
# AUTHOR_USERNAME = "Fit_Bet_1261"
# POSTED_BY_NAME = "David"

# POST_TITLE = "Running a business is difficult!"
# POST_BODY_MD = """
# Running a business is difficult! I am a small business owner. For the last two years, I’ve answered the calls, given the quotes, and assisted in the labor. 100% focus on being professional, on-time, and accurate with quotes/pricing.  We have received nothing but 5 star reviews on yelp, google, Facebook, etc... I’ve built up around 20 reviews on yelp which are all 5 star reviews. Unfortunately 14 out of the 20 are hidden and not shown.

# They call me every other day even though I’ve told them again and again that they can email me offers. I don’t have time to answer disguised calls from reps all day. I understand how yelp works... I understand that i got more customer views when I was advertising with yelp... i understand how to setup everything on yelp and do not need any assistance...

# The harassment, call number disguising, the taking down of reviews, removing service locations... it’s not good business. Now today, I log in... and it keeps clearing my services list.

# I’m wondering how many others this happens to. Google Reviews is only going to improve, and yelp will be nothing... I’m done with them.
# """.strip()

# DEFAULT_SCORE = 5

# # --- logging controls (reduce "too many logs") ---
# LOG_VOTES = False  # set True if you also want vote events

# st.session_state.setdefault("stage", "consent")

# # =============================================================================
# # SURVEY CONTENT
# # =============================================================================
# ATTENTION_CHECK_1_SENTENCE = "Bobby is very happy because he is going to the movies."
# ATTENTION_CHECK_1_OPTIONS = ["very", "happy", "going", "because", "movies", "is", "the"]
# ATTENTION_CHECK_1_CORRECT = "because"

# ATTENTION_CHECK_2_OPTIONS = ["Grape", "Apple", "Pear", "Orange", "Strawberry"]
# ATTENTION_CHECK_2_CORRECT = "Orange"

# ONLINE_SITES = ["Facebook", "Instagram", "Twitter", "YouTube", "Pinterest", "Reddit", "LinkedIn", "WhatsApp"]
# ONLINE_SCALE = ["Never", "Rarely", "Sometimes", "Often", "Always"]


# # =============================================================================
# # STREAMLIT PAGE CONFIG
# # =============================================================================
# st.set_page_config(page_title="Reddit-style Study (M_BL)", page_icon="🧪", layout="centered")

# st.markdown(
#     """
# <style>
# #MainMenu {visibility: hidden;}
# footer {visibility: hidden;}
# header [data-testid="stToolbar"] {display: none !important;}
# header [data-testid="stToolbarActions"] {display: none !important;}
# </style>
# """,
#     unsafe_allow_html=True,
# )


# def utc_now_iso() -> str:
#     return datetime.now(timezone.utc).isoformat()


# def get_query_param(name: str) -> Optional[str]:
#     try:
#         v = st.query_params.get(name)
#         if isinstance(v, list):
#             return v[0] if v else None
#         return v
#     except Exception:
#         qp = st.experimental_get_query_params()
#         vals = qp.get(name, [])
#         return vals[0] if vals else None


# def to_data_uri(local_path: Path) -> str:
#     if not local_path.exists():
#         return ""
#     suffix = local_path.suffix.lower()
#     mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
#     b64 = base64.b64encode(local_path.read_bytes()).decode("utf-8")
#     return f"data:{mime};base64,{b64}"


# # =============================================================================
# # GOOGLE SHEET LOGGING (same pattern / same function names as your example)
# # =============================================================================
# GSHEET_KEYS = ["id", "start", "variant", "timestamp", "type", "title", "url"]
# MIN_SECONDS = 10
# def render_consent_page():
#     st.title("Study Information and Consent")

#     st.markdown("""
#     **Study Overview and Consent**

#     You are invited to participate in a research study about **entrepreneurial experiences**.
#     You must be **18 years or older** to participate.

#     In this study, you will read a short paragraph describing an entrepreneur’s experience
#     (e.g., business challenges or work–life balance issues). After reading, you will be asked
#     to **write a brief comment** and **answer several questions** about your reactions.

#     The study will take approximately **10–15 minutes**. There will be **no follow-up questionnaire**.

#     Your participation is **voluntary**. You may stop participating at any time without penalty.
#     All responses are **anonymous**, and no identifying information will be collected or reported.
#     De-identified data may be shared with other researchers for academic purposes.

#     There are **no known risks** associated with this study and no direct benefits to you.
#     You will receive **$0.50** for completing the study.

#     For scientific reasons, full details about the research purpose cannot be provided at this time.
#     You will be **fully debriefed** after completing the study.

#     If you have questions about your rights as a research participant, you may contact the
#     Office of Research Integrity, Ball State University, Muncie, IN 47306,
#     (765) 285-5052, or orihelp@bsu.edu.
#     """)

#     agree = st.checkbox("I am at least 18 years old and I agree to participate in this study.")

#     st.session_state.setdefault("instr_start_ts", time.time())

#     elapsed = int(time.time() - st.session_state.instr_start_ts)
#     remaining = max(0, MIN_SECONDS - elapsed)

#     st.caption(f"Please stay on this page for at least {MIN_SECONDS} seconds. "
#                f"Remaining: {remaining}s")

#     if st.button("I agree and continue"):
#         if remaining > 0:
#             st.warning(f"Please wait {remaining}s before continuing.")
#             return
#         if agree:
#             st.session_state.stage = "pid"
#             st.rerun()
#         else:
#             st.warning("You must agree to participate before continuing.")


# # def get_credentials_from_secrets() -> Dict[str, Any]:
# #     """Return a service-account dict.
# #
# #     Local testing support:
# #       1) If you have .streamlit/secrets.toml with [GOOGLE_CREDENTIALS], use it.
# #       2) Else, load a local JSON file (default: streamlit_app.json next to this .py).
# #     """
# #     # 1) secrets.toml
# #     if "GOOGLE_CREDENTIALS" in st.secrets:
# #         creds_dict = {k: v for k, v in st.secrets["GOOGLE_CREDENTIALS"].items()}
# #         if isinstance(creds_dict.get("private_key"), str):
# #             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
# #         return creds_dict
# #
# #     creds_dict = {
# #         "type": "service_account",
# #         "project_id": "sonorous-earth-435907-a1",
# #         "private_key_id": "7f73728ecf5fc01c95352356b6c9c3cb9455e82c",
# #         "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC/jBWfexTn4SVT\ncETSe5oLns9PS25fEXk/aivXpcS5/MmVHnLHZjHZOmc5NTgq4BDjFTefMDQERMjE\n6UceovyPLvuwtj47mqlog4DIRhZ4WkOmr5TLDRfcNtZWk12aERfgpNlVfUYMGWb/\nl2PkYcH1MCPt+VFrOMCp01IkKghj4BeJbx985lMQ6Fw/aFJzP7tlANl3ox6Wst0d\nZ325fikKBJZbzgNOPVbTDkT0U2nZQru3+HJj3EJjyhOUkL3LiqtUf5vyj0/SB5j8\n1LsY2MUQTiVpd+aucdsuwTkQRJVKDT5aXRDh8546gR/k4rI5jI1lgzK0JBjyy+PO\n98wHpYdTAgMBAAECggEACCDMphjV+UT/jXvdH8Vo8wdJKsc7psMaDwvVUnBRWccV\nUsOZAUcf5GTrDm1otcEOVmSHGLU179xvXJO9ldo6t2S5/3SsTWExwSKba2Q1/eNu\nrXsT6E3k7k5RaBkWxrvk9H5qTotjVo4ZZc0pyv4u+dWSIL4Mq20cF9jEyo4SDxLX\ngRymSm8DOdXO7Ju8fQcPPKM7RtLH13QBrh7YJ50F/OnLgxfMCYthu0eXwsIIP7RT\nsd811zQ/V064P2JKkb2aDMj5/zBJqkKFCOEStQKjCIQNXmEuI/GbMb9YMKCo7UpV\nTc/Up6cxCReyfL+HTArSdgHUX0OUmN9LHbZLQ9LOGQKBgQDg6rg3KgAqFUiKH0R3\nHUdev2JeT2EHO3Q7hc0Y61o1FkcgRUDHO+P4WCT7/IeFV8TMuPyBBzQAezvNb9XX\n2TCwii4Wf7Q+jNNz3nSpC4/U2TY1uDFDe3Y6rCjWFh33Cc9fHUt7fwbeDZk7SKvF\nolo0nIftZf02U981UdZNgbLqhwKBgQDaBMmOqAU2nuxuZMA/DRsKp8kEft/+S+K/\n9UPWogfSRDbusCj6Cb/kFJw7loPoBzE3bHG0kZRqc+syV62OCG2yxOKGci9m1FRW\nJXQVitBYOKaJkNKaQjHs+UtYBn/zZ53ULcaEZ3MVwj2iG1atqmzBGNtiqWGJMgkg\nis8b1NSz1QKBgQCjGfNOpZmK6vY4m2YFzuijj7vg0kV1firSwzuw93LqDmazwySv\nlgHCZQEk7sLD8prXLsqFMtkGBFegqZn0Nh711q6HSEJIHc11N/t3XtgFrSJ/oDux\nSQW6lH/kiBNgwu9rdQ3412v+ePQGprNR1WL+xghYIl6WGApEWz1B5Wz+XwKBgDjU\nRKG95FX/iQuhkYcd6G2XnMtiMwr7RujYis1YwQcrJtKC8rtybSWLxcm2iz2hGlAj\nIWR7Ch/RhX5C4oeCZO3TamS3QOnh8PXfn2m6HGLSqX50VKFHHfJybRRN5W5SFQ7o\nu7VprdL/JceqrqZoJR8UVqNaGYWEmGJ2LFRJ3wPdAoGACdRoKIVJRhcmSZ8OHhAt\nKIiU+/FnPr5+qx4+1daDuMDSQEb8dz4vyHQjYvGD8DYn1jIC9Rjlh83jDtqdaBO5\nZ6DuLLc3vlvV6On8db/WzIeAFHcigvkvKSLVRwg7RDQxQYUSOwUIPNcxKtihYA4e\nilJM/3DmsNmwUFCTv+kTjeg=\n-----END PRIVATE KEY-----\n",
# #         "client_email": "streamlit-click-logger@sonorous-earth-435907-a1.iam.gserviceaccount.com",
# #         "client_id": "113829506494814206491",
# #         "auth_uri": "https://accounts.google.com/o/oauth2/auth",
# #         "token_uri": "https://oauth2.googleapis.com/token",
# #         "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
# #         "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/streamlit-click-logger%40sonorous-earth-435907-a1.iam.gserviceaccount.com",
# #         "universe_domain": "googleapis.com"
# #     }
# #     if creds_dict:
# #         return creds_dict
# #
# #     raise RuntimeError(
# #         "Google credentials not found. Add .streamlit/secrets.toml with [GOOGLE_CREDENTIALS], "
# #         "or place streamlit_app.json next to this script (or set GOOGLE_APPLICATION_CREDENTIALS)."
# #     )
# def get_credentials_from_secrets():
#     # 还原成 dict
#     creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
#     creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

#     return creds_dict




# @st.cache_resource(show_spinner=False)
# def _get_sheet1():
#     """Connect once and keep the handle."""
#     # scopes
#     scopes = [
#         "https://www.googleapis.com/auth/spreadsheets",
#         "https://www.googleapis.com/auth/drive",
#     ]

#     creds_dict = get_credentials_from_secrets()

#     if _USE_OAUTH2CLIENT:
#         creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes=scopes)
#         client = gspread.authorize(creds)
#     else:
#         creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
#         client = gspread.authorize(creds)

#     # spreadsheet name (defaults to your example)
#     spreadsheet_name = (
#         st.secrets.get("SPREADSHEET_NAME", None)
#         if hasattr(st, "secrets")
#         else None
#     )
#     spreadsheet_name = spreadsheet_name or os.getenv("SPREADSHEET_NAME") or "SeEn Ads"

#     sh = client.open(spreadsheet_name)
#     ws = sh.sheet1

#     # ensure header row exists
#     first_row = ws.row_values(1)
#     if not first_row:
#         ws.append_row(GSHEET_KEYS)
#     return ws


# LOCAL_FALLBACK = "fallback_event_log.csv"


# def _append_local(row: List[Any]) -> None:
#     exists = Path(LOCAL_FALLBACK).exists()
#     with open(LOCAL_FALLBACK, "a", newline="", encoding="utf-8") as f:
#         w = csv.writer(f)
#         if not exists:
#             w.writerow(GSHEET_KEYS)
#         w.writerow(row)


# # def save_to_gsheet(data: Dict[str, Any]) -> str:
# #     """Append to Google Sheet with retries. If it fails, write to local CSV.
# #
# #     Returns "" (empty string) to match the style of your example.
# #     """
# #     data = dict(data)
# #     data.setdefault("variant", CONDITION)
# #
# #     row = [data.get(k, "") for k in GSHEET_KEYS]
# #
# #     # Always keep a local backup too (so you have 2 copies: Google + local)
# #     _append_local(row)
# #
# #     try:
# #         ws = _get_sheet1()
# #     except Exception as e:
# #         st.session_state["_gsheet_error"] = f"Init error: {e}"
# #         return ""
# #
# #     for i in range(3):
# #         try:
# #             ws.append_row(row)
# #             return ""
# #         except Exception as e:
# #             st.session_state["_gsheet_error"] = f"Append error: {e}"
# #             time.sleep(0.5)
# #
# #     return ""
# def save_to_gsheet(data):
#     scope = [
#         "https://spreadsheets.google.com/feeds",
#         "https://www.googleapis.com/auth/drive"
#     ]

#     creds = ServiceAccountCredentials.from_json_keyfile_dict(
#         get_credentials_from_secrets(), scope
#     )
#     client = gspread.authorize(creds)

#     sheet = client.open("ETP-MALE-BD").sheet1
#     sheet.append_row([
#         data.get("id", ""),
#         data.get("start", ""),
#         data.get("variant", ""),
#         data.get("timestamp", ""),
#         data.get("type", ""),
#         data.get("title", ""),
#         data.get("url", "")
#     ])



# def log_event(event_type: str, *, title: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
#     """One unified logger. 'url' column stores JSON payload."""
#     pid = st.session_state.get("prolific_id") or ""
#     start = st.session_state.get("start_time") or ""
#     save_to_gsheet(
#         {
#             "id": pid,
#             "start": start,
#             "variant": CONDITION,
#             "timestamp": utc_now_iso(),
#             "type": event_type,
#             "title": title,
#             "url": json.dumps(payload or {}, ensure_ascii=False),
#         }
#     )


# # =============================================================================
# # REDDIT-LIKE UI (banner + meta + compact vote)
# # =============================================================================
# APP_DIR = Path(__file__).parent
# REDDIT_LOGO_PATH = APP_DIR / "reddit_logo.png"
# AVATAR_PATH = APP_DIR / "avatar.jpg"


# def render_banner():
#     logo_uri = to_data_uri(REDDIT_LOGO_PATH)
#     st.markdown(
#         f"""
#         <style>:root {{ --banner-font-size: 2rem; }}</style>
#         <div style="display:flex;align-items:center;gap:10px;width:100%;padding:16px 0 24px 0;">
#             <img src="{logo_uri}" style="width:36px;height:36px;">
#             <span style="font-family:Roboto,Arial,sans-serif;font-size:var(--banner-font-size);line-height:1.1;font-weight:700;color:#FF4500;">reddit</span>
#         </div>
#         <hr style="margin:0 0 20px 0;">
#         """,
#         unsafe_allow_html=True,
#     )


# def render_post_meta():
#     avatar_uri = to_data_uri(AVATAR_PATH)
#     st.markdown(
#         f"""
#         <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
#             <img src="{avatar_uri}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">
#             <div style="line-height:1.1;">
#                 <div style="font-weight:700;">{SUBREDDIT} &middot; {DAYS_AGO} days ago</div>
#                 <div style="color:#6e6e6e;font-size:0.95rem;">{AUTHOR_USERNAME}</div>
#             </div>
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )


# PALETTE = {
#     "neutral_bg": "#ECEFF1",
#     "neutral_fg": "#000000",
#     "up_bg": "#FF4500",
#     "down_bg": "#6E4AFF",
#     "active_fg": "#FFFFFF",
# }


# def inject_vote_css(user_vote: int):
#     up_bg = PALETTE["up_bg"] if user_vote == 1 else PALETTE["neutral_bg"]
#     down_bg = PALETTE["down_bg"] if user_vote == -1 else PALETTE["neutral_bg"]
#     up_fg = PALETTE["active_fg"] if user_vote == 1 else PALETTE["neutral_fg"]
#     down_fg = PALETTE["active_fg"] if user_vote == -1 else PALETTE["neutral_fg"]
#     score_c = up_bg if user_vote == 1 else (down_bg if user_vote == -1 else PALETTE["neutral_fg"])

#     st.markdown(
#         f"""
#         <style>
#         div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] {{ column-gap: 0 !important; }}
#         div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{ padding: 0 !important; margin: 0 !important; }}
#         div:has(> #vote-row-anchor) button {{ min-width: auto !important; }}

#         div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(1) button {{
#             border-radius: 9999px !important; padding: 4px 10px !important; border: none !important;
#             background: {up_bg} !important; color: {up_fg} !important;
#         }}
#         div:has(> #vote-row-anchor) div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-of-type(3) button {{
#             border-radius: 9999px !important; padding: 4px 10px !important; border: none !important;
#             background: {down_bg} !important; color: {down_fg} !important;
#         }}
#         span.vote-score {{ font-weight: 600; color: {score_c}; padding: 0 2px; }}
#         </style>
#         """,
#         unsafe_allow_html=True,
#     )


# # =============================================================================
# # SESSION STATE
# # =============================================================================
# st.session_state.setdefault("stage", "pid")  # pid -> experiment -> survey -> done
# st.session_state.setdefault("session_id", str(uuid.uuid4()))
# st.session_state.setdefault("start_time", utc_now_iso())
# st.session_state.setdefault("prolific_id", None)

# # st.session_state.setdefault("vote_count", DEFAULT_SCORE)
# # st.session_state.setdefault("user_vote", 0)
# st.session_state.setdefault("comments", [])  # list[(ts, txt)]


# def render_debug_box():
#     """Small optional panel to see why Google didn’t update."""
#     with st.expander("Debug (Google Sheet status)", expanded=False):
#         err = st.session_state.get("_gsheet_error")
#         if err:
#             st.error(err)
#         else:
#             st.success("No Google Sheet error recorded in this session.")

#         st.caption("If your Google Sheet isn’t updating, the #1 cause is: the sheet is not shared with the service account email.")

#         if st.button("Test Google Sheet write"):
#             log_event("debug_test", title="hello", payload={"ts": utc_now_iso()})
#             st.info("Wrote a test row (also saved locally). Refresh your Google Sheet.")


# # =============================================================================
# # PID PAGE
# # =============================================================================
# def pid_page():
#     render_banner()
#     st.title("Welcome!")
#     st.markdown("Please enter your **Prolific ID** to begin.")

#     prefill = get_query_param("PROLIFIC_PID") or ""
#     pid = st.text_input("Prolific ID", value=prefill)

#     if st.button("Confirm"):
#         pid_clean = (pid or "").strip()
#         if not pid_clean:
#             st.error("Please enter your Prolific ID.")
#             return

#         st.session_state.prolific_id = pid_clean
#         log_event("session_start", payload={"pid": pid_clean, "session_id": st.session_state.session_id})
#         st.session_state.stage = "experiment"
#         st.rerun()

#     # render_debug_box()


# # =============================================================================
# # EXPERIMENT PAGE (post + vote + comment)
# # =============================================================================
# def apply_vote(action: str):
#     before_vote = st.session_state.user_vote
#     before_score = st.session_state.vote_count

#     if action == "up":
#         if before_vote == 1:
#             st.session_state.vote_count -= 1
#             st.session_state.user_vote = 0
#             event = "undo_upvote"
#         else:
#             if before_vote == -1:
#                 st.session_state.vote_count += 1
#             st.session_state.vote_count += 1
#             st.session_state.user_vote = 1
#             event = "upvote"
#     else:
#         if before_vote == -1:
#             st.session_state.vote_count += 1
#             st.session_state.user_vote = 0
#             event = "undo_downvote"
#         else:
#             if before_vote == 1:
#                 st.session_state.vote_count -= 1
#             st.session_state.vote_count -= 1
#             st.session_state.user_vote = -1
#             event = "downvote"

#     # Optional: log votes (OFF by default)
#     if LOG_VOTES:
#         log_event(
#             event,
#             payload={
#                 "user_vote_before": before_vote,
#                 "user_vote_after": st.session_state.user_vote,
#                 "score_before": before_score,
#                 "score_after": st.session_state.vote_count,
#             },
#         )

# import re

# MIN_WORDS = 50

# def count_words(text: str) -> int:
#     # More robust than split(): counts word-like tokens
#     return len(re.findall(r"\b\w+\b", text or ""))

# def experiment_page():
#     render_banner()

#     st.markdown(f"**Below, you will read a thread posted by {POSTED_BY_NAME} on social media.**")
#     render_post_meta()

#     st.title(POST_TITLE)
#     st.markdown(POST_BODY_MD)
#     st.divider()

#     st.subheader("Add your comment")

#     # Make sure these exist
#     st.session_state.setdefault("comment_draft", "")
#     st.session_state.setdefault("has_commented", False)
#     st.session_state.setdefault("comment_n", 0)  # just for numbering/log titles

#     feedback = st.empty()  # message area (updates when they click buttons)

#     with st.form("comment_form", clear_on_submit=False):
#         comment_txt = st.text_area(
#             "Write your comment:",
#             key="comment_draft",
#             height=180,
#             placeholder=(
#                 "Minimum 50 words.\n"
#                 "Tip: describe what happened, how you feel about it, and what you would suggest."
#             ),
#             help="You must write at least 50 words before submitting."
#         )

#         # Two buttons INSIDE the form → text will not disappear
#         c1, c2 = st.columns([1, 1])
#         with c1:
#             check_wc = st.form_submit_button("Check word count")
#         with c2:
#             submitted = st.form_submit_button("Post comment")

#     # Evaluate the latest committed text (after either button is clicked)
#     clean = (comment_txt or "").strip()
#     wc = count_words(clean)
#     remaining = max(0, MIN_WORDS - wc)

#     if check_wc:
#         if not clean:
#             feedback.info(f"Current word count: **0**. Please write at least **{MIN_WORDS}** words.")
#         elif wc < MIN_WORDS:
#             feedback.info(f"Current word count: **{wc}**. Please add **{remaining}** more words.")
#         else:
#             feedback.success(f"Great — word count is **{wc}**. You can submit now.")

#     if submitted:
#         if not clean:
#             feedback.warning("Comment cannot be empty.")
#         elif wc < MIN_WORDS:
#             feedback.warning(
#                 f"Your comment is **{wc}** words. Please add **{remaining}** more words (minimum {MIN_WORDS}).")
#             # IMPORTANT: we do NOT clear comment_draft, so they keep what they wrote
#         else:
#             # Mark success
#             st.session_state.has_commented = True
#             st.session_state.comment_n += 1

#             # ✅ Log ONLY the comment (minimal logging)
#             log_event(
#                 "comment_posted",
#                 title=f"comment_{st.session_state.comment_n}",
#                 payload={
#                     "comment_text": clean,
#                     "word_count": wc,
#                 },
#             )

#             feedback.success("Comment submitted. You can now continue to the survey.")
#     st.markdown("---")

#     if st.session_state.has_commented:
#         if st.button("Continue to survey"):
#             st.session_state.stage = "survey"
#             st.rerun()
#     else:
#         # only show a gentle reminder BEFORE they've commented
#         st.caption("You must submit at least **one comment** (minimum **50 words**) before continuing to the survey.")

#     # Vote pill (tight spacing via extra columns)
#     # with st.container():
#     #     st.markdown("<div id='vote-row-anchor'></div>", unsafe_allow_html=True)
#     #     cols = st.columns([1, 0.25, 1, 8], gap="small")
#     #     with cols[0]:
#     #         if st.button("▲", key="up_btn"):
#     #             apply_vote("up")
#     #             st.rerun()
#     #     with cols[1]:
#     #         st.markdown(
#     #             f"<div style='display:flex;justify-content:center;align-items:center;height:100%;'>"
#     #             f"<span class='vote-score'>{st.session_state.vote_count}</span></div>",
#     #             unsafe_allow_html=True,
#     #         )
#     #     with cols[2]:
#     #         if st.button("▼", key="down_btn"):
#     #             apply_vote("down")
#     #             st.rerun()
#     #     inject_vote_css(st.session_state.user_vote)

#     # st.divider()
#     #
#     # st.subheader("Add your comment")
#     # with st.form("comment_form", clear_on_submit=True):
#     #     comment_txt = st.text_area(
#     #         "Write your comment (minimum 50 words):",
#     #         key="comment_draft",
#     #         height=180,
#     #         placeholder=(
#     #             "Please write at least 50 words.\n"
#     #             "Tip: describe what happened, how you feel about it, and what you would suggest."
#     #         ),
#     #         help="Your comment must be at least 50 words to proceed."
#     #     )
#     #
#     #     # wc = len(comment_txt.)
#     #     # remaining = max(0, MIN_WORDS - wc)
#     #     # txt = st.text_area("", placeholder="Write something…", height=120)
#     #
#     #     clean = (comment_txt or "").strip()
#     #     wc = len(comment_txt.split())
#     #     # remaining = max(0, 50 - wc)
#     #     # st.caption(f"Word count: **{wc}**  |  Remaining: **{remaining}**")
#     #
#     #     # Submit button (enabled only when enough words)
#     #     can_submit = wc >= 50 and comment_txt.strip() != ""
#     #     submitted = st.form_submit_button("Post comment")
#     #
#     # if submitted:
#     #
#     #     if not clean:
#     #         st.warning("Comment cannot be empty.")
#     #     if not can_submit:
#     #         st.warning("Comment must be longer than 50 words.")
#     #     else:
#     #         ts = utc_now_iso()
#     #         st.session_state.comments.append((ts, clean))
#     #         # ✅ Minimal logging: log comment only
#     #         log_event(
#     #             "comment_posted",
#     #             title=f"comment_{len(st.session_state.comments)}",
#     #             payload={
#     #                 "comment_text": clean,
#     #                 "comment_length": len(clean),
#     #                 "current_score": st.session_state.vote_count,
#     #                 "current_vote": st.session_state.user_vote,
#     #             },
#     #         )
#     #         st.success("Comment posted!")

#     # if st.session_state.comments:
#     #     st.subheader("Your comments (only you can see these)")
#     #     for ts, text in reversed(st.session_state.comments):
#     #         with st.expander(f"🗨️ {ts}", expanded=False):
#     #             st.markdown(text)

#     # st.markdown("---")
#     # if st.button("Continue to survey"):
#     #     if not st.session_state.has_commented:
#     #         st.info("Please post at least **one comment** to continue to the survey.")
#     #         return
#     #     st.session_state.stage = "survey"
#     #     st.rerun()
#     # else:
#     #     st.info("Please post at least **one comment** to continue to the survey.")

#     # render_debug_box()


# # =============================================================================
# # SURVEY PAGE
# # =============================================================================
# def likert7(question: str, key: str) -> Optional[int]:
#     st.markdown(f"**{question}**")
#     return st.radio("", options=[1, 2, 3, 4, 5, 6, 7], horizontal=True, index=None, key=key, label_visibility="collapsed")


# def survey_page():
#     render_banner()
#     st.title("Survey")
#     st.caption("Please answer all questions.")

#     with st.form("survey_form"):
#         st.subheader("Manipulation check")
#         mc_gender = st.radio("The entrepreneur in the post was:", ["Female", "Male"], index=None, horizontal=True)
#         mc_topic = st.radio("The post was mainly about:", ["Work-life balance", "Business difficulty"], index=None, horizontal=True)

#         st.subheader("Attention checks")
#         st.markdown("**What is the fifth word in the following sentence:**")
#         st.markdown(f"> {ATTENTION_CHECK_1_SENTENCE}")
#         att1 = st.radio("", ATTENTION_CHECK_1_OPTIONS, index=None, horizontal=True, label_visibility="collapsed")
#         att2 = st.radio(
#             "What is your favorite fruit? Please select Orange to show that you are paying attention to this question.",
#             ATTENTION_CHECK_2_OPTIONS,
#             index=None,
#             horizontal=True,
#         )

#         st.subheader("Online activity")
#         online = {}
#         st.markdown("**How much do you use the following sites, apps, services, or games to connect or interact with other people?**")
#         for site in ONLINE_SITES:
#             online[site] = st.radio(site, ONLINE_SCALE, index=None, horizontal=True, key=f"online_{site}")

#         st.subheader("G-V congruity scale (1–7)")
#         st.caption("1 = Strongly disagree, 7 = Strongly agree")
#         gv1 = likert7("What this person talked about is common for male entrepreneurs in the venturing process.", "gv1")
#         gv2 = likert7("It is common for male entrepreneurs to experience what this person talked about in the venturing process.", "gv2")
#         gv3 = likert7("Male entrepreneurs are likely to experience what this person talked about in the venturing process.", "gv3")

#         st.subheader("Demographics")
#         birth_year = st.text_input("What is your birth year? (1960–2005)", placeholder="e.g., 1998")
#         gender = st.selectbox("What is your gender?", ["female", "male", "third gender", "transgender"], index=None, placeholder="Select…")
#         education = st.selectbox(
#             "What’s your highest level of formal education?",
#             [
#                 "High school degree or below",
#                 "Associated or technical degree",
#                 "Bachelor degree",
#                 "Master degree",
#                 "Doctorate degree",
#             ],
#             index=None,
#             placeholder="Select…",
#         )
#         ent_years = st.text_input("How many years of entrepreneurial experience do you have? (0–50)", placeholder="e.g., 3")
#         work_years = st.text_input("How many years of work experience do you have? (0–50)", placeholder="e.g., 10")

#         submit = st.form_submit_button("Submit survey")

#     if not submit:
#         # render_debug_box()
#         return

#     # ---- validation ----
#     def blank(x: Any) -> bool:
#         return x is None or (isinstance(x, str) and x.strip() == "")

#     missing = []
#     for label, val in [
#         ("MC gender", mc_gender),
#         ("MC topic", mc_topic),
#         ("Attention check 1", att1),
#         ("Attention check 2", att2),
#         ("GV1", gv1),
#         ("GV2", gv2),
#         ("GV3", gv3),
#         ("Birth year", birth_year),
#         ("Gender", gender),
#         ("Education", education),
#         ("Entrepreneurial years", ent_years),
#         ("Work years", work_years),
#     ]:
#         if blank(val):
#             missing.append(label)
#     for site in ONLINE_SITES:
#         if blank(online.get(site)):
#             missing.append(f"Online: {site}")
#     if missing:
#         st.error("Please complete all required questions: " + ", ".join(missing))
#         return

#     # numeric checks
#     errs = []
#     try:
#         by = int(str(birth_year).strip())
#         if by < 1960 or by > 2005:
#             errs.append("Birth year must be 1960–2005")
#     except Exception:
#         errs.append("Birth year must be an integer")
#     try:
#         ey = int(str(ent_years).strip())
#         if ey < 0 or ey > 50:
#             errs.append("Entrepreneurial experience must be 0–50")
#     except Exception:
#         errs.append("Entrepreneurial experience must be an integer")
#     try:
#         wy = int(str(work_years).strip())
#         if wy < 0 or wy > 50:
#             errs.append("Work experience must be 0–50")
#     except Exception:
#         errs.append("Work experience must be an integer")
#     if errs:
#         for e in errs:
#             st.error(e)
#         return

#     # compute correctness flags
#     att1_ok = (att1 == ATTENTION_CHECK_1_CORRECT)
#     att2_ok = (att2 == ATTENTION_CHECK_2_CORRECT)
#     mc_gender_ok = (mc_gender == "Male")
#     mc_topic_ok = (mc_topic == "Business difficulty")

#     responses = {
#         "condition": CONDITION,
#         "manipulation_check": {
#             "gender_answer": mc_gender,
#             "topic_answer": mc_topic,
#             "gender_correct": mc_gender_ok,
#             "topic_correct": mc_topic_ok,
#         },
#         "attention_checks": {
#             "att1_answer": att1,
#             "att1_correct": att1_ok,
#             "att2_answer": att2,
#             "att2_correct": att2_ok,
#         },
#         "online_activity": online,
#         "gv": {"gv1": gv1, "gv2": gv2, "gv3": gv3},
#         "demographics": {
#             "birth_year": by,
#             "gender": gender,
#             "education": education,
#             "entrepreneurial_years": ey,
#             "work_years": wy,
#         },
#         "comment_count": len(st.session_state.comments),
#         "final_vote_score": st.session_state.vote_count,
#         "final_user_vote": st.session_state.user_vote,
#     }

#     # ✅ Minimal logging: log survey only
#     log_event("survey_submitted", title="survey", payload=responses)

#     st.session_state.stage = "done"
#     st.rerun()


# def done_page():
#     render_banner()
#     st.title("Finished")
#     st.success("Thanks — your responses have been recorded.")
#     st.caption("You may now close this tab.")
#     # render_debug_box()


# # =============================================================================
# # ROUTER
# # =============================================================================
# def main():
#     # Auto PID from Prolific URL


#     if st.session_state.get("prolific_id") is None:
#         qp = get_query_param("PROLIFIC_PID")
#         if qp and qp.strip():
#             st.session_state.prolific_id = qp.strip()
#             if not st.session_state.get("_logged_auto_pid"):
#                 log_event("session_start", payload={"pid": st.session_state.prolific_id, "source": "query_param"})
#                 st.session_state._logged_auto_pid = True
#             st.session_state.stage = "experiment"

#     stage = st.session_state.stage
#     if st.session_state.stage == "consent":
#         render_consent_page()
#         return
#     if stage == "pid":
#         pid_page(); return
#     if stage == "experiment":
#         experiment_page(); return
#     if stage == "survey":
#         survey_page(); return
#     done_page()


# if __name__ == "__main__":
#     main()

CONDITION = "M_BL"

SUBREDDIT = "r/business"
DAYS_AGO = 7
AUTHOR_USERNAME = "Fit_Bet_1261"
POSTED_BY_NAME = "David"

POST_TITLE = "Running a business is difficult!"
POST_BODY_MD = """
Running a business is difficult! I am a small business owner. For the last two years, I’ve answered the calls, given the quotes, and assisted in the labor. 100% focus on being professional, on-time, and accurate with quotes/pricing.  We have received nothing but 5 star reviews on yelp, google, Facebook, etc... I’ve built up around 20 reviews on yelp which are all 5 star reviews. Unfortunately 14 out of the 20 are hidden and not shown.

They call me every other day even though I’ve told them again and again that they can email me offers. I don’t have time to answer disguised calls from reps all day. I understand how yelp works... I understand that i got more customer views when I was advertising with yelp... i understand how to setup everything on yelp and do not need any assistance...

The harassment, call number disguising, the taking down of reviews, removing service locations... it’s not good business. Now today, I log in... and it keeps clearing my services list.

I’m wondering how many others this happens to. Google Reviews is only going to improve, and yelp will be nothing... I’m done with them.
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
st.set_page_config(page_title="Reddit-style Study (M_BL)", page_icon="🧪", layout="centered")

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
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
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

    sheet = client.open("ETP-MALE-BD").sheet1
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

        st.caption("If your Google Sheet isn’t updating, the #1 cause is: the sheet is not shared with the service account email.")

        if st.button("Test Google Sheet write"):
            log_event("debug_test", title="hello", payload={"ts": utc_now_iso()})
            st.info("Wrote a test row (also saved locally). Refresh your Google Sheet.")

def render_consent_page():
    st.title("Study Information and Consent")

    st.markdown("""
    **Study Overview and Consent**

    You are invited to participate in a research study about **entrepreneurial interactions**.
    You must be **18 years or older** to participate.

    In this study, you will read a short post from a Reddit discussion thread in which an entrepreneur describes their experience
    (e.g., business challenges or work–life balance issues). After reading the post, you will be asked
    to **write a brief comment as if replying in the thread** and then **answer several questions** about your reactions.

    The study will take approximately **10–15 minutes**. There will be **no follow-up questionnaire**.

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

    elapsed = int(time.time() - st.session_state.instr_start_ts)
    remaining = max(0, MIN_SECONDS - elapsed)

    st.caption(f"Please stay on this page for at least {MIN_SECONDS} seconds. "
               f"Remaining: {remaining}s")

    if st.button("I agree and continue"):
        if remaining > 0:
            st.warning(f"Please wait {remaining}s before continuing.")
            return
        if agree:
            st.session_state.stage = "practice"
            st.rerun()
        else:
            st.warning("You must agree to participate before continuing.")


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

    # Use a form so values persist and are submitted together
    with st.form("practice_form", clear_on_submit=False):
        # q1 = st.text_input(
        #     "1) Please type the **5th word** in this sentence:\n\n"
        #     "“Entrepreneurs often work hard because success takes time.”",
        #     key="practice_q1",
        # )
        # q2 = st.radio(
        #     "2) Please select **Orange** from the options below:",
        #     options=["Apple", "Orange", "Banana", "Grape"],
        #     index=None,
        #     key="practice_q2",
        # )

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

    if submitted:
        st.session_state.practice_attempts += 1

        ans1 = att1 #(q1 or "").strip()
        ans2 = att2 #q2

        pass1 = (ans1.lower() == "because")
        pass2 = (ans2 == "Orange")
        passed = pass1 and pass2

        # ✅ Record to Google Sheet (one row per attempt; includes pass/fail)
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

        # if not passed:
        #     st.error("One or more answers were incorrect. Please try again.")
        #     st.info("Tip: For Q1, count the words in the sentence carefully.")
        #     return

        # ✅ Passed → go to experiments
        st.session_state.stage = "pid"
        st.session_state.scroll_top_next = True  # if you use the scroll-to-top flag
        st.rerun()
        
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
        st.session_state.stage = "experiment"
        st.rerun()

    # render_debug_box()



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

    st.markdown(f"**Below, you will read a thread posted by {POSTED_BY_NAME} on social media.**")
    render_post_meta()

    st.title(POST_TITLE)
    st.markdown(POST_BODY_MD)
    st.divider()

    st.subheader("Add your comment")

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
            placeholder=(
                "Minimum 50 words.\n"
                "Tip: How would you comment on David’s thread about his business difficulties?"
            ),
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
    return st.radio("", options=[1, 2, 3, 4, 5, 6, 7], horizontal=True, index=None, key=key, label_visibility="collapsed")


def survey_page():
    render_banner()
    if st.session_state.pop("scroll_top_next", False):
        scroll_to_top_once()
    st.title("Survey")
    st.caption("Please answer all questions.")

    with st.form("survey_form"):
        # st.subheader("Manipulation check")
        mc_gender = st.radio("The entrepreneur in the post was:", ["Female", "Male"], index=None, horizontal=True)
        mc_topic = st.radio("The post was mainly about:", ["Work-life balance", "Business difficulty"], index=None, horizontal=True)

        # st.subheader("Attention checks")
        # st.markdown("**What is the fifth word in the following sentence:**")
        # st.markdown(f"> {ATTENTION_CHECK_1_SENTENCE}")
        # att1 = st.radio("", ATTENTION_CHECK_1_OPTIONS, index=None, horizontal=True, label_visibility="collapsed")
        # att2 = st.radio(
        #     "What is your favorite fruit? Please select Orange to show that you are paying attention to this question.",
        #     ATTENTION_CHECK_2_OPTIONS,
        #     index=None,
        #     horizontal=True,
        # )

        # st.subheader("Online activity")
        online = {}
        st.markdown("**How much do you use the following sites, apps, services, or games to connect or interact with other people?**")
        for site in ONLINE_SITES:
            online[site] = st.radio(site, ONLINE_SCALE, index=None, horizontal=True, key=f"online_{site}")

        # st.subheader("G-V congruity scale (1–7)")
        st.caption("1 = Strongly disagree, 7 = Strongly agree")
        gv1 = likert7("What this person talked about is common for men entrepreneurs in the venturing process.", "gv1")
        gv2 = likert7("It is common for men entrepreneurs to experience what this person talked about in the venturing process.", "gv2")
        gv3 = likert7("Men entrepreneurs are likely to experience what this person talked about in the venturing process.", "gv3")

        # st.subheader("Demographics")
        birth_year = st.text_input("What is your birth year? (1960–2007)", placeholder="e.g., 1998")
        gender = st.selectbox("What is your gender?", ["female", "male", "third gender", "transgender"], index=None, placeholder="Select…")
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
        )
        ent_years = st.text_input("How many years of entrepreneurial experience do you have? (0–50)", placeholder="e.g., 3")
        work_years = st.text_input("How many years of work experience do you have? (0–50)", placeholder="e.g., 10")

        submit = st.form_submit_button("Submit survey")

    if not submit:
        # render_debug_box()
        return

    # ---- validation ----
    def blank(x: Any) -> bool:
        return x is None or (isinstance(x, str) and x.strip() == "")

    missing = []
    for label, val in [
        ("MC gender", mc_gender),
        ("MC topic", mc_topic),
        # ("Attention check 1", att1),
        # ("Attention check 2", att2),
        ("GV1", gv1),
        ("GV2", gv2),
        ("GV3", gv3),
        ("Birth year", birth_year),
        ("Gender", gender),
        ("Education", education),
        ("Entrepreneurial years", ent_years),
        ("Work years", work_years),
    ]:
        if blank(val):
            missing.append(label)
    for site in ONLINE_SITES:
        if blank(online.get(site)):
            missing.append(f"Online: {site}")
    if missing:
        st.error("Please complete all required questions: " + ", ".join(missing))
        return

    # numeric checks
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

    # compute correctness flags
    # att1_ok = (att1 == ATTENTION_CHECK_1_CORRECT)
    # att2_ok = (att2 == ATTENTION_CHECK_2_CORRECT)
    mc_gender_ok = (mc_gender == "Male")
    mc_topic_ok = (mc_topic == "Business difficulty")

    responses = {
        "condition": CONDITION,
        "manipulation_check": {
            "gender_answer": mc_gender,
            "topic_answer": mc_topic,
            "gender_correct": mc_gender_ok,
            "topic_correct": mc_topic_ok,
        },
        # "attention_checks": {
        #     "att1_answer": att1,
        #     "att1_correct": att1_ok,
        #     "att2_answer": att2,
        #     "att2_correct": att2_ok,
        # },
        "online_activity": online,
        "gv": {"gv1": gv1, "gv2": gv2, "gv3": gv3},
        "demographics": {
            "birth_year": by,
            "gender": gender,
            "education": education,
            "entrepreneurial_years": ey,
            "work_years": wy,
        },
        "comment_count": len(st.session_state.comments),
        # "final_vote_score": st.session_state.vote_count,
        # "final_user_vote": st.session_state.user_vote,
    }

    # ✅ Minimal logging: log survey only
    log_event("survey_submitted", title="survey", payload=responses)

    st.session_state.stage = "done"
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
    # Auto PID from Prolific URL


    if st.session_state.get("prolific_id") is None:
        qp = get_query_param("PROLIFIC_PID")
        if qp and qp.strip():
            st.session_state.prolific_id = qp.strip()
            if not st.session_state.get("_logged_auto_pid"):
                log_event("session_start", payload={"pid": st.session_state.prolific_id, "source": "query_param"})
                st.session_state._logged_auto_pid = True
            st.session_state.stage = "experiment"

    stage = st.session_state.stage
    if st.session_state.stage == "consent":
        render_consent_page()
        return
    if st.session_state.stage == "practice":
        practice_questions_page()
        return
    if stage == "pid":
        pid_page(); return
    if stage == "experiment":
        experiment_page(); return
    if stage == "survey":
        survey_page(); return
    done_page()


if __name__ == "__main__":
    main()

