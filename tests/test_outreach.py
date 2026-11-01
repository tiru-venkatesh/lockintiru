import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import jarvis  # noqa: E402

CSV_IITB = Path(__file__).parent.parent / "recipients_iitb.csv"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(jarvis, "SENT_LOG", str(tmp_path / "sent_log.csv"))
    monkeypatch.setattr(jarvis, "ROLE_SEND_DELAY", 0)
    monkeypatch.setattr(jarvis.time, "sleep", lambda _: None)
    monkeypatch.setattr(jarvis, "load_templates",
                        lambda: jarvis.json.loads((Path(__file__).parent.parent / "templates.json").read_text("utf-8")))
    monkeypatch.setattr(jarvis, "resume_available", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    sent = []
    monkeypatch.setattr(jarvis, "send_gmail", lambda to, s, b, attach_path=None: sent.append((to, s, b)) or "id1")
    return sent


def write(rows, name="r.csv"):
    with open(name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["email", "name", "type", "personal_sentence"])
        w.writeheader()
        w.writerows(rows)
    return name


G = {"email": "a@uni.edu", "name": "Prof. A", "type": "ml", "personal_sentence": "I liked your work on bandits."}


def test_sends_personalised_professional_email(env):
    jarvis.bulk_role_send(write([G]))
    to, subject, body = env[0]
    assert to == "a@uni.edu" and subject.startswith("Research internship inquiry")
    assert body.startswith("Dear Prof. A,") and "I liked your work on bandits." in body
    assert "second-year" in body and "Thank you for your time." in body
    assert not jarvis.PLACEHOLDER_RE.search(body)


def test_skips_missing_personal_sentence_unless_generic(env):
    row = {**G, "personal_sentence": ""}
    jarvis.bulk_role_send(write([row]))
    assert env == []
    jarvis.bulk_role_send(write([row]), allow_generic=True)
    assert len(env) == 1


def test_never_double_sends_and_logs(env):
    jarvis.bulk_role_send(write([G]))
    jarvis.bulk_role_send(write([G]))
    assert len(env) == 1
    assert jarvis.load_sent_log() == {"a@uni.edu"}


def test_invalid_duplicate_and_unknown_type(env):
    jarvis.bulk_role_send(write([G, G, {**G, "email": "bad"}]))
    assert [e[0] for e in env] == ["a@uni.edu"]
    jarvis.bulk_role_send(write([{**G, "email": "z@uni.edu", "type": "nope"}]))
    assert len(env) == 1


def test_cap_and_limit(env, monkeypatch):
    monkeypatch.setattr(jarvis, "ROLE_SEND_MAX", 3)
    jarvis.bulk_role_send(write([{**G, "email": f"p{i}@uni.edu"} for i in range(6)]))
    assert len(env) == 3
    jarvis.bulk_role_send(write([{**G, "email": f"q{i}@uni.edu"} for i in range(6)]), limit=1)
    assert len(env) == 4


def test_cancel_sends_nothing(env, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    jarvis.bulk_role_send(write([G]))
    assert env == []


def test_failure_not_logged_as_sent(env, monkeypatch):
    def boom(to, s, b, attach_path=None):
        raise RuntimeError("quota")
    monkeypatch.setattr(jarvis, "send_gmail", boom)
    jarvis.bulk_role_send(write([G]))
    assert jarvis.load_sent_log() == set()


def test_iitb_list_is_valid_and_fully_templated():
    rows = list(csv.DictReader(open(CSV_IITB, encoding="utf-8")))
    types = set(jarvis.json.loads((Path(__file__).parent.parent / "templates.json").read_text("utf-8")))
    assert len(rows) == 26
    assert all(r["email"].endswith("@cse.iitb.ac.in") and r["type"] in types and r["personal_sentence"] for r in rows)
    assert len({r["email"] for r in rows}) == 26
