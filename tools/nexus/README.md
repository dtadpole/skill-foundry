# nexus

**Nexus** is a task delegation and I/O bridge for running Claude Code in the background via tmux, with live two-way communication routed through your Telegram channel.

You assign a task. Nexus launches Claude Code in a named tmux session, monitors its progress, and stays out of the way — until Claude Code needs to ask you something. At that point, it relays the question to your Telegram, waits for your reply, and passes the answer back. When the task is done, you get notified.

---

## What it does

- Starts a named tmux session and launches Claude Code with your task
- Monitors the pane every N seconds for questions or completion
- Detects when Claude Code is waiting for user input and delivers the question to Telegram
- Accepts your reply and forwards it into the tmux session
- Notifies you when the session ends
- Lets you check progress at any time

---

## Usage

```bash
# Start a coding task
python3 nexus.py start "build a FastAPI CRUD service for users" --session myapi --workdir ~/myapi

# Check current progress
python3 nexus.py status --session myapi

# Send an answer when Claude Code is asking something
python3 nexus.py answer "yes, use PostgreSQL" --session myapi

# List all active sessions and pending questions
python3 nexus.py list

# Stop a session
python3 nexus.py stop --session myapi
```

---

## How it works

```
[You, Telegram]
      ↕
[Blue Lantern — main session]
      ↕  (reads question file, writes answer file)
[nexus.py — background monitor]
      ↕  (capture-pane / send-keys)
[tmux session → Claude Code]
```

1. `nexus.py start` launches a tmux session, starts Claude Code, and enters a monitor loop
2. When a question is detected in the pane output, it writes to `~/.code-agent/<session>.question` and delivers to Telegram via `openclaw agent --channel last --deliver`
3. Blue Lantern sees the question notification, relays it to you, and when you reply, writes your answer to `~/.code-agent/<session>.answer`
4. The monitor loop detects the answer file and sends it into the tmux session via `send-keys`

---

## State files

All session state is stored under `~/.code-agent/`:

| File | Purpose |
|------|---------|
| `<session>.json` | Session metadata (task, status, started time) |
| `<session>.question` | Current pending question from Claude Code |
| `<session>.answer` | Answer written by main session, picked up by monitor |

---

## Requirements

- `tmux` installed
- `claude` CLI (Claude Code) installed and authenticated
- `openclaw` CLI installed and configured
- Python 3.10+
