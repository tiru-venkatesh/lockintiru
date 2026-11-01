import csv
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for f in ("templates.json",):
        with open(os.path.join(os.path.dirname(jarvis.__file__), f), "rb") as src:
            (tmp_path / f).write_bytes(src.read())
    monkeypatch.setattr(jarvis, "SENT_LOG", str(tmp_path / "sent_log.csv"))
    monkeypatch.setattr(jarvis, "ROLE_SEND_DELAY", 0)
    monkeypatch.setattr(jarvis, "resume_available", lambda: False)
    sent = []
    monkeypatch.setattr(jarvis, "send_gmail", lambda to, s, b, attach_path=None: sent.append((to, s, b)) or "id1")
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    return types.SimpleNamespace(dir=tmp_path, sent=sent)


def write(env, rows):
    p = env.dir / "r.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["email", "name", "type", "personal_sentence"])
        w.writeheader()
        w.writerows(rows)
    return str(p)


GOOD = {"email": "a@uni.edu", "name": "Prof. A", "type": "ml", "personal_sentence": "I like your work on X."}


def test_sends_professional_email(env):
    jarvis.bulk_role_send(write(env, [GOOD]))
    to, subject, body = env.sent[0]
    assert to == "a@uni.edu" and subject.startswith("Research internship")
    assert "Dear Prof. A," in body and "second-year" in body and "I like your work on X." in body
    assert "10-15 hours" in body and "Best regards,\nTiru Venkatesh" in body
    assert not jarvis.PLACEHOLDER_RE.search(body)


def test_skips_bad_duplicate_and_missing_sentence(env):
    rows = [GOOD, GOOD, {**GOOD, "email": "bad"}, {**GOOD, "email": "b@uni.edu", "personal_sentence": ""}]
    jarvis.bulk_role_send(write(env, rows))
    assert [s[0] for s in env.sent] == ["a@uni.edu"]


def test_generic_flag_allows_missing_sentence(env):
    jarvis.bulk_role_send(write(env, [{**GOOD, "personal_sentence": ""}]), allow_generic=True)
    assert len(env.sent) == 1


def test_never_resends(env):
    p = write(env, [GOOD])
    jarvis.bulk_role_send(p)
    jarvis.bulk_role_send(p)
    assert len(env.sent) == 1


def test_cap_and_limit(env, monkeypatch):
    monkeypatch.setattr(jarvis, "ROLE_SEND_MAX", 3)
    p = write(env, [{**GOOD, "email": f"p{i}@uni.edu"} for i in range(6)])
    jarvis.bulk_role_send(p, limit=2)
    assert len(env.sent) == 2


def test_cancel_sends_nothing(env, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    jarvis.bulk_role_send(write(env, [GOOD]))
    assert env.sent == []


def test_failure_not_logged_so_retry_possible(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(jarvis, "send_gmail", boom)
    jarvis.bulk_role_send(write(env, [GOOD]))
    assert jarvis.load_sent_log(str(env.dir / "sent_log.csv")) == set()


def test_iitb_list_all_valid_and_known_types():
    here = os.path.dirname(os.path.abspath(jarvis.__file__))
    types_ = set(__import__("json").load(open(os.path.join(here, "templates.json"))))
    rows = list(csv.DictReader(open(os.path.join(here, "recipients_iitb.csv"), encoding="utf-8")))
    assert len(rows) == 26
    for r in rows:
        assert r["email"].endswith("@cse.iitb.ac.in") and r["type"] in types_ and r["personal_sentence"]
