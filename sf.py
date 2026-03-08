#!/usr/bin/env python3
"""sf.py — Unified CLI for skill-foundry tools (thread_tracker, user_ledger)."""

import sys
import argparse
from pathlib import Path

# Ensure skill-foundry root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.thread_tracker.manager import ThreadManager
from tools.thread_tracker.models import ThreadStatus
from tools.user_ledger.logger import UserLedger
from tools.user_ledger.reader import read_messages, list_sessions


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

VALID_STATUSES = [s.value for s in ThreadStatus]


def _fmt_topic_line(t):
    """Format a one-line topic summary."""
    line = f"  {t.topic_id[:8]}  [{t.status.value}]  {t.title}"
    if t.current_action:
        line += f" — {t.current_action}"
    return line


def threads_list(args):
    mgr = ThreadManager()
    active = mgr.list_active()
    if not active:
        print("No active threads.")
        return
    print(f"Active threads ({len(active)}):")
    for t in active:
        print(_fmt_topic_line(t))


def threads_all(args):
    mgr = ThreadManager()
    all_threads = mgr.list_all()
    if not all_threads:
        print("No threads.")
        return
    print(f"All threads ({len(all_threads)}):")
    for t in all_threads:
        print(_fmt_topic_line(t))


def threads_show(args):
    mgr = ThreadManager()
    t = mgr.get(args.topic_id)
    if not t:
        print(f"Error: topic not found: {args.topic_id}", file=sys.stderr)
        sys.exit(1)
    print(f"Topic: {t.title}")
    print(f"  ID:       {t.topic_id}")
    print(f"  Status:   {t.status.value}")
    print(f"  Created:  {t.created_at}")
    print(f"  Updated:  {t.updated_at}")
    if t.original_request:
        print(f"  Request:  {t.original_request}")
    if t.current_action:
        print(f"  Current:  {t.current_action}")
    if t.tags:
        print(f"  Tags:     {', '.join(t.tags)}")
    if t.done:
        print(f"  Done:")
        for d in t.done:
            print(f"    - {d}")
    if t.pending:
        print(f"  Pending:")
        for p in t.pending:
            print(f"    - {p}")
    if t.tool_calls:
        print(f"  Tool calls:")
        for tc in t.tool_calls:
            line = f"    - {tc['tool']}"
            if tc.get("result"):
                line += f": {tc['result']}"
            print(line)
    if t.events:
        print(f"  Events ({len(t.events)}):")
        for e in t.events:
            print(f"    [{e.timestamp[:19]}] {e.event_type}: {e.description}")


def threads_add(args):
    mgr = ThreadManager()
    topic = mgr.create(title=args.title, description=args.original_request)
    topic.original_request = args.original_request
    mgr.save()
    print(topic.topic_id)


