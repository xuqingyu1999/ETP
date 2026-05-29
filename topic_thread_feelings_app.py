
import base64
import csv
import html
import hashlib
import io
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
# APP SETTINGS
# =============================================================================
CONDITION = "TOPIC_FEELINGS_V3_RANDOM_STORY_4COMMENTS"  # logged as "variant" in Google Sheet

# Neutral identities shown in the prompt (not necessarily inside the post text)
POSTED_BY_NAME = "Alex"
AUTHOR_USERNAME = "HiddenBadger74"

# Commenter identity (neutral)
COMMENTER_USERNAME = "SageOtter21"
COMMENT_DAYS_AGO = 5

# UI meta
SUBREDDIT = "r/Entrepreneur"
POST_DAYS_AGO = 3

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

# Topic choices (participant is randomly assigned to ONE group after passing attention check)
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

# =============================================================================
# STREAMLIT CONFIG + CSS
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
  color: #111 !important; /* readable on light highlight even in dark theme */
}

/* Slightly more Reddit-y typography */
:root { --banner-font-size: 2rem; }

/* Thread typography */
.post-title {
  font-size: 1.35rem;
  font-weight: 800;
  margin: 6px 0 10px 0;
}
.post-body {
  font-size: 1rem;
  line-height: 1.45;
  white-space: pre-wrap;
}
.meta-muted {
  font-size: 0.95rem;
  opacity: 0.72;
}
.avatar-circle {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #e9ecef;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
}
.comment-wrap {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
.hr-tight { margin: 0 0 20px 0; }

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
            qp = st.experimental_get_query_params()
            vals = qp.get(name)
            return vals[0] if vals else None
        except Exception:
            return None



def _is_truthy(v: Optional[str]) -> bool:
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def debug_overrides_enabled() -> bool:
    """
    Debug/testing overrides are DISABLED by default so participants cannot manipulate random assignment.
    Enable in either of two ways:
      - Add ?debug=1 in the URL (recommended for testing), OR
      - Set DEBUG_OVERRIDES=true in Streamlit secrets.
    """
    try:
        if bool(st.secrets.get("DEBUG_OVERRIDES", False)):
            return True
    except Exception:
        pass
    return _is_truthy(get_query_param("debug"))


def get_assignment_overrides() -> Dict[str, Optional[str]]:
    """
    Read optional testing overrides from URL query params.
    Examples (only works when debug_overrides_enabled()):
      ?debug=1&topic=Financing
      ?debug=1&topic=Legal&support_combo=high_high
      ?debug=1&story_id=<some_id>&support_combo=low_low
    """
    if not debug_overrides_enabled():
        return {}

    topic = get_query_param("topic") or get_query_param("force_topic")
    category = get_query_param("category") or get_query_param("cat")
    story_id = get_query_param("story_id") or get_query_param("id")
    support_combo = (
        get_query_param("support_combo")
        or get_query_param("combo")
        or get_query_param("comment_type")
    )
    reset_token = get_query_param("reset") or get_query_param("reroll")

    return {
        "topic": topic,
        "category": category,
        "story_id": story_id,
        "support_combo": support_combo,
        "reset_token": reset_token,
    }


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
    if not local_path.exists():
        return ""
    suffix = local_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
    b64 = base64.b64encode(local_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# =============================================================================
# GOOGLE SHEETS LOGGING
# =============================================================================
def get_credentials_from_secrets() -> ServiceAccountCredentials:
    creds = st.secrets.get("GOOGLE_CREDENTIALS", None)
    if creds is None:
        raise RuntimeError("Missing GOOGLE_CREDENTIALS in Streamlit secrets.")
    if isinstance(creds, str):
        creds = json.loads(creds)

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    return ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)


def _get_sheet1():
    spreadsheet_name = st.secrets.get("SPREADSHEET_NAME", "ETP-TOPIC-FEELINGS")
    creds = get_credentials_from_secrets()
    client = gspread.authorize(creds)
    sh = client.open(spreadsheet_name)
    return sh.sheet1


def _append_local(row: List[Any]) -> None:
    """Fallback: append to a local CSV for debugging if GSheet fails."""
    path = Path(__file__).parent / "local_log_fallback.csv"
    with open(path, "a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(row)


def save_to_gsheet(row: List[Any]) -> None:
    last_error = None
    for attempt in range(3):
        try:
            ws = _get_sheet1()
            ws.append_row(row, value_input_option="RAW")
            st.session_state.pop("_gsheet_error", None)
            return
        except Exception as e:
            last_error = e
            st.session_state["_gsheet_error"] = (
                f"GSheet write attempt {attempt + 1}/3 failed: {e}"
            )
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))

    try:
        _append_local(row)
        st.session_state["_gsheet_error"] = (
            f"GSheet write failed after 3 attempts; saved to local fallback: {last_error}"
        )
    except Exception as e:
        st.session_state["_gsheet_error"] = (
            f"GSheet write failed after 3 attempts; local fallback also failed: {e}"
        )


