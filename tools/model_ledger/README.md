# LLM Audit Logging

Structured paper trail for every LLM API call — OpenAI, Anthropic, or any provider.

## Quick Start

```python
from tools.llm_audit import AuditLogger, AuditRecord

logger = AuditLogger(session_id="my-session", caller="my-script")

# Manual logging
record = AuditRecord(
    provider="openai",
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
    response="Hi there!",
    prompt_tokens=10,
    completion_tokens=5,
    total_tokens=15,
    latency_ms=230.5,
)
logger.log(record)
```

## Auto-Logging with Client Wrappers

### OpenAI

```python
from openai import OpenAI
from tools.llm_audit import AuditLogger

logger = AuditLogger(caller="my-agent")
client = logger.wrap_openai(OpenAI())

# Every call is automatically logged
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

### Anthropic

```python
import anthropic
from tools.llm_audit import AuditLogger

logger = AuditLogger(caller="my-agent")
client = logger.wrap_anthropic(anthropic.Anthropic())

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## Reading & Querying Logs

```python
from tools.llm_audit.reader import read_log, filter_records, summarize

# Read today's log
records = read_log()

# Read a specific date
records = read_log(date="2026-03-07")

# Filter
openai_errors = filter_records(records, provider="openai", status="error")

# Summarize
stats = summarize(records)
print(stats)
# {
#   "total_calls": 42,
#   "total_prompt_tokens": 15230,
#   "total_completion_tokens": 8400,
#   "total_tokens": 23630,
#   "total_cost_usd": 0.1827,
#   "avg_latency_ms": 312.5,
#   "error_rate": 0.0238,
# }
```

## Log Format

Each line in the JSONL file is a complete `AuditRecord` with fields for identity, timing, model info, the full conversation, token counts, cost estimates, and error status.

Default log location: `~/.skillfoundry/audit/llm_YYYY-MM-DD.jsonl`

## Cost Estimation

Built-in pricing table covers common models from OpenAI, Anthropic, and Google. Cost is automatically estimated when token counts are available.

```python
from tools.llm_audit.pricing import estimate_cost

cost = estimate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
```
