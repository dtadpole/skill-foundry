#!/usr/bin/env python3
"""
Code Agent — runs Claude Code in tmux with Telegram I/O bridging.

Commands:
  start   <task> [--session NAME] [--workdir DIR]   start a new coding session
  status  [--session NAME]                           show current pane output
  answer  <text> [--session NAME]                    relay user answer back to Claude Code
  stop    [--session NAME]                           kill the tmux session
"""

import argparse
import subprocess
import time
import json
import sys
import re
from pathlib import Path
from datetime import datetime

# ── State dirs ─────────────────────────────────────────────────────────────────
STATE_DIR = Path.home() / ".code-agent"
STATE_DIR.mkdir(exist_ok=True)


def state_file(session: str) -> Path:
    return STATE_DIR / f"{session}.json"


def question_file(session: str) -> Path:
    return STATE_DIR / f"{session}.question"


def answer_file(session: str) -> Path:
    return STATE_DIR / f"{session}.answer"


# ── tmux helpers ────────────────────────────────────────────────────────────────
def tmux_exists(session: str) -> bool:
    r = subprocess.run(["tmux", "has-session", "-t", session],
                       capture_output=True)
    return r.returncode == 0


def capture_pane(session: str, lines: int = 150) -> str:
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"],
        capture_output=True, text=True
    )
    return r.stdout


def send_keys(session: str, text: str, enter: bool = True):
    cmd = ["tmux", "send-keys", "-t", session, text]
    if enter:
        cmd.append("Enter")
    subprocess.run(cmd)


# ── Question detection ──────────────────────────────────────────────────────────
# Patterns that suggest Claude Code is waiting for user input
QUESTION_SIGNALS = [
    r"\(y/n\)",
    r"\(yes/no\)",
    r"Do you want",
    r"Should I",
    r"Would you like",
    r"Please confirm",
    r"Enter .{0,40}:",
    r"Choose .{0,40}:",
    r"Select .{0,40}:",
    r"\? $",                  # ends with "? "
    r"Press Enter to",
]

IDLE_SIGNALS = [
    r"^\s*>\s*$",             # bare ">" prompt
    r"Human:\s*$",
    r"╰─>\s*$",               # Claude Code input cursor
]

_COMPILED_Q = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in QUESTION_SIGNALS]
_COMPILED_I = [re.compile(p, re.MULTILINE) for p in IDLE_SIGNALS]


def detect_question(pane: str) -> str | None:
    """Return a short excerpt if the pane looks like Claude Code is asking something."""
    tail = pane[-3000:]  # look at recent output only
    for pat in _COMPILED_Q:
        m = pat.search(tail)
        if m:
            # grab the surrounding context (up to 5 lines)
            lines = tail.splitlines()
            # find which line matched
            for i, line in enumerate(reversed(lines)):
                if pat.search(line):
                    excerpt_lines = lines[max(0, len(lines)-i-5) : len(lines)-i+1]
                    return "\n".join(l for l in excerpt_lines if l.strip())
    # Also trigger if last non-empty line ends with "?"
    non_empty = [l for l in tail.splitlines() if l.strip()]
    if non_empty and non_empty[-1].strip().endswith("?"):
        return "\n".join(non_empty[-4:])
    return None


def is_done(pane: str) -> bool:
    """Return True if Claude Code has exited or returned to shell prompt."""
    tail = pane[-500:]
    done_patterns = [r"\$\s*$", r"% $"]
    for p in done_patterns:
        if re.search(p, tail, re.MULTILINE):
            return True
    return False


# ── OpenClaw delivery ───────────────────────────────────────────────────────────
def deliver(message: str):
    """Send a message to the user via openclaw → last channel (Telegram)."""
    subprocess.run(
        ["openclaw", "agent", "--channel", "last", "--deliver", message],
        capture_output=True
    )


# ── State helpers ───────────────────────────────────────────────────────────────
def save_state(session: str, **kwargs):
    sf = state_file(session)
    state = json.loads(sf.read_text()) if sf.exists() else {}
    state.update(kwargs)
    sf.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def load_state(session: str) -> dict:
    sf = state_file(session)
    return json.loads(sf.read_text()) if sf.exists() else {}


