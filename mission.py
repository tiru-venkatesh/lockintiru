"""/mission -- one focused GSoC-prep task a day, exams first.

Deliberately tiny: no new tables. Progress lives in a normal memory_store
*plan* ("GSoC 2027 preparation"), blockers live in normal memory facts, so
/plans, /plan <id> and /memory already show everything this command records.

Nothing here talks to the network or to GitHub/Google: it only prints a task
for YOU to do. Forking, commenting, opening PRs, joining chats and emailing
maintainers are always your own decisions.

Modes
    normal      up to ~60 min
    exam-safe   inside EXAM_WINDOW: the ~20 min version is shown by default
    exam-lock   days you lock with /gsoc lock: no task at all
A skipped day is simply skipped: there is no backlog and no catch-up.

Commands
    /mission [minutes]       today's task fitted to the time you really have, e.g. /mission 10
                             (no number: 60 min normally, ~20 in exam-safe; 'full' = 60, 'light' = 20)
    /mission busy            heavy day: rest, nothing is consumed or marked
    /mission done [note]     task finished -> mark done, store what you learned   (alias: /log <note>)
    /mission blocked <text>  record what is stopping you                         (alias: /log blocked <text>)
    /mission unblock         clear the blocker
    /mission status          progress, blocker, next action                     (alias: /status)
    /gsoc                    overview: mode, progress, blocker, next action
    /gsoc lock <date|a:b>    exam-lock a day or range (YYYY-MM-DD)   /gsoc unlock <date|a:b>   /gsoc locks
"""
from __future__ import annotations

import os
from datetime import date

import memory_store

GOAL = "GSoC 2027 preparation"
BLOCKER_PREFIX = "GSoC blocker:"
LOCK_PREFIX = "GSoC lock:"
# Semester exams. Override with EXAM_WINDOW="YYYY-MM-DD:YYYY-MM-DD" (inclusive).
EXAM_WINDOW = os.environ.get("EXAM_WINDOW", "2026-11-01:2026-11-30")
LIGHT_MINUTES = 20
MAX_MINUTES = 60
MIN_MINUTES = 5
UNBLOCK_MINUTES = 10   # share of today's time spent on a recorded blocker

# (title, [(minutes, what to do), ...]) -- each task's minutes add up to 60.
MISSIONS = [
    ("Build a long list of candidate organizations", [
        (10, "List past GSoC organizations that use Python / ML / LLM tooling (gsocorganizations.dev or the official archive)."),
        (30, "Pick 8-10 and note for each: main language, what the project does, last-commit date."),
        (15, "Mark any that look inactive or too large to start in. Do NOT assume any of them take part in 2027."),
        (5, "Write the list into your notes.")]),
    ("Cut the list down to 3", [
        (30, "For each candidate: docs quality, CONTRIBUTING file, 'good first issue' count, recent merged PRs."),
        (15, "Find each one's chat/forum and its AI-assistance policy (some restrict AI-written code or proposals)."),
        (10, "Choose 3 and rank them."),
        (5, "Record the ranking and why.")]),
    ("Choose ONE repository and read its rules", [
        (10, "Read README, CONTRIBUTING and the code of conduct end to end."),
        (15, "Read the project's AI / LLM contribution policy and write down what is allowed."),
        (20, "Skim the repo layout: top-level folders, entry point, where tests live."),
        (15, "Write a 5-line summary of what the project does and who uses it.")]),
    ("Get it running locally", [
        (10, "Clone it locally (forking on GitHub is an external change: do that yourself when you decide)."),
        (30, "Follow the setup docs; note every step that was unclear or failed."),
        (15, "Run the application or example once."),
        (5, "Save the exact commands that worked.")]),
    ("Run the tests", [
        (15, "Find how the project runs its tests and linters."),
        (25, "Run them. Separate failures that are already known from ones caused by your setup."),
        (15, "Open one test and explain what it checks."),
        (5, "Record the commands and the real output.")]),
    ("Map the architecture", [
        (20, "Draw the main modules and how they call each other (paper is fine)."),
        (25, "Trace one feature from entry point to result in the code."),
        (10, "List the 3 files you'd read first for any bug."),
        (5, "Write down what you still don't understand.")]),
    ("Learn the project's conventions from merged PRs", [
        (30, "Read 3 recently merged PRs: size, tests included, commit style, review comments."),
        (15, "Note what maintainers ask contributors to change."),
        (10, "Read how issues are claimed and assigned."),
        (5, "Write the conventions as a short checklist.")]),
    ("Join the community and shortlist issues", [
        (15, "Read the chat/forum for a while; observe how questions are asked and answered."),
        (30, "List 5 beginner-suitable issues. Check each is open, unclaimed and not already fixed."),
        (10, "For each, note what you'd need to learn first."),
        (5, "Pick a favourite. Posting anywhere is your decision.")]),
    ("Understand ONE issue deeply", [
        (15, "Read the issue and every comment; restate the problem in your own words."),
        (25, "Find the files and functions involved."),
        (15, "List the concepts you need and learn the most important one."),
        (5, "Write what a correct fix would look like.")]),
    ("Reproduce the problem", [
        (10, "Write down what you predict the current code does."),
        (30, "Reproduce the issue locally."),
        (15, "Compare prediction vs reality; find why they differ."),
        (5, "Record the reproduction steps.")]),
    ("Find the cause and plan the fix", [
        (35, "Trace the cause through the code."),
        (15, "Sketch the smallest change that fixes it, plus a test that would catch it."),
        (10, "Check the issue thread: is anyone else on it?")]),
    ("Make the small change locally", [
        (35, "Implement the fix or the test/doc improvement on a local branch."),
        (15, "Run the project's tests and linters."),
        (10, "Re-read your diff line by line.")]),
    ("Self-review before anything is submitted", [
        (15, "Can you explain every line of your change without help?"),
        (15, "Does it follow the conventions checklist and the project's AI policy?"),
        (15, "Are tests added and passing?"),
        (15, "Draft the PR description in your own words. Opening the PR is your decision.")]),
]