def threads_status(args):
    status_str = args.status.lower()
    if status_str not in VALID_STATUSES:
        print(f"Error: invalid status '{args.status}'. Valid: {', '.join(VALID_STATUSES)}", file=sys.stderr)
        sys.exit(1)
    mgr = ThreadManager()
    try:
        t = mgr.update_status(args.topic_id, ThreadStatus(status_str))
        print(f"Updated {t.topic_id[:8]} → {t.status.value}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_progress(args):
    mgr = ThreadManager()
    try:
        t = mgr.add_progress(args.topic_id, args.what_was_done)
        print(f"Logged progress on {t.topic_id[:8]}: {args.what_was_done}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_pending(args):
    mgr = ThreadManager()
    try:
        t = mgr.add_pending(args.topic_id, args.next_action)
        print(f"Added pending on {t.topic_id[:8]}: {args.next_action}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_resolve(args):
    mgr = ThreadManager()
    try:
        t = mgr.resolve_pending(args.topic_id, args.action)
        print(f"Resolved on {t.topic_id[:8]}: {args.action}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_current(args):
    mgr = ThreadManager()
    try:
        t = mgr.set_current(args.topic_id, args.current_action)
        print(f"Set current on {t.topic_id[:8]}: {args.current_action}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_tool(args):
    mgr = ThreadManager()
    try:
        t = mgr._require(args.topic_id)
        t.log_tool_call(args.tool_name, result=args.result_summary)
        mgr.save()
        print(f"Logged tool call on {t.topic_id[:8]}: {args.tool_name}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_close(args):
    mgr = ThreadManager()
    try:
        t = mgr.close(args.topic_id, summary=args.summary)
        print(f"Closed {t.topic_id[:8]}: {t.title}")
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def threads_snapshot(args):
    mgr = ThreadManager()
    print(mgr.snapshot())


# ---------------------------------------------------------------------------
# UserLedger
# ---------------------------------------------------------------------------

def ledger_session_start(args):
    ledger = UserLedger(
        channel=args.channel,
        user_id=args.user_id,
        user_name=args.user_name,
    )
    print(ledger._session_id)


def ledger_log(args):
    role = args.role.lower()
    if role not in ("user", "assistant", "system"):
        print(f"Error: invalid role '{args.role}'. Use: user, assistant, system", file=sys.stderr)
        sys.exit(1)
    ledger = UserLedger(session_id=args.session_id)
    ledger.log_message(role=role, content=args.content)
    print(f"Logged {role} message to session {args.session_id[:8]}")


def ledger_session_end(args):
    ledger = UserLedger(session_id=args.session_id)
    rec = ledger.close(summary=args.summary)
    print(f"Session {rec['session_id'][:8]} closed.")


def ledger_history(args):
    messages = read_messages(date=args.date, channel=args.channel)
    if not messages:
        print("No messages found.")
        return
    for m in messages:
        ts = m.timestamp[:19]
        ch = f" [{m.channel}]" if m.channel else ""
        name = f" ({m.sender_name})" if m.sender_name else ""
        print(f"[{ts}]{ch} {m.role}{name}: {m.content}")


def ledger_sessions(args):
    sessions = list_sessions(date=args.date)
    if not sessions:
        print("No sessions found.")
        return
    for s in sessions:
        line = f"  {s['session_id'][:8]}  {s.get('started_at', '?')[:19]}"
        if s.get("channel"):
            line += f"  [{s['channel']}]"
        if s.get("user_name"):
            line += f"  {s['user_name']}"
        if s.get("total_turns"):
            line += f"  ({s['total_turns']} turns)"
        if s.get("summary"):
            line += f"  — {s['summary']}"
        print(line)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="sf",
        description="skill-foundry unified CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # -- threads --
    tp = sub.add_parser("threads", help="Topic tracker commands")
    tp_sub = tp.add_subparsers(dest="action")

    tp_sub.add_parser("list", help="List active threads").set_defaults(func=threads_list)
    tp_sub.add_parser("all", help="List all threads").set_defaults(func=threads_all)

    p = tp_sub.add_parser("show", help="Show topic details")
    p.add_argument("topic_id")
    p.set_defaults(func=threads_show)

    p = tp_sub.add_parser("add", help="Create a new topic")
    p.add_argument("title")
    p.add_argument("original_request")
    p.set_defaults(func=threads_add)

    p = tp_sub.add_parser("status", help="Update topic status")
    p.add_argument("topic_id")
    p.add_argument("status", choices=VALID_STATUSES)
    p.set_defaults(func=threads_status)

    p = tp_sub.add_parser("progress", help="Log progress on a topic")
    p.add_argument("topic_id")
    p.add_argument("what_was_done")
    p.set_defaults(func=threads_progress)

    p = tp_sub.add_parser("pending", help="Add pending action")
    p.add_argument("topic_id")
    p.add_argument("next_action")
    p.set_defaults(func=threads_pending)

    p = tp_sub.add_parser("resolve", help="Resolve a pending action")
    p.add_argument("topic_id")
    p.add_argument("action")
    p.set_defaults(func=threads_resolve)

    p = tp_sub.add_parser("current", help="Set current action")
    p.add_argument("topic_id")
    p.add_argument("current_action")
    p.set_defaults(func=threads_current)

    p = tp_sub.add_parser("tool", help="Log a tool call")
    p.add_argument("topic_id")
    p.add_argument("tool_name")
    p.add_argument("result_summary")
    p.set_defaults(func=threads_tool)

    p = tp_sub.add_parser("close", help="Close a topic")
    p.add_argument("topic_id")
    p.add_argument("summary")
    p.set_defaults(func=threads_close)

    tp_sub.add_parser("snapshot", help="Compact snapshot of active threads").set_defaults(func=threads_snapshot)

    # -- ledger --
    lg = sub.add_parser("ledger", help="User ledger commands")
    lg_sub = lg.add_subparsers(dest="action")

    p = lg_sub.add_parser("session-start", help="Start a new session")
    p.add_argument("--channel", default=None)
    p.add_argument("--user-id", dest="user_id", default=None)
    p.add_argument("--user-name", dest="user_name", default=None)
    p.set_defaults(func=ledger_session_start)

    p = lg_sub.add_parser("log", help="Log a message")
    p.add_argument("session_id")
    p.add_argument("role")
    p.add_argument("content")
    p.set_defaults(func=ledger_log)

    p = lg_sub.add_parser("session-end", help="End a session")
    p.add_argument("session_id")
    p.add_argument("summary", nargs="?", default=None)
    p.set_defaults(func=ledger_session_end)

    p = lg_sub.add_parser("history", help="Show message history")
    p.add_argument("--date", default=None, help="YYYY-MM-DD")
    p.add_argument("--channel", default=None)
    p.set_defaults(func=ledger_history)

    p = lg_sub.add_parser("sessions", help="List sessions")
    p.add_argument("--date", default=None, help="YYYY-MM-DD or YYYY-MM")
    p.set_defaults(func=ledger_sessions)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not hasattr(args, "func"):
        # Subcommand group entered but no action given
        parser.parse_args([args.command, "-h"])
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
