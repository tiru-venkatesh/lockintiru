#!/usr/bin/env python3
"""
Jarvis - local chat assistant with Gmail send capability, powered by Groq.

Prereqs:
    1. A free Groq API key: https://console.groq.com/keys
       Set it as an environment variable before running:
         Windows (PowerShell):  $env:GROQ_API_KEY = "gsk_..."
         Windows (permanent):   setx GROQ_API_KEY "gsk_..."   (new terminal needed after)
         macOS/Linux:           export GROQ_API_KEY="gsk_..."
    2. pip install requests google-auth google-auth-oauthlib google-api-python-client
    3. Gmail send setup (one-time):
         - Go to console.cloud.google.com -> create/select a project
         - Enable the "Gmail API"
         - Credentials -> Create Credentials -> OAuth client ID -> "Desktop app"
         - Download the JSON, save it next to this script as credentials.json
       The first time Jarvis sends an email, a browser window opens for you
       to approve access. After that, a token.json is cached locally and
       you won't be asked again.

Run:
    python jarvis.py
"""

import base64
import csv
import itertools
import json
import time
import re
import mimetypes
import os
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import memory_store

# --- Groq connection -----------------------------------------------------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"  # tool-calling capable; llama-3.3-70b-versatile was deprecated by Groq in June 2026
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = GROQ_MODEL

SYSTEM_PROMPT = (
    "You are Jarvis, a helpful local AI assistant running on the user's own "
    "machine. Be concise and direct. You can send emails on the user's "
    "behalf using the send_email tool, and you can look things up about "
    "Tiru's own projects/notes/history using the search_knowledge tool. "
    "Before calling send_email, make sure you "
    "have a real recipient address, a subject, and a body -- ask the user "
    "for anything missing rather than inventing it. Outreach/application "
    "emails should attach Tiru's resume (tiru-venkatesh.pdf) by default -- "
    "leave attach_resume unset (or true) unless the user says not to attach "
    "it. The tool itself will show the user a preview and ask for their "
    "confirmation before anything is actually sent, so you don't need to "
    "ask twice. Use "
    "search_knowledge whenever the user asks about their own past work, "
    "projects, or anything you wouldn't otherwise know -- don't guess or "
    "make things up when you could look it up instead. This includes "
    "identity/personal questions like 'who am I' or 'what have I worked "
    "on' -- those are search_knowledge lookups, never a reason to call "
    "send_email. Only call send_email when the user has actually asked "
    "you to send, draft-and-send, or email someone.\n\n"
    "You also have a remember_fact tool. Call it when the user tells you "
    "something worth keeping across future conversations -- a preference, "
    "an ongoing project detail, a recurring contact, a standing "
    "instruction. Don't call it for one-off details that only matter to "
    "the current message, and don't call it just because a fact was "
    "mentioned in passing -- only when it's actually worth recalling "
    "later. This is separate from search_knowledge: search_knowledge "
    "looks things up in existing files, remember_fact writes something "
    "new down for next time.\n\n"
    "You can also work from GOALS, not just one-off instructions. When the "
    "user tells you an outcome they want rather than a single concrete task "
    "-- things like 'I need to find internships', 'help me launch this', "
    "'get me some interviews' -- use the create_plan tool to break it into "
    "an ordered list of concrete steps, then tell the user the plan in plain "
    "sentences. As you actually complete a step during the conversation "
    "(after a search, after an email is approved and sent, etc.), call "
    "complete_plan_step to mark progress. Don't create a plan for a simple "
    "single request you can just do right away.\n\n"
    "IMPORTANT: when the user asks you to send, draft-and-send, or email "
    "someone, you MUST actually call the send_email function -- do not "
    "just write a text reply describing or narrating that you 'sent' or "
    "'are sending' an email. A text reply alone sends nothing. If you "
    "have a real to/subject/body, call the tool. Only fall back to plain "
    "text if something required (like the recipient address) is missing, "
    "in which case ask for it instead of guessing.\n\n"
    "FORMATTING: your replies are shown in a plain-text interface and read "
    "aloud, so never use markdown -- no asterisks/bold, no headers, no "
    "backticks, no numbered or dashed bullet lists. Write in plain, "
    "natural, conversational sentences. If you're listing a few things, "
    "just say them as a short sentence or put each on its own plain line "
    "with no marker in front of it."
)

# --- Resume / portfolio config -------------------------------------------
# Put tiru-venkatesh.pdf next to this script (or point RESUME_PATH at wherever
# it actually lives). When present, it's attached to every outreach email
# automatically -- single sends, /bulk, and /bulk-role alike.
_HERE = os.path.dirname(os.path.abspath(__file__))
RESUME_PATH = os.environ.get("RESUME_PATH") or os.path.join(_HERE, "tiru-venkatesh.pdf")
PORTFOLIO_URL = "https://tiru-venkatesh.github.io"