# (why it matters, done when, evidence to record) -- aligned with MISSIONS by position.
EXTRAS = [
    ("A wide first pass stops you committing to the first project you happen to see.",
     "You have 8-10 candidates, each with language, purpose and last-commit date.", "Your candidate list in notes."),
    ("Three well-checked options beat thirty skimmed ones.",
     "A ranked top 3, each with docs quality, beginner issues and AI-policy notes.", "The ranking plus one sentence of reasoning each."),
    ("One repository understood properly is worth more than many barely explored.",
     "You have chosen one repo and can state what it does and what its AI policy allows.", "Your 5-line summary and the policy note."),
    ("You cannot contribute to what you cannot run.",
     "The project runs on your machine from commands you saved.", "The exact commands and a note on anything that failed."),
    ("Passing tests are your safety net for every later change.",
     "You ran the test suite and can explain one test.", "The commands and the real output (pass/fail counts)."),
    ("Knowing the layout lets you locate the right code for any issue.",
     "You can trace one feature end to end and name 3 starting files.", "Your diagram or notes and your open questions."),
    ("Matching the project's habits makes your work easier to review.",
     "You have a conventions checklist drawn from 3 merged PRs.", "The checklist."),
    ("Choosing a suitable issue is half the work of a good first contribution.",
     "You have 5 verified-open candidate issues and a favourite.", "Issue links with notes on status and prerequisites."),
    ("You must understand a problem before you try to solve it.",
     "You can explain the issue and its code location without looking.", "Your own-words summary and the file/function list."),
    ("A problem you cannot reproduce is a problem you cannot verify you fixed.",
     "You reproduced it, or documented exactly why you could not.", "Reproduction steps and prediction-vs-reality notes."),
    ("A reasoned plan prevents wasted patches.",
     "You know the cause and have a minimal fix plan with a test idea.", "The cause and plan, written down."),
    ("A small, tested change you understand is the goal, not a big one.",
     "The change works locally and the project's tests pass.", "The diff and the test output."),
    ("It protects you and the maintainers' time, and keeps the work yours.",
     "You can explain every line and the AI-policy check passes.", "Your self-review checklist and PR draft."),
]
assert len(EXTRAS) == len(MISSIONS)

# --- helpers -----------------------------------------------------------------
def in_exam_window(today: date | None = None) -> bool:
    today = today or date.today()
    try:
        start, end = (date.fromisoformat(p) for p in EXAM_WINDOW.split(":"))
    except ValueError:
        return False
    return start <= today <= end


def _parse_range(text: str):
    """'2026-11-12' or '2026-11-12:2026-11-14' -> (start, end) or None."""
    try:
        parts = text.strip().split(":")
        a = date.fromisoformat(parts[0])
        b = date.fromisoformat(parts[1]) if len(parts) > 1 else a
    except (ValueError, IndexError):
        return None
    return (a, b) if a <= b else None


