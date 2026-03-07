# UserLedger

Conversation logging between the user and OpenClaw (AI agent). Every message exchanged gets logged with full context — who said what, when, on which channel.

## Quick Start

```python
from tools.user_ledger import UserLedger

# Start a session
ledger = UserLedger(channel="telegram", user_name="Zhen")

# Log messages as they happen
ledger.log_message("user", "Hey, can you help me debug this?", sender_name="Zhen")
ledger.log_message("assistant", "Sure! What's the error you're seeing?")
ledger.log_message("user", "Getting a KeyError on line 42", sender_name="Zhen")
ledger.log_message("assistant", "That's because the dict is missing the 'name' key...")

# Close session when done
conversation = ledger.close(summary="Helped debug a KeyError in user's script")
```

## Log Locations

- **Live messages**: `~/.skillfoundry/user_ledger/YYYY-MM/YYYY-MM-DD.jsonl`
- **Session summaries**: `~/.skillfoundry/user_ledger/YYYY-MM/sessions/{session_id}.json`

## Reading Logs

```python
from tools.user_ledger.reader import read_messages, read_session, list_sessions, search, summarize

# Read today's messages
messages = read_messages()

# Filter by channel
messages = read_messages(date="2026-03-07", channel="telegram")

# Load a full session
session = read_session("some-session-uuid")

# List all sessions
sessions = list_sessions(channel="discord")

# Search across all logs
results = search("KeyError", date_from="2026-03-01", date_to="2026-03-07")

# Get summary stats
stats = summarize(messages)
# => {"total_messages": 42, "by_role": {"user": 21, "assistant": 21}, "by_channel": {"telegram": 42}, "avg_length": 85.3}
```

## Message Format (JSONL)

Each line in the daily log is a `MessageRecord`:

```json
{"message_id":"...","role":"user","content":"Hello!","timestamp":"2026-03-07T10:00:00+00:00","channel":"telegram","sender_id":"123","sender_name":"Zhen","attachments":[],"metadata":{}}
```

## Session Summary Format (JSON)

```json
{
  "session_id": "...",
  "started_at": "2026-03-07T10:00:00+00:00",
  "ended_at": "2026-03-07T10:15:00+00:00",
  "channel": "telegram",
  "user_name": "Zhen",
  "messages": [...],
  "total_turns": 5,
  "tags": [],
  "summary": "Helped debug a KeyError"
}
```

## Thread Safety

All write operations are protected by `threading.Lock`. Safe for concurrent use across threads.