def ask_yes_no(prompt: str) -> bool:
    """Strict confirm prompt. Re-asks on anything that isn't y/yes/n/no
    (blank = no), so a typo or stray keystroke can never count as approval
    and never falls through to anything else. Ctrl-C / EOF = no."""
    while True:
        try:
            ans = input(f"{prompt} [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if ans in ("y", "yes"):
            return True
        if ans in ("", "n", "no"):
            return False
        print("  Please type y or n.")


def resume_available() -> bool:
    """RESUME_PATH is the primary path, but the actual filename has drifted
    more than once (tIru-venkatesh.pdf, TIru_Venkatesh.pdf, ...) and Render's
    filesystem is case-sensitive, so an exact-name mismatch silently sends
    outreach emails with no resume attached. Fall back to a forgiving search
    in the script's own directory before giving up, and remember whatever it
    finds so every other call site (bulk_send, bulk_role_send,
    confirm_and_send) benefits automatically."""
    global RESUME_PATH
    if RESUME_PATH and os.path.exists(RESUME_PATH):
        return True

    here = os.path.dirname(os.path.abspath(__file__)) or "."
    try:
        for fname in os.listdir(here):
            if fname.lower().endswith(".pdf") and "venkatesh" in fname.lower():
                RESUME_PATH = os.path.join(here, fname)
                return True
    except OSError:
        pass
    return False


# --- Gmail setup -------------------------------------------------------
# Locally these sit next to jarvis.py. On Render they're uploaded as
# Secret Files instead, which get mounted read-only at /etc/secrets/ --
# so prefer that path when it exists, and let an env var override either
# path explicitly if you ever need to.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _resolve_secret_path(env_var, filename):
    override = os.environ.get(env_var)
    if override:
        return override
    render_path = os.path.join("/etc/secrets", filename)
    if os.path.exists(render_path):
        return render_path
    return filename


CREDENTIALS_FILE = _resolve_secret_path("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = _resolve_secret_path("GMAIL_TOKEN_FILE", "token.json")
# Refreshed tokens get written here instead of back over TOKEN_FILE, since
# /etc/secrets is read-only on Render. TOKEN_FILE (which still has a valid
# refresh_token) gets re-read and re-refreshed on every cold start, so
# nothing is lost by not persisting the refreshed copy.
TOKEN_WRITE_PATH = os.environ.get(
    "GMAIL_TOKEN_WRITE_FILE",
    "/tmp/gmail_token.json" if TOKEN_FILE.startswith("/etc/secrets") else TOKEN_FILE,
)


def get_gmail_service():
    """Build an authenticated Gmail API client, handling the OAuth dance
    and caching the resulting token so this only prompts you once."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Missing Gmail dependencies. Run:\n"
            "  pip install google-auth google-auth-oauthlib google-api-python-client"
        )

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise RuntimeError(
                    f"{CREDENTIALS_FILE} not found. Download an OAuth client-secret "
                    "JSON (Desktop app type) from Google Cloud Console -> APIs & "
                    "Services -> Credentials, and save it as credentials.json next "
                    "to jarvis.py. See the setup notes at the top of this file."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_WRITE_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def send_gmail(to: str, subject: str, body: str, attach_path: str = None) -> str:
    """Send an email via the Gmail API. If attach_path points at a real file
    (defaults to RESUME_PATH when attach_resume is used upstream), it's
    attached as-is -- e.g. tiru-venkatesh.pdf. Returns the sent message id."""
    # Prefer the Gmail API (HTTPS) whenever a token is available: hosts like
    # Render's free tier block outbound SMTP ports (465/587), so the App
    # Password route only works on machines that allow SMTP.
    have_api_token = os.path.exists(TOKEN_FILE)
    use_smtp = bool(os.environ.get("GMAIL_APP_PASSWORD")) and not have_api_token
    service = None if use_smtp else get_gmail_service()

    if attach_path and os.path.exists(attach_path):
        message = MIMEMultipart()
        message.attach(MIMEText(body))
        ctype, _ = mimetypes.guess_type(attach_path)
        maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
        with open(attach_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype=subtype)
        part.add_header(
            "Content-Disposition", "attachment", filename=os.path.basename(attach_path)
        )
        message.attach(part)
    else:
        message = MIMEText(body)

    message["to"] = to
    message["subject"] = subject
    if use_smtp:
        # App Password route: no Google Cloud / credentials.json needed.
        import smtplib
        sender = os.environ.get("GMAIL_ADDRESS", "")
        if not sender:
            raise RuntimeError("Set GMAIL_ADDRESS (your Gmail) along with GMAIL_APP_PASSWORD.")
        message["from"] = sender
        pwd = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
                smtp.login(sender, pwd)
                smtp.send_message(message)
        except OSError as e:
            raise RuntimeError(
                f"Could not reach smtp.gmail.com:465 ({e}). This host probably "
                "blocks SMTP (Render's free tier does). Use the Gmail API "
                "instead: upload token.json as a Secret File."
            )
        return "smtp-sent"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent.get("id", "unknown")


# --- Tool definition + confirmation gate -----------------------------------
EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": (
            "Send an email through the user's Gmail account. Only call this "
            "once you have a real recipient address, subject, and body -- "
            "never invent an email address."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient's email address"},
                "subject": {"type": "string", "description": "Subject line"},
                "body": {"type": "string", "description": "Full email body text"},
                "attach_resume": {
                    "type": "boolean",
                    "description": (
                        "Whether to attach the resume PDF (tiru-venkatesh.pdf). "
                        "Default true for outreach/application emails -- set "
                        "false only if the user explicitly says not to attach it."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
}

KNOWLEDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": (
            "Search Tiru's local knowledge base (his own notes, projects, "
            "outreach history, etc. -- see the knowledge/ folder) for "
            "information relevant to the user's question. Use this before "
            "answering anything about Tiru's own projects, past work, or "
            "personal context that you wouldn't otherwise know."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        },
    },
}

REMEMBER_TOOL = {
    "type": "function",
    "function": {
        "name": "remember_fact",
        "description": (
            "Save a single fact about the user that's worth recalling in "
            "future conversations -- a preference, an ongoing project "
            "detail, a recurring contact, a standing instruction. Not for "
            "one-off details that only matter right now."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The fact to remember, written as a short standalone sentence.",
                },
            },
            "required": ["fact"],
        },
    },
}

CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Turn a fuzzy goal the user gives you ('I need internships "
            "somehow', 'help me launch this') into a structured, ordered "
            "plan of concrete steps. Call this when the user states an "
            "outcome they want rather than a single specific action -- it's "
            "what lets AURA work from intent, not just instructions. Break "
            "the goal into a handful of clear, ordered steps (usually 3-7). "
            "Tag each step's action so the plan knows what kind of work it "
            "is: 'search' (look something up in their knowledge base), "
            "'email' (send an email -- still goes through the normal "
            "approval), 'remember' (save a fact), or 'manual' (something the "
            "user does themselves). Don't call this for a one-off request "
            "you can just do directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The user's overall goal, in one sentence.",
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered steps that accomplish the goal.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "What this step accomplishes, one short sentence.",
                            },
                            "action": {
                                "type": "string",
                                "enum": ["search", "email", "remember", "manual"],
                                "description": "The kind of work this step represents.",
                            },
                        },
                        "required": ["description"],
                    },
                },
            },
            "required": ["goal", "steps"],
        },
    },
}

COMPLETE_STEP_TOOL = {
    "type": "function",
    "function": {
        "name": "complete_plan_step",
        "description": (
            "Mark progress on an existing plan as you work through it. By "
            "default this completes the next still-pending step of the plan "
            "in order -- call it right after you actually finish that step's "
            "work (e.g. after a search or after an email is approved and "
            "sent). Only use this for a plan that already exists; check the "
            "active plans you were told about rather than inventing a plan "
            "id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "The id of the plan to advance.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional short note on what happened for this step.",
                },
            },
            "required": ["plan_id"],
        },
    },
}

ALL_TOOLS = [
    EMAIL_TOOL,
    KNOWLEDGE_TOOL,
    REMEMBER_TOOL,
    CREATE_PLAN_TOOL,
    COMPLETE_STEP_TOOL,
]


def load_recipients(path: str) -> list:
    """Read a txt file with one email address per line. Blank lines and
    lines starting with # are ignored."""
    if not os.path.exists(path):
        raise RuntimeError(f"File not found: {path}")
    with open(path, "r") as f:
        lines = [ln.strip() for ln in f]
    return [ln for ln in lines if ln and not ln.startswith("#")]


# --- Role-matched outreach templates ---------------------------------------
TEMPLATES_FILE = "templates.json"

EMAIL_INTRO = (
    "Dear {name},\n\n"
    "I am Tiru Venkatesh, a second-year B.Tech CSE student at JNTU "
    "Narasaraopeta, with a strong interest in Artificial Intelligence, Large "
    "Language Models, and autonomous agents."
)

EMAIL_ASK = (
    "I would be grateful for an opportunity to contribute to your research "
    "group or ongoing projects, whether through a research internship, a "
    "project collaboration, or by assisting with ongoing work. I am willing "
    "to invest the time needed to learn the relevant literature, tools and "
    "methods, and to contribute meaningfully."
)

EMAIL_CLOSING = (
    "Portfolio: https://tiru-venkatesh.github.io\n"
    "GitHub: https://github.com/tiru-venkatesh\n"
    "LinkedIn: https://www.linkedin.com/in/tiru-venkatesh-830907202/\n\n"
    "I have attached my resume for your reference. If my background aligns "
    "with your research interests, I would sincerely appreciate an "
    "opportunity to discuss whether there may be a suitable way for me to "
    "contribute.\n\n"
    "Thank you for your time and consideration.\n\n"
    "Best regards,\n"
    "Tiru Venkatesh\n"
    "B.Tech CSE, Second Year\n"
    "JNTU Narasaraopeta"
)

DEFAULT_ROLE_SUBJECT = "Research internship inquiry - 2nd-year CSE student (AI agents, LLMs)"
BODY_FILE = "outreach_body.txt"
SENT_LOG = "receipts.txt"                 # one "email,name,type" per sent mail
SKIP_FILES = ("receipts.txt", "emails.txt")  # never email these again
DEFAULT_BULK_LIMIT = int(os.environ.get("BULK_LIMIT", "40"))
BULK_DELAY_SECONDS = float(os.environ.get("BULK_DELAY", "8"))
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{1,60}\]")


def load_templates(path: str = TEMPLATES_FILE) -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"Templates file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sent_set() -> set:
    """Addresses we've already emailed (receipts.txt / emails.txt)."""
    sent = set()
    for fn in SKIP_FILES:
        if not os.path.exists(fn):
            continue
        with open(fn, "r", encoding="utf-8-sig") as f:
            for ln in f:
                first = ln.strip().split(",")[0].strip().strip('"').lower()
                if "@" in first:
                    sent.add(first)
    return sent


def log_sent(email: str, name: str, type_key: str) -> None:
    new_file = not os.path.exists(SENT_LOG) or os.path.getsize(SENT_LOG) == 0
    with open(SENT_LOG, "a", encoding="utf-8", newline="") as f:
        if new_file:
            f.write("email,name,type\n")
        safe_name = name.replace(",", " ")
        f.write(f"{email},{safe_name},{type_key}\n")


def load_recipients_csv(path: str) -> list:
    """Read a CSV with columns: email, name (optional), type, and an optional
    personal_sentence. 'type' must match a key in templates.json."""
    if not os.path.exists(path):
        raise RuntimeError(f"File not found: {path}")
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            email = (r.get("email") or "").strip().lower()
            if not email or email.startswith("#"):
                continue
            rows.append({
                "email": email,
                "name": (r.get("name") or "").strip() or "Professor",
                "type": (r.get("type") or "").strip().lower(),
                "personal_sentence": (r.get("personal_sentence") or "").strip(),
            })
    return rows


def compose_role_email(templates: dict, name: str, type_key: str,
                       variant_idx: int, personal_sentence: str = ""):
    """Build subject/body: intro, optional personal sentence, role-matched
    middle paragraph, ask, closing."""
    entry = templates.get(type_key)
    if not entry:
        raise KeyError(f"Unknown type '{type_key}'. Valid types: {', '.join(templates.keys())}")
    variants = entry["variants"]
    # No personal_sentence => we know nothing real about their work, so use
    # the neutral paragraph (what I build + what I want to learn) instead of
    # variants that claim familiarity with their research.
    if not personal_sentence and entry.get("neutral"):
        middle = entry["neutral"]
    else:
        middle = variants[variant_idx % len(variants)]
    parts = [EMAIL_INTRO.format(name=name)]
    if personal_sentence:
        parts.append(personal_sentence)
    parts += [middle, EMAIL_ASK, EMAIL_CLOSING]
    return DEFAULT_ROLE_SUBJECT, "\n\n".join(parts)


def _parse_bulk_args(rest: str):
    """'file.csv limit=10' -> ('file.csv', 10). Quotes around the path are ok."""
    limit = DEFAULT_BULK_LIMIT
    tokens = rest.split()
    keep = []
    for t in tokens:
        m = re.match(r"^(?:--)?limit=(\d+)$", t, re.I)
        if m:
            limit = int(m.group(1))
        else:
            keep.append(t)
    return " ".join(keep).strip().strip('"').strip("'"), limit


def bulk_role_send(rest: str) -> None:
    """Role-matched bulk outreach. Skips invalid/duplicate/already-sent
    addresses, caps each run, previews, asks once, then sends with a short
    delay and logs every success to receipts.txt."""
    path, limit = _parse_bulk_args(rest)
    try:
        templates = load_templates()
        recipients = load_recipients_csv(path)
    except RuntimeError as e:
        print(f"[bulk-role] {e}")
        return
    if not recipients:
        print(f"[bulk-role] No recipients found in {path}.")
        return

    # Rows whose type isn't a research area are skipped, not fatal:
    # "personal" rows are private addresses (never cold-emailed), anything
    # else unknown (e.g. "institute") has no matching template.
    personal = [r for r in recipients if r["type"] == "personal"]
    unknown = [r for r in recipients if r["type"] not in templates and r["type"] != "personal"]
    recipients = [r for r in recipients if r["type"] in templates]
    if personal:
        print(f"[bulk-role] Skipped {len(personal)} 'personal' (private) addresses.")
    if unknown:
        print(f"[bulk-role] Skipped {len(unknown)} rows with no matching type "
              f"({', '.join(sorted({r['type'] or '(blank)' for r in unknown}))}). "
              f"Set type to one of: {', '.join(templates.keys())}")
    if not recipients:
        print("[bulk-role] Nothing left to send.")
        return

    already = load_sent_set()
    seen, todo, skipped = set(), [], {"invalid": 0, "duplicate": 0, "already_sent": 0}
    for r in recipients:
        e = r["email"]
        if not EMAIL_RE.match(e):
            skipped["invalid"] += 1
        elif e in seen:
            skipped["duplicate"] += 1
        elif e in already:
            skipped["already_sent"] += 1
        else:
            todo.append(r)
        seen.add(e)

    remaining_after = max(0, len(todo) - limit)
    todo = todo[:limit]
    print(f"\n[bulk-role] {len(recipients)} rows | skipped: {skipped['already_sent']} already emailed, "
          f"{skipped['duplicate']} duplicates, {skipped['invalid']} invalid")
    if not todo:
        print("[bulk-role] Nothing new to send.")
        return

    counters = {t: itertools.cycle(range(len(templates[t]["variants"]))) for t in templates}
    attach_path = RESUME_PATH if resume_available() else None
    if not attach_path:
        print(f"[bulk-role] ABORTED: resume not found at {RESUME_PATH}. "
              "Every email says 'I have attached my resume', so nothing was sent. "
              "Put tiru-venkatesh.pdf next to jarvis.py (or set RESUME_PATH).")
        return

    prepared, problems = [], []
    for r in todo:
        v = next(counters[r["type"]])
        subject, body = compose_role_email(templates, r["name"], r["type"], v, r["personal_sentence"])
        if PLACEHOLDER_RE.search(body):
            problems.append(r["email"])
        prepared.append((r, subject, body, v))
    if problems:
        print(f"[bulk-role] BLOCKED: unfilled [placeholder] text in emails to: {', '.join(problems[:5])}")
        return

    first_r, first_subj, first_body, _ = prepared[0]
    print(f"\n--- Sample (to {first_r['email']}) ---\nSubject: {first_subj}\n\n{first_body}\n---------------------------")
    print("\nRecipients this run:")
    for r, _, _, v in prepared:
        print(f"  {r['email']:38s} {r['type']:9s} v{v + 1}  {r['name']}")
    if remaining_after:
        print(f"\n({remaining_after} more not in this run - limit={limit}. Run again for the next batch.)")
    print(f"\nAttachment: {attach_path}")
    no_personal = sum(1 for r, *_ in prepared if not r["personal_sentence"])
    if no_personal:
        print(f"Tip: {no_personal}/{len(prepared)} rows have no personal_sentence column filled in; "
              "a one-line mention of their research makes replies much more likely.")

    if not ask_yes_no(f"\nSend {len(prepared)} emails?"):
        print("[bulk-role] Cancelled.")
        return

    sent, failed = 0, []
    for i, (r, subject, body, _) in enumerate(prepared):
        try:
            msg_id = send_gmail(r["email"], subject, body, attach_path=attach_path)
            log_sent(r["email"], r["name"], r["type"])
            print(f"  [ok]   {r['email']} (id: {msg_id})")
            sent += 1
        except Exception as e:
            print(f"  [fail] {r['email']}: {e}")
            failed.append(r["email"])
        if i < len(prepared) - 1:
            time.sleep(BULK_DELAY_SECONDS)

    print(f"\n[bulk-role] Done. Sent {sent}/{len(prepared)}.")
    if failed:
        print(f"[bulk-role] Failed (not logged, will retry next run): {', '.join(failed)}")


def bulk_send(path: str, subject: str, body: str) -> None:
    """Same subject/body to every address in a txt file (one per line)."""
    try:
        recipients = load_recipients(path)
    except RuntimeError as e:
        print(f"[bulk] {e}")
        return
    already = load_sent_set()
    recipients = [a for a in dict.fromkeys(x.lower() for x in recipients)
                  if EMAIL_RE.match(a) and a not in already]
    if not recipients:
        print(f"[bulk] No new valid addresses in {path}.")
        return
    if PLACEHOLDER_RE.search(subject + body):
        print("[bulk] BLOCKED: subject/body still contains a [placeholder].")
        return

    attach_path = RESUME_PATH if resume_available() else None
    if not attach_path and "attach" in body.lower():
        print(f"[bulk] ABORTED: body mentions an attachment but {RESUME_PATH} was not found.")
        return
    print("\n--- Bulk email preview ---")
    print(f"Subject:   {subject}\nBody:\n{body}\nRecipients ({len(recipients)}):")
    for addr in recipients:
        print(f"  - {addr}")
    print(f"Attachment: {attach_path}" if attach_path else
          f"NOTE: {RESUME_PATH} not found -- sending without a resume attachment.")
    print("---------------------------")
    if not ask_yes_no(f"Send to all {len(recipients)} addresses?"):
        print("[bulk] Cancelled.")
        return

    sent, failed = 0, []
    for i, addr in enumerate(recipients):
        try:
            msg_id = send_gmail(addr, subject, body, attach_path=attach_path)
            log_sent(addr, "", "")
            print(f"  [ok]   {addr} (id: {msg_id})")
            sent += 1
        except Exception as e:
            print(f"  [fail] {addr}: {e}")
            failed.append(addr)
        if i < len(recipients) - 1:
            time.sleep(BULK_DELAY_SECONDS)
    print(f"\n[bulk] Done. Sent {sent}/{len(recipients)}.")
    if failed:
        print(f"[bulk] Failed: {', '.join(failed)}")


def confirm_and_send(args: dict) -> str:
    """Show a preview of the email and require explicit y/N before sending.
    This is the safety net -- the model can draft, but a human approves."""
    want_resume = args.get("attach_resume", True)
    attach_path = RESUME_PATH if want_resume else None
    will_attach = bool(attach_path and os.path.exists(attach_path))

    print("\n--- Email preview ---")
    print(f"To:      {args.get('to', '')}")
    print(f"Subject: {args.get('subject', '')}")
    print(f"Body:\n{args.get('body', '')}")
    if want_resume and not will_attach:
        print(f"Attachment: NONE -- {RESUME_PATH} not found, sending without it")
    else:
        print(f"Attachment: {RESUME_PATH}" if will_attach else "Attachment: none")
    print("----------------------")

    if want_resume and not will_attach:
        return ("NOT SENT: resume attachment requested but the PDF was not "
                f"found at {RESUME_PATH}. Fix the path, then retry.")
    if not ask_yes_no("Send this email?"):
        return "The user declined to send this email."

    try:
        msg_id = send_gmail(
            args["to"], args["subject"], args["body"],
            attach_path=attach_path if will_attach else None,
        )
        note = " with resume attached" if will_attach else ""
        return f"Email sent successfully to {args.get('to')}{note} (id: {msg_id})."
    except Exception as e:
        return f"Failed to send email: {e}"


VALID_TOOL_NAMES = {
    "send_email",
    "search_knowledge",
    "remember_fact",
    "create_plan",
    "complete_plan_step",
}


def _extract_fallback_tool_call(content: str):
    """Some models occasionally write the tool call as plain-text JSON in
    `content` instead of populating the real `tool_calls` field. Detect that
    shape and convert it into the same structure handle_tool_calls()
    expects, so it isn't just printed as raw JSON and ignored.

    Recognizes both {"name": ..., "parameters": {...}} and
    {"name": ..., "arguments": {...}}. Returns a list of tool_calls
    (possibly empty) if a match is found, else None."""
    if not content:
        return None
    text = content.strip()
    # Strip a ```json ... ``` fence if the model wrapped it in one.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    name = parsed.get("name")
    if name not in VALID_TOOL_NAMES:
        return None
    args = parsed.get("parameters", parsed.get("arguments", {}))
    if not isinstance(args, dict):
        return None

    return [{
        "id": "fallback_call_0",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }]


# --- Groq chat loop --------------------------------------------------
def check_groq_setup():
    if not GROQ_API_KEY:
        print("GROQ_API_KEY environment variable is not set.")
        print('Get a free key at https://console.groq.com/keys, then:')
        print('  Windows (PowerShell):  $env:GROQ_API_KEY = "gsk_..."')
        print('  macOS/Linux:           export GROQ_API_KEY="gsk_..."')
        sys.exit(1)


def _group_into_turns(messages):
    """Group a message list into atomic units: a lone user/assistant/tool
    message, or an assistant message with tool_calls together with all of
    its matching tool-result messages. Trimming has to cut at these
    boundaries -- cutting in the middle of a unit would send Groq a tool
    result with no matching tool_call (or vice versa), which the API
    rejects outright rather than just running with less context."""
    units = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            call_ids = {c.get("id") for c in m["tool_calls"]}
            j = i + 1
            unit = [m]
            while j < len(messages) and messages[j].get("role") == "tool" and messages[j].get("tool_call_id") in call_ids:
                unit.append(messages[j])
                j += 1
            units.append(unit)
            i = j
        else:
            units.append([m])
            i += 1
    return units


def trim_for_budget(messages, max_chars=22000):
    """The one place request size gets capped before it reaches Groq.

    Why this exists: persistent memory (memory_store.py) means a session
    can resume with 30-40+ prior messages, and a long-running chat grows
    further from there. Groq's on_demand tier caps at 8000 tokens/minute
    -- a real conversation blows past that in normal use, not because of
    anything unusual in that turn's message, just because history has
    piled up. That showed up as: 'Request too large ... Requested 8216,
    Limit 8000'.

    messages[0] is always the system prompt -- kept in full, always (it
    carries the tool instructions and the user's remembered facts, both
    of which matter every turn). From the rest, keep as many of the most
    recent *complete* units (see _group_into_turns) as fit under
    max_chars. Character count is a cheap proxy for tokens (~4 chars per
    token for English) -- good enough to stay clear of the limit without
    pulling in a real tokenizer dependency.

    Important: this only affects what gets *sent* to Groq this turn. The
    full conversation still lives in memory_store (SQLite) and in the
    caller's in-memory `messages` list untouched -- trimming returns a
    new list, it never mutates or drops anything from what's stored."""
    if not messages:
        return messages
    system = messages[0]
    units = _group_into_turns(messages[1:])

    kept = []
    total = len(system.get("content") or "")
    for unit in reversed(units):
        unit_chars = sum(len(m.get("content") or "") for m in unit)
        if kept and total + unit_chars > max_chars:
            break
        kept.append(unit)
        total += unit_chars
    kept.reverse()

    flat = [system]
    for unit in kept:
        flat.extend(unit)
    return flat


def stream_chat(messages, tools=None):
    """Send the conversation to Groq (OpenAI-compatible chat completions
    endpoint). Non-streaming, since we need the full tool_calls payload
    before deciding what to do next."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": trim_for_budget(messages),
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    except requests.exceptions.RequestException as e:
        print(f"\n[Groq connection error]: {e}")
        return "", []

    if resp.status_code != 200:
        print(f"\n[Groq error {resp.status_code}]: {resp.text}")
        return "", []

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        print(f"\n[Groq error]: no choices in response: {data}")
        return "", []

    msg = choices[0].get("message", {})
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls", []) or []

    # Fallback: occasionally a model writes the tool call as JSON text in
    # `content` instead of using the real tool_calls field. If so, treat
    # it as a tool call instead of printing raw JSON at the user.
    if not tool_calls:
        fallback = _extract_fallback_tool_call(content)
        if fallback is not None:
            tool_calls = fallback
            content = ""

    if content:
        print(content)

    return content, tool_calls


def handle_tool_calls(messages, tool_calls):
    """Execute each tool call, feed the result back into the conversation,
    then let the model give a natural follow-up (e.g. "Email sent.")."""
    for call in tool_calls:
        fn = call.get("function", {})
        name = fn.get("name")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        if name == "send_email":
            result = confirm_and_send(args)
        elif name == "search_knowledge":
            import rag
            try:
                result = rag.query_as_context(CLI_USER_ID, args.get("query", ""))
            except RuntimeError as e:
                result = f"Knowledge search unavailable: {e}"
        elif name == "remember_fact":
            fact = args.get("fact", "")
            memory_store.remember(CLI_USER_ID, fact)
            result = f"Remembered: {fact}"
        elif name == "create_plan":
            try:
                plan_id = memory_store.create_plan(
                    CLI_USER_ID, args.get("goal", ""), args.get("steps", [])
                )
                plan = memory_store.get_plan(CLI_USER_ID, plan_id)
                lines = [f"Created plan #{plan_id}: {plan['goal']}"]
                for s in plan["steps"]:
                    lines.append(f"  {s['position'] + 1}. [{s['action']}] {s['description']}")
                result = "\n".join(lines)
            except ValueError as e:
                result = f"Couldn't create plan: {e}"
        elif name == "complete_plan_step":
            step = memory_store.complete_next_step(
                CLI_USER_ID, args.get("plan_id"), note=args.get("note")
            )
            if step is None:
                result = "No pending step to complete on that plan (it may be finished or not exist)."
            else:
                plan = memory_store.get_plan(CLI_USER_ID, step["plan_id"])
                prog = plan["progress"]
                result = (
                    f"Marked done: {step['description']} "
                    f"({prog['done']}/{prog['total']} steps complete)."
                )
                if plan["status"] == "done":
                    result += " That was the last step -- plan complete."
        else:
            result = f"Unknown tool '{name}'."

        tool_call_id = call.get("id", "fallback_call_0")
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })
        memory_store.append_message(CLI_USER_ID, "tool", result, tool_call_id=tool_call_id)

    print("Jarvis: ", end="", flush=True)
    followup, _ = stream_chat(messages, tools=ALL_TOOLS)
    if followup:
        messages.append({"role": "assistant", "content": followup})
        memory_store.append_message(CLI_USER_ID, "assistant", followup)


CLI_USER_ID = "local"  # single-user CLI mode; jarvis_server.py uses the same fixed user id


def main():
    check_groq_setup()
    memory_store.init_db()
    print(f"Jarvis (model: {MODEL} via Groq) — type 'exit' to quit.\n")

    system_content = (
        SYSTEM_PROMPT
        + memory_store.facts_as_context(CLI_USER_ID)
        + memory_store.active_plans_as_context(CLI_USER_ID)
    )
    messages = [{"role": "system", "content": system_content}]
    messages.extend(memory_store.load_recent_messages(CLI_USER_ID))
    if len(messages) > 1:
        print(f"(resuming with {len(messages) - 1} messages of prior history)\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break
        if not user_input:
            continue

        # Let "bulk-role file.csv" / "bulk file.txt" work without the slash,
        # so they never fall through to the LLM as ordinary chat.
        _first = user_input.split(None, 1)[0].lower()
        if _first in ("bulk", "bulk-role", "bulkrole", "clear"):
            user_input = "/" + user_input
        if user_input.lower().startswith("/bulkrole"):
            user_input = "/bulk-role" + user_input[len("/bulkrole"):]

        # A bare "y"/"n"/"ok" at the main prompt is a leftover answer to a
        # confirm prompt that already closed. Never forward it to the LLM
        # (that is how the model hallucinated "Hello SWEETY" from old history).
        if user_input.lower() in ("y", "yes", "yep", "yeah", "n", "no", "nope", "ok", "okay"):
            print("(Nothing is waiting for confirmation. Re-run the command, e.g. "
                  "bulk-role file.csv, if you meant to send.)")
            continue

        # /clear -- wipe saved chat history (not facts or plans)
        if user_input.lower() == "/clear":
            memory_store.clear_conversation(CLI_USER_ID)
            del messages[1:]
            print("Conversation history cleared.")
            continue

        # /memories -- list what's been remembered long-term
        if user_input.lower() == "/memories":
            facts = memory_store.list_facts(CLI_USER_ID)
            if not facts:
                print("Nothing remembered yet.")
            for f in reversed(facts):
                print(f"  [{f['id']}] {f['fact']}")
            continue

        # /forget <id> -- delete one remembered fact
        if user_input.lower().startswith("/forget"):
            rest = user_input[len("/forget"):].strip()
            if not rest.isdigit():
                print("Usage: /forget <id>  (see /memories for ids)")
                continue
            ok = memory_store.forget(CLI_USER_ID, int(rest))
            print("Forgotten." if ok else "No memory with that id.")
            continue

        # /plan <id> -- show one plan's steps in detail (checked before
        # /plans, since "/plan 3".startswith("/plan") and we want the id form
        # to win when there's an argument).
        if user_input.lower().startswith("/plan ") or user_input.lower() == "/plan":
            rest = user_input[len("/plan"):].strip()
            if not rest.isdigit():
                print("Usage: /plan <id>  (see /plans for ids)")
                continue
            plan = memory_store.get_plan(CLI_USER_ID, int(rest))
            if not plan:
                print("No plan with that id.")
                continue
            prog = plan["progress"]
            print(f"Plan #{plan['id']}: {plan['goal']}  [{plan['status']}] "
                  f"({prog['done']}/{prog['total']}, {prog['pct']}%)")
            marks = {"done": "[x]", "pending": "[ ]", "skipped": "[-]"}
            for s in plan["steps"]:
                mark = marks.get(s["status"], "[ ]")
                note = f"  ({s['note']})" if s["note"] else ""
                print(f"  {mark} {s['position'] + 1}. [{s['action']}] {s['description']}{note}")
            continue

        # /plans -- list all plans with progress
        if user_input.lower() == "/plans":
            plans = memory_store.list_plans(CLI_USER_ID)
            if not plans:
                print("No plans yet. Tell me a goal and I'll build one.")
            for p in plans:
                prog = p["progress"]
                print(f"  #{p['id']} [{p['status']}] {p['goal']} "
                      f"({prog['done']}/{prog['total']}, {prog['pct']}%)")
            continue

        # Commands typed without the leading slash must never reach the LLM
        # (it has email tools and just hallucinates a subject/body).
        _first = user_input.split(None, 1)[0].lower() if user_input.split() else ""
        if _first in ("bulk-role", "bulk", "plan", "plans", "memories", "forget"):
            print(f"(Commands start with a slash: /{user_input}  -- e.g. /bulk-role file.csv --limit 5)")
            continue

        # /bulk-role <recipients.csv>
        # CSV columns: email,name,type  (type = ml/nlp/cv/systems/data/robotics)
        if user_input.lower().startswith("/bulk-role"):
            rest = user_input[len("/bulk-role"):].strip()
            if not rest:
                print("Usage: /bulk-role recipients.csv")
                continue
            bulk_role_send(rest)
            continue

        # /bulk <file.txt> [| subject | body]
        # Defaults to the research-internship subject and outreach_body.txt.
        if user_input.lower().startswith("/bulk"):
            rest = user_input[len("/bulk"):].strip()
            parts = [p.strip() for p in rest.split("|")]
            file_path = parts[0].strip('"').strip("'") if parts and parts[0] else None
            subject = parts[1] if len(parts) > 1 and parts[1] else DEFAULT_ROLE_SUBJECT
            body = parts[2] if len(parts) > 2 and parts[2] else "@" + BODY_FILE
            if body.startswith("@"):
                body_file = body[1:].strip()
                try:
                    with open(body_file, "r", encoding="utf-8") as bf:
                        body = bf.read().strip()
                except OSError as e:
                    print(f"Couldn't read body file '{body_file}': {e}")
                    continue
            if not file_path:
                print("Usage: /bulk emails.txt  OR  /bulk emails.txt | Subject | Body text")
                continue
            bulk_send(file_path, subject, body)
            continue

        messages.append({"role": "user", "content": user_input})
        memory_store.append_message(CLI_USER_ID, "user", user_input)
        print("Jarvis: ", end="", flush=True)
        reply, tool_calls = stream_chat(messages, tools=ALL_TOOLS)

        assistant_msg = {"role": "assistant", "content": reply}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)
        memory_store.append_message(CLI_USER_ID, "assistant", reply, tool_calls=tool_calls)

        if tool_calls:
            handle_tool_calls(messages, tool_calls)


if __name__ == "__main__":
    main()