# ── Commands ─────────────────────────────────────────────────────────────────────
def cmd_start(task: str, session: str, workdir: str | None, poll: int):
    # Kill any existing session with same name
    if tmux_exists(session):
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
        time.sleep(0.5)

    # Create new tmux session
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "50"
    ])

    # cd to workdir if specified
    if workdir:
        send_keys(session, f"cd {workdir}")
        time.sleep(0.3)

    # Launch Claude Code
    send_keys(session, "claude")
    time.sleep(4)  # wait for Claude Code to start

    # Send the task
    send_keys(session, task)

    save_state(session,
               task=task,
               workdir=workdir or str(Path.cwd()),
               started=datetime.now().isoformat(),
               status="running",
               pending_question=False)

    print(f"[code_agent] Session '{session}' started. Monitoring every {poll}s.")
    deliver(f"🚀 Coding session **{session}** started.\nTask: {task}\n\nI'll notify you if Claude Code needs input.")

    # Enter monitor loop
    _monitor_loop(session, poll)


def _monitor_loop(session: str, poll: int):
    last_question_text = ""
    last_pane_tail = ""

    while True:
        time.sleep(poll)

        if not tmux_exists(session):
            deliver(f"✅ Coding session **{session}** has ended.")
            save_state(session, status="done")
            break

        pane = capture_pane(session)
        pane_tail = pane[-1000:]

        # Skip if output hasn't changed
        if pane_tail == last_pane_tail:
            continue
        last_pane_tail = pane_tail

        # Check if done (back to shell)
        if is_done(pane):
            deliver(f"✅ Coding session **{session}** complete! Reply 'status {session}' to see output.")
            save_state(session, status="done")
            break

        # Check for question
        question = detect_question(pane)
        if question and question != last_question_text:
            last_question_text = question
            qf = question_file(session)
            qf.write_text(question)
            af = answer_file(session)
            af.unlink(missing_ok=True)
            save_state(session, pending_question=True, last_question=question)

            deliver(
                f"🤔 **Claude Code [{session}] is asking:**\n\n{question}\n\n"
                f"Reply with your answer and I'll pass it along."
            )

            # Wait for answer (up to 30 min)
            waited = 0
            while waited < 1800:
                time.sleep(10)
                waited += 10
                if af.exists():
                    answer = af.read_text().strip()
                    af.unlink()
                    qf.unlink(missing_ok=True)
                    send_keys(session, answer)
                    save_state(session, pending_question=False)
                    last_question_text = ""  # reset so same question can re-trigger
                    break
            else:
                deliver(f"⚠️ No answer received for 30 min — session **{session}** may be stalled.")


def cmd_status(session: str, lines: int):
    if not tmux_exists(session):
        state = load_state(session)
        print(f"Session '{session}' not running. Last status: {state.get('status', 'unknown')}")
        return
    pane = capture_pane(session, lines)
    print(pane)

    # Also check pending question
    qf = question_file(session)
    if qf.exists():
        print(f"\n[PENDING QUESTION]\n{qf.read_text()}")


def cmd_answer(text: str, session: str):
    af = answer_file(session)
    af.write_text(text)
    print(f"[code_agent] Answer written for session '{session}'.")


def cmd_stop(session: str):
    if tmux_exists(session):
        subprocess.run(["tmux", "kill-session", "-t", session])
        print(f"[code_agent] Session '{session}' killed.")
    else:
        print(f"[code_agent] Session '{session}' not found.")
    save_state(session, status="stopped")


def cmd_list():
    r = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True)
    print(r.stdout or "No tmux sessions running.")
    # Show any pending questions
    for qf in STATE_DIR.glob("*.question"):
        session = qf.stem
        print(f"\n⚠️  Pending question in session '{session}':\n{qf.read_text()}")


# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Code Agent — Claude Code in tmux with Telegram I/O")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start a new coding session")
    p_start.add_argument("task", help="Task description for Claude Code")
    p_start.add_argument("--session", default="coding", help="tmux session name")
    p_start.add_argument("--workdir", default=None, help="Working directory")
    p_start.add_argument("--poll", type=int, default=15, help="Poll interval in seconds")

    p_status = sub.add_parser("status", help="Show current pane output")
    p_status.add_argument("--session", default="coding")
    p_status.add_argument("--lines", type=int, default=80)

    p_answer = sub.add_parser("answer", help="Send answer to pending question")
    p_answer.add_argument("text", help="Answer text")
    p_answer.add_argument("--session", default="coding")

    p_stop = sub.add_parser("stop", help="Kill coding session")
    p_stop.add_argument("--session", default="coding")

    sub.add_parser("list", help="List active sessions and pending questions")

    args = parser.parse_args()

    if args.cmd == "start":
        cmd_start(args.task, args.session, args.workdir, args.poll)
    elif args.cmd == "status":
        cmd_status(args.session, args.lines)
    elif args.cmd == "answer":
        cmd_answer(args.text, args.session)
    elif args.cmd == "stop":
        cmd_stop(args.session)
    elif args.cmd == "list":
        cmd_list()


if __name__ == "__main__":
    main()
