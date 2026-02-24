# Versiona Examples

This directory contains usage examples for Versiona in different scenarios.

## Directory Structure

```
examples/
├── agent/                  # AI Agent Context Management
│   ├── README.md
│   ├── basic_agent.py      # Basic Agent execution flow
│   ├── tool_management.py  # Tool calls and data cleanup
│   ├── conversation_fork.py # Conversation branching
│   └── snapshot_restore.py # System snapshots
│
├── enterprise/             # Enterprise Data Version Control
│   ├── README.md
│   └── order_tracking.py   # Order tracking and audit
│
├── document/               # Document Version Control
│   ├── README.md
│   └── document_editing.py # Document editing and versions
│
├── cad/                    # CAD Drawing Version Control
│   ├── README.md
│   └── dxf_management.py   # DXF management
│
└── game/                   # Game Save System
    ├── README.md
    └── game_save.py        # Game saves
```

## Quick Start

### 1. Install Dependencies

```bash
pip install versiona asyncpg
```

### 2. Set Up Database

```bash
# Using Docker (Recommended)
docker run -d \
  --name versiona-postgres \
  -e POSTGRES_USER=versiona \
  -e POSTGRES_PASSWORD=versiona_dev \
  -e POSTGRES_DB=versiona \
  -p 5432:5432 \
  postgres:16-alpine

# Set environment variable
export DATABASE_URL=postgresql://versiona:versiona_dev@localhost:5432/versiona
```

### 3. Run Examples

```bash
# AI Agent
cd examples/agent
python basic_agent.py

# Enterprise Orders
cd examples/enterprise
python order_tracking.py

# Document Editing
cd examples/document
python document_editing.py

# CAD Management
cd examples/cad
python dxf_management.py

# Game Saves
cd examples/game
python game_save.py
```

## Core Features Quick Reference

### Context Operations

```python
# Create
await client.create_context(id, level=ContextLevel.PROJECT)

# Fork child node
await client.fork(parent_id, child_id, level=ContextLevel.TASK)

# Get node
node = await client.get_node(id)
```

### Data Operations

```python
# Set data (supports TTL)
await client.set(id, key, value, ttl_seconds=3600)
await client.set(id, key, value, ttl_turns=5, current_turn=1)

# Local vs Output
await client.set_local(id, key, value)   # Intermediate, not inherited
await client.set_output(id, key, value)  # Final output, inheritable

# Get data
value = await client.get_value(id, key)
data = await client.get(id)

# Delete
await client.soft_delete(id, key)  # Traceable
await client.hard_delete(id, key)  # Permanent
```

### Version Operations

```python
# Commit
version = await client.commit(id, message="Update")

# Checkout
await client.checkout(id, version)

# Diff
diff = await client.diff(id, v1, v2)

# History
history = await client.get_history(id)
```

### Branches and Tags

```python
# Branches
await client.create_branch(id, "feature")
await client.switch_branch(id, "feature")
branches = await client.list_branches(id)

# Tags
await client.create_tag(id, "v1.0.0")
tags = await client.list_tags(id)
await client.checkout_tag(id, "v1.0.0")
```

### Snapshots

```python
# Create
snapshot_id = await client.create_snapshot(root_id, name="checkpoint")

# Restore
await client.restore_snapshot(snapshot_id)

# List
snapshots = await client.list_snapshots(root_id)
```

### Agent-Specific

```python
# Fork Session (conversation branching)
await client.fork_session(session_id, new_id, fork_at_turn=3)

# ExecutionContext (auto finalize + merge)
async with client.execution_context(id, parent_id=parent) as ctx:
    await ctx.set_local("thinking", [...])
    await ctx.set_output("result", {...})
```

## More Information

- [Versiona README](../README.md)
- [API Reference](../README.md#api-reference)