def _secret_or_env(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        value = st.secrets.get(name, None)
    except Exception:
        value = None
    return value or os.getenv(name) or default


def get_completion_url() -> Optional[str]:
    return _secret_or_env("COMPLETION_URL_STUDY2")


def get_prolific_reward() -> Optional[str]:
    reward = _secret_or_env("PROLIFIC_REWARD_STUDY2")
    if reward is None:
        return None
    reward = str(reward).strip()
    return reward or None


def log_event(event_type: str, title: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
    payload = payload or {}
    pid = st.session_state.get("prolific_id") or ""
    start = st.session_state.get("start_time") or ""
    ts = utc_now_iso()

    row = [
        pid,                          # id
        start,                        # start
        CONDITION,                    # variant
        ts,                           # timestamp
        event_type,                   # type
        title or "",                  # title
        json.dumps(payload, ensure_ascii=False),  # url (payload)
    ]
    save_to_gsheet(row)


# =============================================================================
# REDDIT-LIKE UI
# =============================================================================
APP_DIR = Path(__file__).parent
REDDIT_LOGO_PATH = APP_DIR / "reddit_logo.png"
AVATAR_PATH = APP_DIR / "avatar.jpg"


def render_banner():
    logo_uri = to_data_uri(REDDIT_LOGO_PATH)
    if logo_uri:
        logo_html = f'<img src="{logo_uri}" style="width:36px;height:36px;">'
    else:
        # fallback if the image isn't present
        logo_html = '<div style="width:36px;height:36px;border-radius:8px;background:#ff4500;"></div>'

    st.markdown(
        f"""
<div style="display:flex;align-items:center;gap:10px;width:100%;padding:16px 0 24px 0;">
  {logo_html}
  <span style="font-family:Roboto,Arial,sans-serif;font-size:var(--banner-font-size);line-height:1.1;font-weight:700;color:#FF4500;">reddit</span>
</div>
<hr class="hr-tight">
""",
        unsafe_allow_html=True,
    )


def render_post_meta():
    avatar_uri = to_data_uri(AVATAR_PATH)
    if avatar_uri:
        avatar_html = f'<img src="{avatar_uri}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">'
    else:
        avatar_html = f'<div class="avatar-circle" style="width:40px;height:40px;">{html.escape((AUTHOR_USERNAME[:1] or "?").upper())}</div>'

    st.markdown(
        f"""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
  {avatar_html}
  <div style="line-height:1.1;">
    <div style="font-weight:700;">{html.escape(SUBREDDIT)} &middot; {POST_DAYS_AGO} days ago</div>
    <div class="meta-muted">{html.escape(AUTHOR_USERNAME)}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_text_block(text: str) -> None:
    safe = html.escape(text or "")
    st.markdown(f'<div class="post-body">{safe}</div>', unsafe_allow_html=True)


def render_post_content(title: str, body: str) -> None:
    safe_title = html.escape(title or "")
    st.markdown(f'<div class="post-title">{safe_title}</div>', unsafe_allow_html=True)
    if body:
        render_text_block(body)


def render_comment(comment_text: str):
    letter = (COMMENTER_USERNAME[:1] or "?").upper()
    safe_user = html.escape(COMMENTER_USERNAME)
    safe_text = html.escape(comment_text or "")

    st.markdown(
        f"""
<div class="comment-wrap">
  <div class="avatar-circle">{html.escape(letter)}</div>
  <div style="flex:1;">
    <div class="meta-muted">
      <span style="font-weight:800;">{safe_user}</span>
      &nbsp;&middot;&nbsp; {COMMENT_DAYS_AGO} days ago
    </div>
    <div class="post-body" style="margin-top:4px;">{safe_text}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_thread_context(thread: Dict[str, str], subtopic: str, *, show_post_body: bool = True) -> None:
    """
    Show the post (title + optionally body) and comment in a consistent way.
    Used on both the thread page and survey pages so participants can revisit the comment.
    """
    render_post_meta()
    render_post_content(thread.get("title", ""), thread.get("body", "") if show_post_body else "")
    st.divider()
    st.markdown("**Comment**")
    render_comment(thread.get("comment", ""))


# =============================================================================

# CSV LOADER + RANDOM ASSIGNMENT (NO PARTICIPANT CHOICE)
# =============================================================================
def _pick_column(keys: List[str], candidates: List[str]) -> Optional[str]:
    lower_map = {k.lower().strip(): k for k in keys}
    for c in candidates:
        if c.lower().strip() in lower_map:
            return lower_map[c.lower().strip()]
    return None


def _decode_bytes(b: bytes) -> str:
    # Robustly handle Excel-exported CSV encodings
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _to_bool(x: Any) -> Optional[bool]:
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("true", "t", "1", "yes", "y"):
        return True
    if s in ("false", "f", "0", "no", "n"):
        return False
    return None


def _stable_story_id(topic: str, title: str, body: str) -> str:
    base = f"{topic}\n{title}\n{body}".encode("utf-8", errors="ignore")
    return hashlib.sha1(base).hexdigest()[:12]


def load_threads_csv(path: str, *, uploaded_bytes: Optional[bytes] = None) -> List[Dict[str, Any]]:
    """
    Expected (recommended) columns for this experiment:
      - topic
      - post_title
      - post_body
      - comment
      - informational_support (low/high)
      - emotional_support (low/high)
      - support_combo (e.g., low_low, low_high, high_low, high_high)
      - is_original_comment (True/False)

    Backward-compatible with older 3-column format: topic, post, comment.
    """
    if uploaded_bytes is not None:
        text = _decode_bytes(uploaded_bytes)
        source_name = "uploaded"
    else:
        with open(path, "rb") as fh:
            text = _decode_bytes(fh.read())
        source_name = os.path.basename(path)

    reader = csv.DictReader(io.StringIO(text))
    dict_rows = list(reader)
    keys = reader.fieldnames or []

    if not dict_rows:
        return []

    topic_col = _pick_column(keys, ["topic", "subtopic", "topic_name"])
    comment_col = _pick_column(keys, ["comment", "reply", "comment_md", "comment_text", "response"])
    title_col = _pick_column(keys, ["post_title", "title"])
    body_col = _pick_column(keys, ["post_body", "body"])
    # fallback combined post column (3-col format)
    post_col = _pick_column(keys, ["post", "thread", "post_md", "post_text", "postcontent"])
    link_col = _pick_column(keys, ["link_id", "id", "thread_id", "reddit_id", "story_id"])

    info_col = _pick_column(keys, ["informational_support", "info_support", "informational"])
    emo_col = _pick_column(keys, ["emotional_support", "emo_support", "emotional"])
    combo_col = _pick_column(keys, ["support_combo", "comment_type", "support_type", "combo"])
    orig_col = _pick_column(keys, ["is_original_comment", "original_comment", "is_original"])

    # If exactly 3 columns and any required missing, assume order.
    if (topic_col is None or comment_col is None or (title_col is None and body_col is None and post_col is None)) and len(keys) == 3:
        topic_col = topic_col or keys[0]
        post_col = post_col or keys[1]
        comment_col = comment_col or keys[2]

    threads: List[Dict[str, Any]] = []
    for idx, r in enumerate(dict_rows, start=1):
        topic = (r.get(topic_col or "", "") or "").strip()
        if not topic:
            continue

        title = ""
        body = ""
        if title_col and body_col:
            title = (r.get(title_col, "") or "").strip()
            body = (r.get(body_col, "") or "").strip()
        else:
            post_raw = (r.get(post_col or "", "") or "").strip()
            if post_raw:
                parts = post_raw.splitlines()
                title = (parts[0] or "").strip()
                body = "\n".join(parts[1:]).strip() if len(parts) > 1 else ""

        comment = (r.get(comment_col or "", "") or "").strip()

        # Normalize line breaks
        title = title.replace("\r\n", "\n").replace("\r", "\n")
        body = body.replace("\r\n", "\n").replace("\r", "\n")
        comment = comment.replace("\r\n", "\n").replace("\r", "\n")

        # Comment meta (optional)
        info = (r.get(info_col, "") or "").strip().lower() if info_col else ""
        emo = (r.get(emo_col, "") or "").strip().lower() if emo_col else ""
        combo = (r.get(combo_col, "") or "").strip().lower() if combo_col else ""
        is_orig = _to_bool(r.get(orig_col)) if orig_col else None

        link_id = (r.get(link_col, "") or "").strip() if link_col else ""

        story_id = link_id or _stable_story_id(topic, title, body)
        # comment variant id should differentiate the 4 comments under the same story
        comment_variant_id = f"{story_id}::{combo or f'v{idx}'}"

        threads.append(
            {
                "topic": topic,
                "title": title,
                "body": body,
                "comment": comment,
                "story_id": story_id,
                "thread_id": story_id,  # keep legacy field name for logging/UI
                "comment_variant_id": comment_variant_id,
                "informational_support": info,
                "emotional_support": emo,
                "support_combo": combo,
                "is_original_comment": is_orig,
                "source": source_name,
            }
        )

    return threads


@st.cache_data(show_spinner=False)
def get_threads_data() -> Tuple[List[Dict[str, Any]], str]:
    """Load threads from a path or from an uploaded CSV in session_state."""
    # 1) Path from secrets/env (preferred)
    default_path = str(Path(__file__).parent / "topic_threads_4_comments_low_low_revised.csv")
    csv_path = st.secrets.get("TOPIC_CSV_PATH", default_path)

    # 2) If the default path doesn't exist, fall back to the older filename
    p = Path(csv_path)
    if not p.is_absolute():
        p = (Path(__file__).parent / p).resolve()

    if not p.exists():
        legacy = (Path(__file__).parent / "topic_threads.csv").resolve()
        if legacy.exists():
            p = legacy

    uploaded = st.session_state.get("uploaded_threads_csv_bytes")
    if uploaded:
        try:
            return load_threads_csv(str(p), uploaded_bytes=uploaded), "uploaded"
        except Exception as e:
            return [], f"uploaded_error: {e}"

    try:
        return load_threads_csv(str(p)), str(p)
    except Exception as e:
        return [], f"file_error: {e}"


def _topic_to_category_map() -> Dict[str, str]:
    # Case-insensitive mapping
    m: Dict[str, str] = {}
    for cat, topics in TOPIC_GROUPS.items():
        for t in topics:
            m[str(t).strip().lower()] = cat
    return m


def _normalize_category(label: str) -> Optional[str]:
    s = (label or "").strip().lower()
    if s in {"business", "biz"}:
        return "Business"
    if s in {"worklife balance", "work-life balance", "work life balance", "wlb", "worklife", "work-life", "work life"}:
        return "Worklife balance"
    return None


def _assign_random_story_and_comment() -> Optional[Dict[str, Any]]:
    """Assign scenario (Business vs Worklife), then a story, then 1 of its 4 comment types.

    In debug/testing mode (?debug=1), you can force assignment with query params:
      - topic=<Financing|Legal|...>
      - story_id=<id>
      - support_combo=<low_low|low_high|high_low|high_high>
      - reset=<token>  (optional, forces re-roll once when token changes)
    """
    threads, source = get_threads_data()
    st.session_state["_threads_source"] = source

    if not threads:
        return None

    overrides = get_assignment_overrides()
    debug = debug_overrides_enabled()

    forced_topic = (overrides.get("topic") or "").strip()
    forced_category_raw = (overrides.get("category") or "").strip()
    forced_story_id = (overrides.get("story_id") or "").strip()
    forced_combo = (overrides.get("support_combo") or "").strip()

    topic_to_cat = _topic_to_category_map()

    # Optional: filter rows to a forced topic (debug only)
    filtered_threads = threads
    if debug and forced_topic:
        ft = forced_topic.lower()
        filtered_threads = [t for t in threads if (t.get("topic") or "").strip().lower() == ft]
        if not filtered_threads:
            st.warning(f"[Debug] No rows found for topic='{forced_topic}'. Falling back to random assignment.")
            filtered_threads = threads

    # Build: category -> story_id -> [variants]
    cat_story_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for t in filtered_threads:
        topic = (t.get("topic") or "").strip().lower()
        cat = topic_to_cat.get(topic)
        if not cat:
            continue
        story_id = t.get("story_id") or t.get("thread_id") or ""
        if not story_id:
            continue
        cat_story_map.setdefault(cat, {}).setdefault(story_id, []).append(t)

    available_cats = [c for c, stories in cat_story_map.items() if stories]
    if not available_cats:
        return None

    # 1) Assign scenario group
    assigned_cat = st.session_state.get("assigned_category")

    forced_cat: Optional[str] = None
    if debug and forced_category_raw:
        forced_cat = _normalize_category(forced_category_raw)
        if forced_cat is None:
            st.warning(f"[Debug] Unknown category='{forced_category_raw}'. Expected 'Business' or 'Worklife balance'.")
    if debug and forced_topic:
        # If topic is valid, it implies a category; used when category isn't explicitly forced.
        implied = topic_to_cat.get(forced_topic.lower())
        if implied:
            forced_cat = forced_cat or implied
        else:
            st.warning(f"[Debug] Unknown topic='{forced_topic}'. It does not map to a category in TOPIC_GROUPS.")

    if debug and forced_cat and forced_cat in available_cats:
        if assigned_cat != forced_cat:
            assigned_cat = forced_cat
            st.session_state.assigned_category = assigned_cat
            log_event(
                "category_assigned",
                title=assigned_cat,
                payload={"assigned_category": assigned_cat, "method": "forced", "overrides": overrides},
            )
    else:
        if assigned_cat not in available_cats:
            assigned_cat = random.choice(available_cats)
            st.session_state.assigned_category = assigned_cat
            log_event(
                "category_assigned",
                title=assigned_cat,
                payload={"assigned_category": assigned_cat, "method": "random"},
            )

    # 2) Assign a story within that scenario
    story_groups = cat_story_map[assigned_cat]
    story_id: str
    if debug and forced_story_id and forced_story_id in story_groups:
        story_id = forced_story_id
    else:
        if debug and forced_story_id and forced_story_id not in story_groups:
            st.warning(f"[Debug] story_id='{forced_story_id}' not found in assigned category '{assigned_cat}'. Using random story.")
        story_id = random.choice(list(story_groups.keys()))

    variants = story_groups[story_id]

    # 3) Assign 1 comment type for that story
    chosen_variant: Dict[str, Any]
    if debug and forced_combo:
        fc = forced_combo.lower()
        candidates = [v for v in variants if (v.get("support_combo") or "").strip().lower() == fc]
        if candidates:
            chosen_variant = random.choice(candidates)
        else:
            st.warning(f"[Debug] support_combo='{forced_combo}' not found for story '{story_id}'. Using random comment variant.")
            chosen_variant = random.choice(variants)
    else:
        chosen_variant = random.choice(variants)

    # Persist assignment
    st.session_state.chosen_subtopic = chosen_variant.get("topic")
    st.session_state.selected_thread = chosen_variant
    st.session_state.exp_view_start_ts = None
    st.session_state.thread_read_elapsed_seconds = None
    st.session_state.pop("_logged_thread_shown", None)

    log_event(
        "story_assigned",
        title=str(story_id),
        payload={
            "assigned_category": assigned_cat,
            "topic": chosen_variant.get("topic"),
            "story_id": story_id,
            "comment_variant_id": chosen_variant.get("comment_variant_id"),
            "support_combo": chosen_variant.get("support_combo"),
            "informational_support": chosen_variant.get("informational_support"),
            "emotional_support": chosen_variant.get("emotional_support"),
            "is_original_comment": chosen_variant.get("is_original_comment"),
            "source": chosen_variant.get("source"),
            "method": "forced" if (debug and overrides and (forced_topic or forced_category_raw or forced_story_id or forced_combo)) else "random",
            "overrides": overrides if (debug and overrides) else None,
        },
    )

    return chosen_variant


def ensure_thread_selected() -> Optional[Dict[str, Any]]:
    """Ensure one assigned (story + comment type) is fixed for this participant.

    In debug mode, if URL query params force a topic/story/support_combo, we clear any existing
    selection that doesn't match, so refreshing the page will respect the override.
    """
    overrides = get_assignment_overrides()
    debug = debug_overrides_enabled()

    if debug and overrides:
        # Optional reset: change ?reset=<token> to force a re-roll once (token can be any string)
        reset_token = overrides.get("reset_token")
        if reset_token:
            last = st.session_state.get("_debug_last_reset_token")
            if str(reset_token) != str(last):
                st.session_state["_debug_last_reset_token"] = str(reset_token)
                for k in [
                    "selected_thread",
                    "assigned_category",
                    "chosen_subtopic",
                    "exp_view_start_ts",
                    "thread_read_elapsed_seconds",
                ]:
                    st.session_state.pop(k, None)
                st.session_state.pop("_logged_thread_shown", None)

        existing = st.session_state.get("selected_thread")
        if existing is not None:
            topic_ok = True
            story_ok = True
            combo_ok = True

            if overrides.get("topic"):
                topic_ok = (existing.get("topic") or "").strip().lower() == overrides["topic"].strip().lower()
            if overrides.get("story_id"):
                story_ok = (existing.get("story_id") or "") == overrides["story_id"]
            if overrides.get("support_combo"):
                combo_ok = (existing.get("support_combo") or "").strip().lower() == overrides["support_combo"].strip().lower()

            if not (topic_ok and story_ok and combo_ok):
                st.session_state.pop("selected_thread", None)

    if st.session_state.get("selected_thread") is not None:
        return st.session_state.selected_thread

    return _assign_random_story_and_comment()


# =============================================================================
# SURVEY WIDGETS
# =============================================================================
def likert8(prompt: str, key: str) -> Optional[int]:
    # Display without numbering and without subheaders; consistent with prior style
    st.markdown(prompt)
    return st.radio(
        label="",
        options=[1, 2, 3, 4, 5, 6, 7, 8],
        index=None,
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )


def blank(x: Any) -> bool:
    if x is None:
        return True
    s = str(x).strip()
    return s == ""


# =============================================================================
# PAGES
# =============================================================================
def consent_page():
    st.title("Study Information and Consent")
    reward = get_prolific_reward()
    reward_sentence = (
        f"You will receive **{reward}** for completing the study."
        if reward
        else "You will receive compensation **as described on Prolific** for completing the study."
    )

    st.markdown(
        f"""
**Study Overview and Consent**

You are invited to participate in a research study about **how entrepreneurs interact on social media**.
You must be **18 years or older** to participate.

In this study, you will:
- Enter your Prolific ID,
- Answer two short attention-check questions,
- You will be randomly assigned to read one short **online thread** (a post and a comment) in which an entrepreneur **shares their experience**,
- Answer questions about **how you would feel** if you were the entrepreneur who posted the thread.

The study will take approximately **5–8 minutes**.

Your participation is **voluntary**. You may stop participating at any time without penalty.
All responses are **anonymous**, and no identifying information will be collected or reported.
De-identified data may be shared with other researchers for academic purposes.

There are **no known risks** associated with this study and no direct benefits to you.
{reward_sentence}

For scientific reasons, full details about the research purpose cannot be provided at this time.
You will be **fully debriefed** after completing the study.

If you have any questions about our research, please contact our team member Hongfei Li (Email: hongfei.li@cuhk.edu.hk) from CUHK.
"""
    )

    agree = st.checkbox("I am at least 18 years old and I agree to participate in this study.")

    st.session_state.setdefault("consent_start_ts", time.time())
    elapsed = int(time.time() - st.session_state.consent_start_ts)
    remaining = max(0, MIN_SECONDS_CONSENT - elapsed)

    countdown = st.empty()
    countdown.caption(
        f"Please stay on this page for at least {MIN_SECONDS_CONSENT} seconds. Remaining: {remaining}s"
    )

    if remaining > 0:
        st.button("I agree and continue", disabled=True)
        time.sleep(1)
        st.rerun()
        return

    if st.button("I agree and continue"):
        if not agree:
            st.warning("You must agree to participate before continuing.")
            return

        st.session_state.stage = "pid"
        st.session_state.scroll_top_next = True
        st.rerun()

def pid_page():
    render_banner()
    st.title("Prolific ID")

    # Try URL param
    qp = get_query_param("PROLIFIC_PID")
    if qp and not st.session_state.get("prolific_id"):
        st.session_state.prolific_id = qp.strip()

    pid = st.text_input("Please enter your Prolific ID:", value=st.session_state.get("prolific_id") or "")
    if st.button("Confirm"):
        pid_clean = (pid or "").strip()
        if not pid_clean:
            st.error("Please enter a valid Prolific ID.")
            return

        st.session_state.prolific_id = pid_clean
        log_event("session_start", title="pid_confirmed", payload={"pid": pid_clean, "session_id": st.session_state.session_id})

        st.session_state.stage = "practice"
        st.session_state.scroll_top_next = True
        st.rerun()


def practice_page():
    render_banner()
    st.title("PRACTICE QUESTIONS")

    st.markdown(
        "Before starting the study, please answer the practice questions below. "
        "These questions help ensure the study is working properly and that responses are attentive."
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
        # Random assignment: scenario (Business vs Worklife balance), story, and comment type
        thread = ensure_thread_selected()
        if thread is None:
            st.error("Could not load the scenario threads CSV. Please contact the researcher.")
            return

        st.session_state.stage = "experiment"
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
        "Really sorry, but you failed the attention check twice and are not qualified to continue this study."
    )
    st.caption("You may now close this tab.")


def topic_select_page():
    render_banner()
    st.title("Topic selection")

    st.markdown(
        "**Task:** Please select the **one topic** that best matches something you have encountered recently."
    )

    assigned = st.session_state.get("assigned_category")
    if not assigned:
        # Fallback (shouldn't happen if attention check passed)
        assigned = random.choice(list(TOPIC_GROUPS.keys()))
        st.session_state.assigned_category = assigned
        log_event("category_assigned", title=assigned, payload={"assigned_category": assigned, "method": "fallback"})

    st.caption(f"You have been assigned to topics in the area: **{assigned}**")

    # Load availability info (optional)
    threads, source = get_threads_data()
    st.session_state["_threads_source"] = source

    sub = st.radio("Select one topic (choose one):", TOPIC_GROUPS[assigned], index=None)

    # Optional: show a small hint if csv missing
    if not threads:
        st.info(
            f"⚠️ Topic CSV not loaded ({source}). "
            "For researchers: place the CSV next to this app as 'topic_threads.csv' "
            "or set TOPIC_CSV_PATH in Streamlit secrets."
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

        st.session_state.chosen_category = assigned
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
                "assigned_category": assigned,
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

    # Ensure random assignment exists (scenario, story, and comment type)
    thread = ensure_thread_selected()
    if not thread:
        source = st.session_state.get("_threads_source", "unknown")
        st.error(f"Could not load scenario threads CSV ({source}).")

        # Optional researcher-only uploader if the CSV is missing on the server
        uploaded = st.file_uploader("Upload topic CSV (researcher only)", type=["csv"])
        if uploaded is not None:
            st.session_state.uploaded_threads_csv_bytes = uploaded.read()
            st.success("CSV uploaded. Reloading…")
            st.rerun()
        return

    # Derive subtopic from the assigned thread
    subtopic = thread.get("topic") or st.session_state.get("chosen_subtopic")
    st.session_state.chosen_subtopic = subtopic

    # Log once when the thread is shown
    if not st.session_state.get("_logged_thread_shown"):
        log_event(
            "thread_shown",
            title=thread.get("thread_id", ""),
            payload={
                "assigned_category": st.session_state.get("assigned_category"),
                "chosen_subtopic": subtopic,
                "story_id": thread.get("story_id") or thread.get("thread_id"),
                "thread_id": thread.get("thread_id"),
                "comment_variant_id": thread.get("comment_variant_id"),
                "support_combo": thread.get("support_combo"),
                "informational_support": thread.get("informational_support"),
                "emotional_support": thread.get("emotional_support"),
                "is_original_comment": thread.get("is_original_comment"),
                "thread_source": thread.get("source"),
                "post_title": thread.get("title"),
            },
        )
        st.session_state["_logged_thread_shown"] = True

    st.markdown(
        f"""
<div style="margin: 6px 0 10px 0; font-weight:700;">
  Task: Please read the thread and the comment carefully.
</div>
""",
        unsafe_allow_html=True,
    )

    # Thread content
    render_thread_context(thread, subtopic, show_post_body=True)

    st.markdown("---")

    # Timing gate (20s) with live countdown
    if st.session_state.exp_view_start_ts is None:
        st.session_state.exp_view_start_ts = time.time()

    elapsed = int(time.time() - st.session_state.exp_view_start_ts)
    remaining = max(0, MIN_SECONDS_THREAD - elapsed)

    countdown = st.empty()
    countdown.caption(
        f"Please stay on this page for at least {MIN_SECONDS_THREAD} seconds. Remaining: {remaining}s"
    )

    if remaining > 0:
        st.button("Continue to survey", disabled=True)
        time.sleep(1)
        st.rerun()
        return

    if st.button("Continue to survey"):
        st.session_state.thread_read_elapsed_seconds = elapsed

        log_event(
            "thread_read_complete",
            title=thread.get("thread_id", ""),
            payload={
                "elapsed_seconds": elapsed,
                "min_required": MIN_SECONDS_THREAD,
                "assigned_category": st.session_state.get("assigned_category"),
                "chosen_subtopic": subtopic,
                "story_id": thread.get("story_id") or thread.get("thread_id"),
                "comment_variant_id": thread.get("comment_variant_id"),
                "support_combo": thread.get("support_combo"),
                "informational_support": thread.get("informational_support"),
                "emotional_support": thread.get("emotional_support"),
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

    # Show the comment at the top of the survey so participants can revisit it while answering.
    # We do NOT show it on the final page (general questions).
    thread = st.session_state.get("selected_thread") or ensure_thread_selected()
    if step == 1 and thread:
        st.markdown(
            """
<div style="font-weight:800; font-size:1.0rem; margin-bottom:8px;">
  Comment (for reference while answering)
</div>
""",
            unsafe_allow_html=True,
        )
        render_comment(thread.get("comment", ""))
        with st.expander("View original post", expanded=False):
            render_post_meta()
            render_post_content(thread.get("title", ""), thread.get("body", ""))
        st.markdown("---")

    st.title(f"Survey ({step}/2)")
    st.caption("Please answer all questions.")

    if step == 1:
        survey_step1()
    else:
        survey_step2()


def survey_step1():
    st.markdown(
        """
Please imagine that you are the entrepreneur **who posted the thread** and that you have just read the online **comment** (scroll up to review the post and the comment).  
Indicate how you would feel right now.

Please answer each item according to the following scale:  
**1 = Definitely False, 2 = Mostly False, 3 = Somewhat False, 4 = Slightly False, 5 = Slightly True, 6 = Somewhat True, 7 = Mostly True, and 8 = Definitely True.**
"""
    )

    with st.form("survey_step1_form"):
        answers: Dict[str, Any] = {}

        hope_items = [
            "If I were the entrepreneur, this response would enable me to think of many ways to get out of the current difficulties in the business.",
            "If I were the entrepreneur, this response would enable me to energetically pursue my business goals.",
            "If I were the entrepreneur, this response would make me feel that there are many ways around any problem I am currently facing in my business.",
            "If I were the entrepreneur, this response would make me feel pretty successful in my business.",
            "If I were the entrepreneur, this response would enable me to think of many ways to reach my current business goals.",
            "If I were the entrepreneur, this response would make me feel that I am meeting the business goals I have set for myself.",
        ]
        for i, q in enumerate(hope_items, start=1):
            answers[f"hope_{i}"] = likert8(q, f"hope_{i}")

        st.divider()

        lonely_items = [
            "If I were the entrepreneur, this response would make me feel that I lack companionship.",
            "If I were the entrepreneur, this response would make me feel that there is no one I can turn to.",
            "If I were the entrepreneur, this response would make me feel like an outgoing person.",
            "If I were the entrepreneur, this response would make me feel left out.",
            "If I were the entrepreneur, this response would make me feel isolated from others.",
            "If I were the entrepreneur, this response would make me feel that I could find companionship when I want it.",
            "If I were the entrepreneur, this response would make me feel unhappy about being so withdrawn.",
            "If I were the entrepreneur, this response would make me feel that people are around me but not really with me.",
        ]
        for i, q in enumerate(lonely_items, start=1):
            answers[f"lonely_{i}"] = likert8(q, f"lonely_{i}")

        st.divider()

        ps_items = [
            "This response made me feel understood.",
            "This response made me feel supported.",
            "This response made me feel supported about my situation.",
        ]
        for i, q in enumerate(ps_items, start=1):
            answers[f"supported_{i}"] = likert8(q, f"supported_{i}")

        st.divider()

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
            "**The response was mainly about:**",
            ["Work-life balance", "Business difficulty"],
            index=None,
            horizontal=True,
            key="mc_topic",
        )

        st.divider()

        birth_year = st.selectbox(
            "What is your birth year?",
            list(range(1946, 2009)),
            index=None,
            placeholder="Select…",
            key="birth_year",
        )
        gender = st.selectbox(
            "What is your gender?",
            ["Female", "Male", "Third gender", "Transgender"],
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
            list(range(0, 51)) + [">50"],
            index=None,
            placeholder="Select…",
            key="ent_years",
        )
        work_years = st.selectbox(
            "How many years of work experience do you have?",
            list(range(0, 51)) + [">50"],
            index=None,
            placeholder="Select…",
            key="work_years",
        )

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

    # Cast numeric fields; experience fields may be the string ">50".
    by = int(birth_year)

    # Store page2
    st.session_state.survey_answers["page2"] = {
        "manipulation_check_topic": mc_topic,
        "birth_year": by,
        "gender": gender,
        "education": education,
        "entrepreneurial_years": ent_years,
        "work_years": work_years,
    }

    # Evaluate manipulation check correctness vs assigned category
    assigned = st.session_state.get("assigned_category")
    expected = "Business difficulty" if assigned == "Business" else "Work-life balance"
    mc_correct = (mc_topic == expected)

    log_event(
        "survey_page2_complete",
        title="mc+demographics",
        payload={
            "manipulation_check": mc_topic,
            "assigned_category": assigned,
            "expected": expected,
            "correct": mc_correct,
            "birth_year": by,
            "gender": gender,
            "education": education,
            "entrepreneurial_years": ent_years,
            "work_years": work_years,
        },
    )

    # Final payload (保持你原来的结构不变)
    final_payload = {
        "pid": st.session_state.get("prolific_id"),
        "session_id": st.session_state.get("session_id"),
        "variant": CONDITION,
        "assigned_category": assigned,
        "assignment": {
            "scenario_label": expected,
            "topic": (st.session_state.get("selected_thread", {}) or {}).get("topic")
            or st.session_state.get("chosen_subtopic"),
            "story_id": (st.session_state.get("selected_thread", {}) or {}).get("story_id")
            or (st.session_state.get("selected_thread", {}) or {}).get("thread_id"),
            "comment_variant_id": (st.session_state.get("selected_thread", {}) or {}).get("comment_variant_id"),
            "support_combo": (st.session_state.get("selected_thread", {}) or {}).get("support_combo"),
            "informational_support": (st.session_state.get("selected_thread", {}) or {}).get("informational_support"),
            "emotional_support": (st.session_state.get("selected_thread", {}) or {}).get("emotional_support"),
            "is_original_comment": (st.session_state.get("selected_thread", {}) or {}).get("is_original_comment"),
        },
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
    completion_url = get_completion_url()
    if completion_url:
        if not st.session_state.get("_completion_link_shown_logged"):
            log_event("completion_link_shown", payload={"completion_url": completion_url})
            st.session_state["_completion_link_shown_logged"] = True
        st.link_button("Click here to complete", completion_url)
    else:
        st.info("No Prolific completion URL is configured. You may now close this tab.")


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
        # Legacy stage from earlier versions: we no longer ask participants to choose a topic.
        st.session_state.stage = "experiment"
        st.session_state.scroll_top_next = True
        st.rerun()
        return
    if stage == "experiment":
        experiment_page()
        return
    if stage == "survey":
        survey_page()
        return
    if stage == "done":
        done_page()
        return

    # fallback
    st.session_state.stage = "consent"
    st.rerun()


# =============================================================================
# SESSION INIT
# =============================================================================
st.session_state.setdefault("session_id", str(uuid.uuid4()))
st.session_state.setdefault("start_time", utc_now_iso())
st.session_state.setdefault("stage", "consent")

st.session_state.setdefault("prolific_id", None)
st.session_state.setdefault("practice_attempts", 0)
st.session_state.setdefault("attention_attempt_history", [])

# Random assignment + topic choice
st.session_state.setdefault("assigned_category", None)
st.session_state.setdefault("chosen_category", None)
st.session_state.setdefault("chosen_subtopic", None)

# Thread selection + timers
st.session_state.setdefault("selected_thread", None)
st.session_state.setdefault("exp_view_start_ts", None)
st.session_state.setdefault("thread_read_elapsed_seconds", None)

# Survey
st.session_state.setdefault("survey_step", 1)
st.session_state.setdefault("survey_answers", {})

# Optional researcher upload
st.session_state.setdefault("uploaded_threads_csv_bytes", None)

main()
