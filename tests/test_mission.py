import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import jarvis  # noqa: E402
import memory_store  # noqa: E402
import mission  # noqa: E402

U = "tester"
EXAM_DAY, FREE_DAY = date(2026, 11, 10), date(2026, 12, 10)   # explicit dates: tests never depend on today's date


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_store, "DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setattr(mission, "EXAM_WINDOW", "2026-11-01:2026-11-30")
    memory_store.init_db()


def m(arg="", day=FREE_DAY):
    return mission.handle(U, arg, today=day)


# --- mission content ----------------------------------------------------------------
def test_first_mission_has_all_required_fields_and_60_minutes():
    out = m()
    for field in ("Mode: normal", "Mission 1/13", "~60 min", "Why:", "Done when:", "Evidence:", "/log"):
        assert field in out
    assert len(memory_store.list_plans(U)) == 1 and memory_store.list_plans(U)[0]["goal"] == mission.GOAL
    m()
    assert len(memory_store.list_plans(U)) == 1            # idempotent: no duplicate plan


def test_every_mission_is_60_minutes_and_has_extras():
    assert all(sum(x for x, _ in items) == 60 for _, items in mission.MISSIONS)
    assert len(mission.EXTRAS) == len(mission.MISSIONS) and all(all(e) for e in mission.EXTRAS)


# --- exam modes -----------------------------------------------------------------------
def test_exam_window_defaults_to_short_exam_safe_mission():
    out = m(day=EXAM_DAY)
    assert "Mode: exam-safe" in out and "Exams come first" in out and "short" in out
    assert 0 < int(out.split("(~")[1].split(" min")[0]) <= mission.LIGHT_MINUTES
    assert "no catch-up" in out


def test_full_overrides_exam_safe_and_normal_day_is_full():
    assert "~60 min" in m("full", EXAM_DAY) and "~60 min" in m("60", EXAM_DAY)
    assert "~60 min" in m(day=FREE_DAY)


def test_exam_window_boundaries():
    assert mission.in_exam_window(date(2026, 11, 1)) and mission.in_exam_window(date(2026, 11, 30))
    assert not mission.in_exam_window(date(2026, 10, 31)) and not mission.in_exam_window(date(2026, 12, 1))


def test_lock_blocks_missions_on_those_days_only_and_persists():
    assert "lock set" in mission.gsoc(U, "lock 2026-12-10:2026-12-11", FREE_DAY)
    out = m(day=FREE_DAY)
    assert "Exam lock is on" in out and "Mission 1" not in out and "Nothing is owed" in out
    assert "Mission 1/13" in m(day=date(2026, 12, 12))      # next day is normal
    assert "2026-12-10 to 2026-12-11" in mission.gsoc(U, "locks")
    assert "Mode: exam-lock" in mission.gsoc(U, "", FREE_DAY)
    assert "removed" in mission.gsoc(U, "unlock 2026-12-10:2026-12-11")
    assert "Mission 1/13" in m(day=FREE_DAY)


def test_lock_validation_and_no_duplicates():
    assert "Usage" in mission.gsoc(U, "lock tomorrow")
    mission.gsoc(U, "lock 2026-12-10")
    mission.gsoc(U, "lock 2026-12-10")
    assert len([f for f in memory_store.list_facts(U) if f["fact"].startswith(mission.LOCK_PREFIX)]) == 1
    assert "No lock was set" in mission.gsoc(U, "unlock 2027-01-01")


def test_busy_changes_nothing():
    assert "Rest day" in m("busy", EXAM_DAY)
    assert memory_store.get_plan(U, mission._plan(U)["id"])["progress"]["done"] == 0
    assert "Mission 1/13" in m(day=FREE_DAY)


def test_skipped_days_create_no_backlog():
    for d in (date(2026, 12, 1), date(2026, 12, 2), date(2026, 12, 3)):
        assert "Mission 1/13" in m(day=d)                   # still just the same single task


# --- progress, continuity, blockers -------------------------------------------------------
def test_done_advances_and_never_repeats():
    first = m()
    out = m("done mapped 10 orgs")
    assert "1/13" in out and "Mission 2" in out
    assert "Mission 2/13" in m() and m() != first
    assert "learned: mapped 10 orgs" in m("status")


def test_log_is_done_or_blocker():
    assert "Usage" in mission.log(U, "")
    assert "Done:" in mission.log(U, "ran the tests, 42 passed")
    assert "Blocker recorded" in mission.log(U, "blocked pip install fails")
    assert "pip install fails" in m()
    assert "learned: ran the tests, 42 passed" in mission.gsoc(U, "")