def _locks(user_id):
    out = []
    for f in memory_store.list_facts(user_id):
        if f["fact"].startswith(LOCK_PREFIX):
            rng = _parse_range(f["fact"][len(LOCK_PREFIX):])
            if rng:
                out.append((rng, f))
    return out


def _locked(user_id, today: date):
    return next((rng for rng, _ in _locks(user_id) if rng[0] <= today <= rng[1]), None)


def _mode(user_id, today: date) -> str:
    if _locked(user_id, today):
        return "exam-lock"
    return "exam-safe" if in_exam_window(today) else "normal"


def _plan(user_id):
    """The mission plan, created on first use. Returns the full plan dict."""
    for p in memory_store.list_plans(user_id):
        if p["goal"] == GOAL:
            return memory_store.get_plan(user_id, p["id"])
    pid = memory_store.create_plan(user_id, GOAL, [t for t, _ in MISSIONS])
    return memory_store.get_plan(user_id, pid)


def _blockers(user_id):
    return [f for f in memory_store.list_facts(user_id) if f["fact"].startswith(BLOCKER_PREFIX)]


def _next_index(plan):
    for i, s in enumerate(plan["steps"]):
        if s["status"] == "pending":
            return i
    return None


def _fit(items, budget: int):
    """Take checklist items in order until `budget` minutes are used. If even the first item is
    longer than the budget, show its opening `budget` minutes rather than nothing."""
    shown, used = [], 0
    for m, text in items:
        if used + m <= budget:
            shown.append((m, text))
            used += m
        elif not shown:
            return [(budget, "Start of: " + text)], budget
        else:
            break
    return shown, used


