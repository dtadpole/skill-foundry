# TopicManager

Track parallel conversation topics so nothing gets lost. Each topic has a
status, progress log, pending actions, and an append-only event history.

## Quick start

```python
from tools.topics import TopicManager, TopicStatus

tm = TopicManager()  # default storage: ~/.skillfoundry/topics/

# Create a topic
topic = tm.create("ModelLedger", description="Build audit logger", tags=["coding"])

# Work on it
tm.update_status(topic.topic_id, TopicStatus.IN_PROGRESS)
tm.set_current(topic.topic_id, "writing models")
tm.add_pending(topic.topic_id, "run tests")
tm.add_pending(topic.topic_id, "write docs")
tm.add_progress(topic.topic_id, "initial build")
tm.resolve_pending(topic.topic_id, "run tests")

# See what's active
print(tm.snapshot())
```

Output:
```
[ACTIVE TOPICS — 1 in progress]
① ModelLedger [in_progress] — writing models
  ✓ Done: initial build, run tests
  ⋯ Pending: write docs
```

## API

### TopicManager

| Method | Description |
|--------|-------------|
| `create(title, description, tags)` | Create a new topic |
| `get(topic_id)` | Get topic by ID |
| `find(query)` | Search by title/description/tags |
| `list_active()` | All non-completed topics |
| `list_all()` | Every topic |
| `update_status(topic_id, status, note)` | Change status |
| `add_progress(topic_id, description)` | Record a completed step |
| `add_pending(topic_id, action)` | Add a pending action |
| `resolve_pending(topic_id, action)` | Move pending → done |
| `set_current(topic_id, action)` | Set current action text |
| `close(topic_id, summary)` | Mark COMPLETED and archive |
| `snapshot()` | Compact text overview of active topics |
| `save()` / `load()` | Persist to / read from disk |

### TopicStatus

`PENDING` · `IN_PROGRESS` · `AWAITING_USER` · `AWAITING_AGENT` ·
`AWAITING_VERIFICATION` · `PAUSED` · `BLOCKED` · `COMPLETED`

### Storage

- Active topics: `~/.skillfoundry/topics/active.json`
- Archived (completed): `~/.skillfoundry/topics/archive/{topic_id}.json`

File writes are thread-safe via `threading.Lock`.