def test_blocker_roundtrip():
    assert "Usage" in m("blocked")
    m("blocked cannot build on Windows")
    assert "cannot build on Windows" in m() and "cannot build" in m("status")
    assert "cleared" in m("unblock") and "Blocker: none" in m("status") and "No blocker" in m("unblock")


def test_state_survives_restart():
    m("done first")
    m("blocked stuck on setup")
    mission.gsoc(U, "lock 2026-12-20")
    # "restart": brand-new connection to the same DB file, no in-memory state is kept by mission.py
    memory_store.init_db()
    st = mission.gsoc(U, "", date(2026, 12, 20))
    assert "1/13" in st and "stuck on setup" in st and "exam-lock" in st and "Mission 2" in st


def test_full_cycle_completes_then_stops():
    for _ in mission.MISSIONS:
        m("done ok")
    assert "plan complete" in m("status") and "All missions" in m() and "All missions" in m("done")
    assert memory_store.list_plans(U)[0]["status"] == "done"


def test_unknown_subcommands_show_usage():
    assert "Usage" in m("frobnicate") and "Usage" in mission.gsoc(U, "frobnicate")


# --- CLI wiring + safety --------------------------------------------------------------------------
def test_cli_commands_are_wired_and_never_call_llm_or_email(monkeypatch, capsys):
    monkeypatch.setattr(mission, "EXAM_WINDOW", "2000-01-01:2000-01-02")    # today is not an exam day
    monkeypatch.setattr(jarvis, "check_groq_setup", lambda: None)
    monkeypatch.setattr(jarvis, "send_gmail", lambda *a, **k: pytest.fail("email must not be sent"))
    monkeypatch.setattr(jarvis.requests, "post", lambda *a, **k: pytest.fail("no LLM call expected"), raising=False)
    inputs = iter(["/mission", "/log finished mission one", "/status", "/gsoc", "/plans", "exit"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    jarvis.main()
    out = capsys.readouterr().out
    assert "Mission 1/13" in out and "Done:" in out and "Next action: Mission 2" in out
    assert "Today: /mission" in out and "GSoC 2027 preparation" in out


# --- time-aware missions + continuity ---------------------------------------------------------
def minutes_of(out):
    return int(out.split("(~")[1].split(" min")[0])


@pytest.mark.parametrize("n", [5, 10, 15, 25, 40, 60])
def test_mission_fits_the_time_you_have(n):
    out = m(str(n))
    assert 0 < minutes_of(out) <= n
    assert "Mission 1/13" in out and "Done when:" in out          # same objective at any length


def test_ten_minutes_still_gives_a_useful_task():
    out = m("10")
    assert "min  List past GSoC organizations" in out              # first real step, not an empty plan


def test_first_step_longer_than_budget_is_shown_as_a_start():
    out = m("5", EXAM_DAY)                                          # smallest step of mission 1 is 10 min
    assert "Start of: List past GSoC organizations" in out and minutes_of(out) == 5


def test_minutes_validation_and_cap():
    assert "Minimum is 5" in m("3")
    assert minutes_of(m("200")) <= mission.MAX_MINUTES == 60


def test_blocker_and_last_note_shape_the_next_mission():
    m("done shortlisted 3 repos")
    m("blocked pip install fails with a compiler error")
    out = m("30")
    assert "Last time you learned: shortlisted 3 repos" in out
    assert "Blocker first" in out and "pip install fails with a compiler error" in out
    assert "Mission 2/13" in out                                      # same task continues; it does not jump away
    assert minutes_of(out) <= 30
    m("unblock")
    assert "Blocker first" not in m("30")


def test_tiny_budget_splits_time_with_the_blocker():
    m("blocked stuck")
    out = m("10")
    assert "Blocker first (5 min)" in out and minutes_of(out) <= 10


def test_priority1_scenario_run_block_restart_status_run_again():
    first = m("20")
    assert "Mission 1/13" in first
    mission.log(U, "blocked cannot reach the project chat")          # worked on it, got stuck
    memory_store.init_db()                                            # "restart"
    st = mission.handle(U, "status", FREE_DAY)
    assert "cannot reach the project chat" in st and "Next action: Mission 1" in st
    again = m("20")
    assert "Mission 1/13" in again and "Blocker first" in again and "cannot reach the project chat" in again
