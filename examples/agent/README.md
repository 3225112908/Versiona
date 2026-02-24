# AI Agent Context Management

This example demonstrates how to use Versiona for AI Agent context management:

- **SubAgent Execution Flow**: Create, execute, finalize, merge
- **Local vs Output Data**: Intermediate process vs final output
- **Tool Call Management**: Using soft_delete and hard_delete
- **Conversation Branching (Fork Session)**: Branch from any turn
- **System Snapshot**: One-click save/restore state

## Files

| File | Description |
|------|-------------|
| `basic_agent.py` | Basic Agent execution flow |
| `tool_management.py` | Tool calls and data cleanup |
| `conversation_fork.py` | Conversation branching and parallel exploration |
| `snapshot_restore.py` | System snapshots and restore |

## Quick Start

```bash
# Install dependencies
pip install versiona asyncpg

# Set environment variable
export DATABASE_URL=postgresql://localhost:5432/versiona

# Run examples
python basic_agent.py
```

## Core Concepts

### Local vs Output

```python
# Local data: Intermediate process, not inherited, soft deleted after finalize
await ctx.set_local("thinking", ["Analyzing problem...", "Designing solution..."])
await ctx.set_local("tool_calls", [{"name": "search", "query": "..."}])

# Output data: Final output, inheritable, permanently retained
await ctx.set_output("summary", "Task completion summary")
await ctx.set_output("result", {"files": ["main.py"]})
```

### Soft Delete vs Hard Delete

```python
# Soft Delete: Marked as deleted, recoverable, traceable after commit
await client.soft_delete(ctx_id, "intermediate_result")

# Hard Delete: Permanently deleted, unrecoverable
await client.hard_delete(ctx_id, "sensitive_data")
```

### TTL Auto-Expiration

```python
# Time TTL: Auto-expires after N seconds
await client.set(ctx_id, "weather", data, ttl_seconds=1800)  # 30 minutes

# Turn TTL: Auto-expires after N turns
await client.set(ctx_id, "thinking", data, ttl_turns=3, current_turn=1)

# Clean expired data at start of each turn
await client.expire_by_turn(ctx_id, current_turn)
```

## Data Structure

```
Project (L0)
├── Task A (L1)
│   ├── SubAgent 1 (L2) - execution_context
│   │   ├── local: thinking, tool_calls
│   │   └── output: summary, files
│   └── SubAgent 2 (L2)
│       ├── local: reasoning
│       └── output: test_results
└── Task B (L1)
    └── ...
```