def _render(idx: int, budget: int, mode: str, blockers, last_note: str | None) -> str:
    title, items = MISSIONS[idx]
    why, done_when, evidence = EXTRAS[idx]
    full = sum(m for m, _ in items)
    out = [f"Mode: {mode}"]
    if mode == "exam-safe":
        out.append("Exams come first: do this only after today's study is done. "
                   "Heavy day? /mission busy.  Have more time? /mission 60.")
    if last_note:
        out.append(f"Last time you learned: {last_note}")

    unblock = 0
    if blockers:
        unblock = min(UNBLOCK_MINUTES, budget // 2)
        out.append(f"Blocker first ({unblock} min): \"{blockers[0]['fact'][len(BLOCKER_PREFIX):].strip()}\"\n"
                   "  Write down exactly what you tried and the exact error, search the project's docs/issues for it, "
                   "and draft one precise question for the project chat. Posting it is your decision.")
    work = budget - unblock
    shown, used = _fit(items, work) if work >= 5 else ([], 0)
    total = used + unblock
    short = f" of {full}" if used < full else ""
    out.append(f"Mission {idx + 1}/{len(MISSIONS)}: {title}  (~{total} min{short}{' - short' if used < full else ''})")
    out.append(f"Why: {why}")
    out.extend(f"  {m:>2} min  {text}" for m, text in shown)
    out.append(f"Done when: {done_when}")
    out.append(f"Evidence: {evidence}")
    if used < full:
        out.append("Part-done is fine: only mark it done once the 'Done when' is true. "
                   "Otherwise it simply stays for another day - no catch-up.")
    out.append("When finished: /log <what you learned>   Still stuck: /log blocked <why>")
    return "\n".join(out)


def _status(user_id, plan, idx, mode, blockers) -> str:
    prog = plan["progress"]
    lines = [f"{GOAL}: {prog['done']}/{prog['total']} missions ({prog['pct']}%)", f"Mode: {mode}"]
    for s in [s for s in plan["steps"] if s["status"] == "done" and s["note"]][-3:]:
        lines.append(f"  learned: {s['note']}")
    lines.append("Blocker: " + (blockers[0]["fact"][len(BLOCKER_PREFIX):].strip() if blockers else "none"))
    lines.append("Next action: " + (f"Mission {idx + 1} - {MISSIONS[idx][0]}" if idx is not None else "plan complete"))
    return "\n".join(lines)


# --- commands ------------------------------------------------------------------
def handle(user_id: str, arg: str = "", today: date | None = None) -> str:
    """/mission ..."""
    today = today or date.today()
    arg = (arg or "").strip()
    cmd, _, rest = arg.partition(" ")
    cmd, rest = cmd.lower(), rest.strip()
    plan = _plan(user_id)
    idx = _next_index(plan)
    mode = _mode(user_id, today)
    blockers = _blockers(user_id)

    if cmd == "busy":
        return ("Rest day: no GSoC task today. Nothing was marked done or skipped, "
                "so tomorrow's mission is unchanged. Good luck with the exam.")

    if cmd == "blocked":
        if not rest:
            return "Usage: /mission blocked <what is stopping you>"
        memory_store.remember(user_id, f"{BLOCKER_PREFIX} {rest}")
        return f"Blocker recorded: {rest}\nIt will show in /mission and /mission status."

    if cmd == "unblock":
        for f in blockers:
            memory_store.forget(user_id, f["id"])
        return "Blocker cleared." if blockers else "No blocker was recorded."

    if cmd == "done":
        if idx is None:
            return "All missions are already complete."
        step = memory_store.complete_next_step(user_id, plan["id"], note=rest or None)
        plan = memory_store.get_plan(user_id, plan["id"])
        nxt = _next_index(plan)
        tail = (f"Next: Mission {nxt + 1} - {MISSIONS[nxt][0]}" if nxt is not None
                else "Preparation plan complete. Pick a real issue and plan your first contribution.")
        return f"Done: {step['description']} ({plan['progress']['done']}/{plan['progress']['total']}).\n{tail}"

    if cmd == "status":
        return _status(user_id, plan, idx, mode, blockers)

    budget = None
    if cmd.isdigit():
        budget = int(cmd)
        if budget < MIN_MINUTES:
            return f"Minimum is {MIN_MINUTES} minutes: /mission <{MIN_MINUTES}-{MAX_MINUTES}>"
        budget = min(budget, MAX_MINUTES)
    elif cmd == "light":
        budget = LIGHT_MINUTES
    elif cmd == "full":
        budget = MAX_MINUTES
    elif cmd == "":
        budget = LIGHT_MINUTES if mode == "exam-safe" else MAX_MINUTES
    else:
        return ("Usage: /mission [minutes | full | light | busy | done <note> | blocked <text> | unblock | status]")
    if mode == "exam-lock":
        a, b = _locked(user_id, today)
        return (f"Exam lock is on ({a} to {b}): no GSoC task today. Nothing is owed afterwards. "
                f"Unlock with /gsoc unlock {a}{'' if a == b else ':' + b.isoformat()}.")
    if idx is None:
        return "All missions complete. Pick a real issue and plan your first contribution."
    notes = [st["note"] for st in plan["steps"] if st["status"] == "done" and st["note"]]
    return _render(idx, budget, mode, blockers, notes[-1] if notes else None)


def gsoc(user_id: str, arg: str = "", today: date | None = None) -> str:
    """/gsoc [status | lock <range> | unlock <range> | locks]"""
    today = today or date.today()
    cmd, _, rest = (arg or "").strip().partition(" ")
    cmd, rest = cmd.lower(), rest.strip()
    if cmd in ("", "status"):
        plan = _plan(user_id)
        return _status(user_id, plan, _next_index(plan), _mode(user_id, today), _blockers(user_id)) \
            + "\nToday: /mission   Log work: /log <note>   Exam day: /gsoc lock " + today.isoformat()
    if cmd == "locks":
        locks = _locks(user_id)
        return "\n".join(f"  {a} to {b}" for (a, b), _ in locks) if locks else "No exam locks set."
    if cmd in ("lock", "unlock"):
        rng = _parse_range(rest)
        if not rng:
            return f"Usage: /gsoc {cmd} YYYY-MM-DD   or   /gsoc {cmd} YYYY-MM-DD:YYYY-MM-DD"
        key = f"{rng[0]}:{rng[1]}" if rng[0] != rng[1] else f"{rng[0]}"
        existing = [f for r, f in _locks(user_id) if r == rng]
        if cmd == "lock":
            if not existing:
                memory_store.remember(user_id, f"{LOCK_PREFIX} {key}")
            return f"Exam lock set for {key}: no GSoC tasks on those days."
        for f in existing:
            memory_store.forget(user_id, f["id"])
        return f"Exam lock removed for {key}." if existing else f"No lock was set for {key}."
    return "Usage: /gsoc [status | lock <date|a:b> | unlock <date|a:b> | locks]"


def log(user_id: str, arg: str = "", today: date | None = None) -> str:
    """/log <what you learned>  |  /log blocked <text>"""
    arg = (arg or "").strip()
    if not arg:
        return "Usage: /log <what you finished or learned>   or   /log blocked <what is stopping you>"
    if arg.lower().startswith("blocked"):
        return handle(user_id, arg, today)
    return handle(user_id, "done " + arg, today)
