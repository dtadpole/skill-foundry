# CostMeter

Track token usage and API costs across all ModelLedger sessions.

## Storage

```
~/.blue_lantern/cost_meter/
├── records.jsonl      ← append-only, one record per session
└── budget.json        ← optional monthly budget config
```

## Python API

```python
from tools.cost_meter import CostMeter, CostRecord, CostSummary

meter = CostMeter()

# Record a session manually
rec = meter.record(
    session_id="abc-123",
    model="claude-sonnet-4-6",
    input_tokens=1500,
    output_tokens=800,
    provider="anthropic",
    channel="bluebubbles",
    session_summary="Answered user question about Python",
)

# Sync from existing ModelLedger MD files
new_count = meter.sync_from_ledger()
print(f"Imported {new_count} new sessions")

# View summaries
today = meter.daily()              # today's costs
march = meter.monthly("2026-03")   # March 2026
everything = meter.total()         # all-time

print(meter.format_summary(today))
```

## Budget Alerts

```python
meter = CostMeter(budget_usd=50.00)
status = meter.check_budget()
# {"budget": 50.0, "spent": 12.34, "remaining": 37.66, "over_budget": False}
```

## CLI (via sf.py)

```bash
python3 sf.py cost today           # today's cost summary
python3 sf.py cost month           # this month's summary
python3 sf.py cost total           # all-time summary
python3 sf.py cost sync            # import from ModelLedger files
python3 sf.py cost budget          # show budget status
python3 sf.py cost budget --set 50 # set monthly budget to $50
```
