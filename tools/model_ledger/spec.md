# ModelLedger — Message Format Specification

> This spec defines how every message exchanged between OpenClaw and an LLM is recorded in Markdown format.
> Markdown is the primary storage format (human-readable). JSONL is a derived format for machine consumption.

---

## File Location

```
~/.blue_lantern/model_ledger/
└── YYYY-MM-DD/
    └── {session_uuid}.md
```

One file per session. Files are **immutable** — append-only. Never overwrite.

---

## File Structure

```
# ModelLedger Session

[Session Metadata Table]

---

## Turn N — {timestamp}

[System Message]        ← optional, usually only in Turn 1
[User Message]          ← one or more
[Assistant Message]     ← with optional tool calls interleaved
[Tool Call]             ← if assistant called a tool
[Tool Response]         ← result of tool call
[Assistant Continued]   ← assistant continues after tool response

---

## Session End

[End Metadata Table]
```

---

## Section Definitions

### 1. Session Header

Written once at session start.

```markdown
# ModelLedger Session

| Field    | Value                                |
|----------|--------------------------------------|
| ID       | 3f2a1b4c-8d9e-4f0a-b1c2-d3e4f5a6b7c8 |
| Started  | 2026-03-07T23:10:00-08:00            |
| Model    | claude-sonnet-4-6                    |
| Provider | anthropic                            |
| Channel  | bluebubbles                          |
| Host     | Blue Lantern (Mac mini)              |
```

---

### 2. Turn Header

Each LLM call = one Turn. Turn number increments per session.

```markdown
## Turn 1 — 2026-03-07T23:10:05-08:00
```

---

### 3. System Message

```markdown
### 🔧 System

> You are Claude Code, Anthropic's official CLI for Claude.
> You are a personal assistant running inside OpenClaw.
```

Use blockquote (`>`) for message body. If content is very long, use a collapsed block:

```markdown
### 🔧 System

<details>
<summary>System prompt (1,234 tokens)</summary>

> You are Claude Code...
> [full content]

</details>
```

---

### 4. User Message

```markdown
### 👤 User

帮我建一个 GitHub 仓库
```

---

### 5. Assistant Message

```markdown
### 🤖 Assistant

好的，我来帮你建。首先初始化本地仓库...
```

---

### 6. Tool Call

```markdown
### 🛠️ Tool Call: `exec`

**Input:**
```json
{
  "command": "git init ~/skill-foundry && cd ~/skill-foundry"
}
```
```

Multiple tool calls in one turn are numbered:

```markdown
### 🛠️ Tool Call 1: `exec`
### 🛠️ Tool Call 2: `Read`
```

---

### 7. Tool Response

Immediately follows its Tool Call section.

```markdown
### ↩️ Tool Response: `exec`

```
Initialized empty Git repository in /Users/zhenchen/skill-foundry/.git/
```
```

For errors:

```markdown
### ❌ Tool Error: `exec`

```
bash: git: command not found
```
```

---

### 8. Assistant Continued

When the assistant continues after receiving tool responses:

```markdown
### 🤖 Assistant (continued)

仓库已初始化。现在创建远程仓库...
```

---

### 9. Session End

Written once when session closes.

```markdown
---

## Session End

| Field              | Value                     |
|--------------------|---------------------------|
| Ended              | 2026-03-07T23:15:00-08:00 |
| Total Turns        | 5                         |
| Input Tokens       | 2,340                     |
| Output Tokens      | 876                       |
| Estimated Cost     | $0.0042                   |
| Summary            | Built skill-foundry repo  |
```

---

## Complete Example

```markdown
# ModelLedger Session

| Field    | Value                                |
|----------|--------------------------------------|
| ID       | 3f2a1b4c-8d9e-4f0a-b1c2-d3e4f5a6b7c8 |
| Started  | 2026-03-07T23:10:00-08:00            |
| Model    | claude-sonnet-4-6                    |
| Provider | anthropic                            |
| Channel  | bluebubbles                          |
| Host     | Blue Lantern (Mac mini)              |

---

## Turn 1 — 2026-03-07T23:10:05-08:00

### 🔧 System

> You are Claude Code...

### 👤 User

帮我建一个 GitHub 仓库，名字叫 skill-foundry

### 🤖 Assistant

好的，我来帮你建。首先初始化本地仓库。

### 🛠️ Tool Call: `exec`

**Input:**
```json
{"command": "mkdir -p ~/skill-foundry && cd ~/skill-foundry && git init"}
```

### ↩️ Tool Response: `exec`

```
Initialized empty Git repository in /Users/zhenchen/skill-foundry/.git/
```

### 🤖 Assistant (continued)

本地仓库已建好，现在在 GitHub 上创建远程仓库...

---

## Turn 2 — 2026-03-07T23:11:00-08:00

### 👤 User

好的，继续

### 🤖 Assistant

正在推送到 GitHub...

### 🛠️ Tool Call: `exec`

**Input:**
```json
{"command": "gh repo create skill-foundry --private --source=. --push"}
```

### ↩️ Tool Response: `exec`

```
✓ Created repository dtadpole/skill-foundry on GitHub
✓ Pushed commits to git@github.com:dtadpole/skill-foundry.git
```

### 🤖 Assistant (continued)

完成！仓库地址：https://github.com/dtadpole/skill-foundry

---

## Session End

| Field          | Value                     |
|----------------|---------------------------|
| Ended          | 2026-03-07T23:12:00-08:00 |
| Total Turns    | 2                         |
| Input Tokens   | 450                       |
| Output Tokens  | 210                       |
| Summary        | Created skill-foundry repo |
```

---

## JSONL Conversion Spec

Each Markdown section maps to a JSONL record. A converter tool reads the MD and outputs one JSON object per line.

### Mapping Table

| Markdown Section | JSONL `type` field |
|------------------|-------------------|
| Session Header   | `session_start`   |
| Turn Header      | `turn_start`      |
| 🔧 System        | `message` with `role: "system"` |
| 👤 User          | `message` with `role: "user"` |
| 🤖 Assistant     | `message` with `role: "assistant"` |
| 🛠️ Tool Call     | `tool_call` |
| ↩️ Tool Response | `tool_response` |
| ❌ Tool Error    | `tool_error` |
| Session End      | `session_end` |

### JSONL Record Examples

```jsonl
{"type":"session_start","session_id":"3f2a1b4c...","started_at":"2026-03-07T23:10:00-08:00","model":"claude-sonnet-4-6","provider":"anthropic","channel":"bluebubbles"}
{"type":"turn_start","turn_number":1,"timestamp":"2026-03-07T23:10:05-08:00"}
{"type":"message","role":"system","content":"You are Claude Code..."}
{"type":"message","role":"user","content":"帮我建一个 GitHub 仓库"}
{"type":"message","role":"assistant","content":"好的，我来帮你建。"}
{"type":"tool_call","turn_number":1,"call_index":1,"tool":"exec","input":{"command":"git init..."}}
{"type":"tool_response","turn_number":1,"call_index":1,"tool":"exec","output":"Initialized empty Git repository..."}
{"type":"message","role":"assistant","content":"仓库已初始化。"}
{"type":"session_end","session_id":"3f2a1b4c...","ended_at":"2026-03-07T23:15:00-08:00","total_turns":2,"input_tokens":450,"output_tokens":210}
```

---

## Conversion Tool

A future utility `md_to_jsonl.py` will parse a ModelLedger MD file and output JSONL:

```bash
python3 md_to_jsonl.py ~/.blue_lantern/model_ledger/2026-03-07/3f2a1b4c.md > output.jsonl
```
