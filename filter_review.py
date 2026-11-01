#!/usr/bin/env python3
"""
filter_review.py - make recipients_iit_all_review.csv safe to hand-review.

    python filter_review.py recipients_iit_all_review.csv

Writes:
    recipients_review_clean.csv   email,name,type,personal_sentence   (review, fill personal_sentence, then send)
    recipients_review_dropped.csv email,name,reason                   (why each row was removed)

Drops: already-emailed, role/office aliases, placeholder addresses, rows whose
type has no template (personal/institute), rows with junk or missing names.
Name must look like a person AND fit the email local-part, otherwise the row
is dropped (not downgraded to "Professor") -- these are cold emails to people
you have no other signal about, so unverified rows stay out.
"""
import csv, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clean_recipients import ROLE_LOCAL, ROLE_EXACT, clean_name, name_fits_email

EXTRA_ROLE = re.compile(
    r"(office|store|stores|^fic|[._-]fic|help|admin|^hod|[._-]hod|^ccs|firstname|"
    r"^adean|^dean|^head|^ahead|alumni|patent|mess|^cse\d*$|^info|^contact|^it$)", re.I)
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
STUDENT_LOCAL = re.compile(r"\d{2}[a-z]{2,4}\d{3,}|^\d+[a-z]?$|^[a-z]\d{4,}$", re.I)  # 24csz0016, 27902a, a26111


def sent_set():
    out = set()
    for fn in ("receipts.txt", "emails.txt"):
        if os.path.exists(fn):
            for ln in open(fn, encoding="utf-8-sig"):
                first = ln.strip().split(",")[0].strip().strip('"').lower()
                if "@" in first:
                    out.add(first)
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python filter_review.py recipients_iit_all_review.csv")
    types = set(json.load(open("templates.json", encoding="utf-8")).keys())
    already = sent_set()
    keep, drop, seen = [], [], set()
    with open(sys.argv[1], encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            email = (r.get("email") or "").strip().lower()
            raw = (r.get("name") or "").strip()
            typ = (r.get("type") or "").strip().lower()
            if not email:
                continue
            local = email.split("@")[0]
            reason = None
            if email in seen:
                reason = "duplicate"
            elif not EMAIL_RE.match(email):
                reason = "invalid email"
            elif email in already:
                reason = "already emailed"
            elif typ not in types:
                reason = f"type '{typ or 'blank'}' has no template"
            elif local in ROLE_EXACT or ROLE_LOCAL.search(local) or EXTRA_ROLE.search(local):
                reason = "role/office/placeholder address"
            elif STUDENT_LOCAL.search(local):
                reason = "looks like a student/staff ID address"
            else:
                name = clean_name(raw)
                if not name:
                    reason = f"junk/missing name ({raw[:30]!r})"
                elif not name_fits_email(name, email):
                    reason = f"name does not fit email: {name}"
                else:
                    keep.append({"email": email, "name": f"Prof. {name}", "type": typ, "personal_sentence": ""})
            seen.add(email)
            if reason:
                drop.append((email, raw, reason))

    with open("recipients_review_clean.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["email", "name", "type", "personal_sentence"])
        w.writeheader(); w.writerows(keep)
    with open("recipients_review_dropped.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["email", "name", "reason"]); w.writerows(drop)

    from collections import Counter
    print(f"kept {len(keep)} -> recipients_review_clean.csv")
    print(f"dropped {len(drop)} -> recipients_review_dropped.csv")
    for k, n in Counter(re.sub(r"\(.*|'.*", "", d[2]).strip() for d in drop).most_common():
        print(f"   {n:4d}  {k}")


if __name__ == "__main__":
    main()
