#!/usr/bin/env python3
"""
resume_followup.py - send the resume to the 5 professors whose first email
went out WITHOUT the PDF (the "tiru-venkatesh.pdf not found" run).

    python resume_followup.py            # preview only
    python resume_followup.py --send     # preview, then asks y/N, then sends

Logs sent follow-ups to followups_sent.txt so a re-run never double-sends.
"""
import os, sys, time
import jarvis

TARGETS = [
    ("aad@cse.iitb.ac.in", "Prof. Ajit A Diwan"),
    ("abhijit.das@cse.iith.ac.in", "Professor"),
    ("abyaym@iitp.ac.in", "Professor"),
    ("adarshbarik1@cse.iitd.ac.in", "Prof. Adarsh Barik"),
    ("addileep@iitdh.ac.in", "Prof. Dileep A D"),
]
SUBJECT = "Resume attached - Research internship inquiry (2nd-year CSE student)"
BODY = (
    "Dear {name},\n\n"
    "I recently wrote to you about a research internship. My resume was meant to be "
    "attached to that email but did not go through, so I am attaching it here.\n\n"
    "Apologies for the extra message, and thank you for your time.\n\n"
    "Best regards,\nTiru Venkatesh\nB.Tech CSE, Second Year\nJNTU Narasaraopeta\n"
    "Portfolio: https://tiru-venkatesh.github.io\n"
)
LOG = "followups_sent.txt"


def main():
    if not jarvis.resume_available():
        sys.exit(f"Resume not found at {jarvis.RESUME_PATH}. Nothing sent.")
    done = set(open(LOG).read().split()) if os.path.exists(LOG) else set()
    todo = [(e, n) for e, n in TARGETS if e not in done]
    print(f"Attachment: {jarvis.RESUME_PATH}\nSubject: {SUBJECT}\n")
    print(BODY.format(name="<name>"))
    for e, n in todo:
        print(f"  -> {e}  ({n})")
    if not todo:
        print("All follow-ups already sent."); return
    if "--send" not in sys.argv:
        print("\nPreview only. Re-run with --send to send."); return
    if not jarvis.ask_yes_no(f"\nSend {len(todo)} follow-ups with resume?"):
        print("Cancelled."); return
    for i, (e, n) in enumerate(todo):
        try:
            mid = jarvis.send_gmail(e, SUBJECT, BODY.format(name=n), attach_path=jarvis.RESUME_PATH)
            open(LOG, "a").write(e + "\n")
            print(f"  [ok]   {e} (id: {mid})")
        except Exception as ex:
            print(f"  [fail] {e}: {ex}")
        if i < len(todo) - 1:
            time.sleep(jarvis.BULK_DELAY_SECONDS)


if __name__ == "__main__":
    main()
