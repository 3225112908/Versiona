# Versiona

<div align="center">

**Version Control for State & Context**

*Dual-dimension version control engine for AI Agents, enterprise data audit, and frontend applications*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 13+](https://img.shields.io/badge/postgresql-13+-336791.svg)](https://www.postgresql.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

</div>

---

## Core Highlights

| Feature | Description |
|---------|-------------|
| **Context Tree** | Hierarchical context with automatic parent-child inheritance |
| **Agent Fork** | Branch from any conversation turn to explore parallel paths |
| **Snapshot & Restore** | One-click system state snapshot with time-travel restore |
| **Dual TTL** | Time-based + turn-based expiration for automatic cleanup |
| **Graph Extension** | Symbol indexing and relationship graphs for code understanding |

## Product Philosophy

### Why Versiona?

In software development, Git solved version control for code. But for **data**, we've always lacked an equally elegant solution:

| Scenario | Pain Point | Versiona Solution |
|----------|------------|-------------------|
| **AI Agent** | SubAgents need to share context, inherit parent outputs | Context Engine + auto-inheritance |
| **Conversation Branching** | Want to restart from turn 5 to explore different answers | Agent Fork + Snapshot |
| **Enterprise Audit** | Who changed what and when? Can we rollback? | Full version history + Diff |
| **Frontend Apps** | Undo/Redo, modification history, collaboration conflicts | Checkout + Branch + Merge |

Versiona's design philosophy: **Manage data like Git manages code**.

### Dual-Dimension Architecture

Versiona's core innovation is **dual-dimension** version control:

**Horizontal: Context Tree** — Parent-child hierarchy with automatic inheritance

**Vertical: Version History** — Git-like commits, branches, and time-travel

```
    +-------------------------------------------------------------------------+
    |                                                                         |
    |                    Horizontal: Context Tree                             |
    |                    ========================                             |
    |                                                                         |
    |                              Project (L0)                               |
    |                            +-----+-----+                                |
    |                         Task A      Task B  (L1)                        |
    |                        +--+--+      +--+--+                             |
    |                      Sub1  Sub2   Sub3  Sub4  (L2)                      |
    |                                                                         |
    |     * Parent-child inheritance: children auto-inherit parent output     |
    |     * Branch merge: SubAgent merges back to parent when complete        |
    |     * Scope isolation: different Tasks don't interfere                  |
    |                                                                         |
    +-------------------------------------------------------------------------+

    +-------------------------------------------------------------------------+
    |                                                                         |
    |                    Vertical: Version History                            |
    |                    =========================                            |
    |                                                                         |
    |     v1 ---------> v2 ---------> v3 ---------> v4 ---------> v5          |
    |     (init)      (draft)     (review)     (revise)     (final)          |
    |                    |                                                    |
    |                    +---- branch: experiment ----> v2.1 ----> v2.2       |
    |                                                                         |
    |     * Version snapshot: commit creates immutable versions               |
    |     * Diff comparison: compare any two versions                         |
    |     * Time travel: checkout/revert to any version                       |
    |     * Branch management: branch/tag like Git                            |
    |                                                                         |
    +-------------------------------------------------------------------------+
```

### Agent Context Engine

Context management engine designed specifically for AI Agents:

**Data Types:**
- **Local Data** — Temporary process data (thinking, reasoning). Not inherited by children, soft deleted on finalize.
- **Output Data** — Final results (summary, artifacts). Inherited by children, retained and merged to parent.

**TTL (Time-To-Live):**
- **Turn-based TTL** — `tool_call` and `tool_result` can set TTL by turns (e.g., `ttl_turns=3`). Auto-cleaned after N conversation turns.
- **Time-based TTL** — For time-sensitive data like API responses, weather, or stock prices (e.g., `ttl_seconds=300`). Auto-expired after duration.

**Delete Operations:**
- **Soft Delete** — Mark as deleted, excluded from queries but retained in version history. Used on finalize for local data.
- **Hard Delete** — Permanently remove, no trace in current state. Used for errors or invalid data that should never be seen.

**Why This Design:**
- **Automatic Token Reduction** — Redundant and intermediate data (thinking, tool calls, errors) are automatically cleaned up through TTL and soft/hard delete, minimizing token usage without manual intervention.
- **No LLM-based Compression** — Unlike memory compression approaches that require LLM calls, this is pure data management. No waiting, no extra processing cost, no information loss from summarization.
- **Noise Elimination** — Only clean, relevant outputs flow to the next context. Agents see exactly what they need, improving performance and reducing hallucination from irrelevant context.
- **Native Version Rollback** — Every commit creates an immutable version. Agents can checkout or revert to any previous state instantly, enabling safe experimentation and error recovery.
- **Dual-Dimension Flexibility** — Combined with horizontal (context tree) and vertical (version history) dimensions, SubAgents can fork from any context node, checkout any version, and explore parallel paths freely.

```
                                Main Context (Project)
                                ======================
                                          |
                                          | v1 (user_request, architecture)
                                          |
       SubAgent A <------ fork -----------+----------- fork ------> SubAgent B
       |                                  |                                  |
       | [inherit v1]                     |                    [inherit v1]  |
       |                                  |                                  |
       +-- set_local(thinking)            |            set_local(thinking) --+
       +-- set_local(tool_call, ttl=3)    |    set_local(tool_call, ttl=3) --+
       +-- set_local(tool_result, ttl=3)  |  set_local(tool_result, ttl=3) --+
       |                                  |                                  |
       +-- error occurred!                |              set_output("api") --+
       +-- hard_delete(failed_result)     |                                  |
       +-- retry, succeed                 |                      [finalize]  |
       +-- set_output(summary)            |                - local: soft del |
       |                                  |                - ttl: auto clean |
       | [finalize]                       |                - output: retained|
       |                                  |                                  |
       +----------- merge --------------->|<------------- merge -------------+
                                          |
                                          | v2 (+ SubAgent A output)
                                          |
                                          | v3 (+ SubAgent B output)
                                          |
                                          +----------- fork ------> Next SubAgent
                                          |                         |
                                          |           [inherit v3: clean outputs]
                                          |           (no thinking, no errors,
                                          |            no expired data)
                                          .
```

### Agent Fork & Snapshot

Branch from any conversation turn, plus system-level snapshots:

```
                           Original Session
    +--------------------------------------------------------------+
    |                                                              |
    |  Turn 1 ---> Turn 2 ---> Turn 3 ---> Turn 4 ---> Turn 5     |
    |    |           |           |                                 |
    |    |           |           |                                 |
    |    |           |     fork_session(fork_at_turn=3)            |
    |    |           |           |                                 |
    +----|-----------|-----------|---------------------------------+
         |           |           |
         v           v           v
    +-------------------------------------------------+
    |              Forked Session                     |
    |                                                 |
    |  Turn 1 ---> Turn 2 ---> Turn 3'               |
    |  (copied)    (copied)    (new path)            |
    |                             |                   |
    |                             v                   |
    |                          Turn 4'                |
    |                          (explore)              |
    +-------------------------------------------------+


                              SNAPSHOT
    +-----------------------------------------------------------------+
    |                                                                 |
    |   Project --+-- Task A --+-- Sub1 (v3)                         |
    |      |      |     |      +-- Sub2 (v2)                         |
    |      |      |     |                        [camera] Snapshot    |
    |      |      +-- Task B --+-- Sub3 (v5)    ==================    |
    |      |            |      +-- Sub4 (v1)    Records all node      |
    |      |            |                       version combinations  |
    |      v            v                                             |
    |   Snapshot ID: snap_abc123                                      |
    |   Node Versions: {                                              |
    |     "project": 10,                                              |
    |     "task_a": 5, "task_b": 7,                                   |
    |     "sub1": 3, "sub2": 2, "sub3": 5, "sub4": 1                  |
    |   }                                                             |
    |                                                                 |
    |   restore_snapshot(snap_abc123)  -->  One-click restore         |
    |                                                                 |
    +-----------------------------------------------------------------+
```

---

## Installation

```bash
pip install versiona
```

### Dependencies

- Python 3.11+
- PostgreSQL 13+ (requires ltree extension)

### Docker (Recommended)

```bash
docker run -d \
  --name versiona-postgres \
  -e POSTGRES_USER=versiona \
  -e POSTGRES_PASSWORD=versiona_dev \
  -e POSTGRES_DB=versiona \
  -p 5432:5432 \
  postgres:16-alpine
```

### Environment Variables

Set in `.env` file:

```bash
DATABASE_URL=postgresql://versiona:versiona_dev@localhost:5432/versiona
```

---

## AI Agent Context Management

Example usage for managing agent context:

### SubAgent Execution Flow

```python
# 1. Coordinator creates Project Context
await client.create_context("project_todo", level=ContextLevel.PROJECT)
await client.set_output("project_todo", "user_request", "Develop Todo API")
await client.set_output("project_todo", "architecture", {"backend": "FastAPI"})
await client.commit("project_todo", "Project initialized")

# 2. Fork a Task
await client.fork("project_todo", "task_backend")

# 3. SubAgent execution
async with client.execution_context("sub_api", parent_id="task_backend") as ctx:
    # Inherit architecture (from parent)
    data = await ctx.get_for_llm()
    arch = data.get("architecture")  # {"backend": "FastAPI"}

    # Execution process (local, won't be inherited)
    await ctx.set_local("thinking", [f"Using {arch['backend']} for development"])
    await ctx.set_local("tool_calls", [{"name": "write_file", "path": "api/routes.py"}])

    # Set output (will merge to task_backend)
    await ctx.set_output("api_spec", {"endpoints": ["GET /todos", "POST /todos"]})
    await ctx.set_output("files", ["api/routes.py"])
    # Auto finalize + merge on exit

# 4. Merge back to project
await client.merge("task_backend", "project_todo")

# 5. Final result contains all SubAgent outputs
result = await client.get("project_todo")
```

### Agent Fork (Conversation Branching)

```python
# Original conversation
session_id = "session_001"
await client.create_context(session_id, level=ContextLevel.PROJECT)

# Conduct conversation
await client.set(session_id, "turn_1_user", "Help me write a function", current_turn=1)
await client.set(session_id, "turn_1_assistant", "Sure, what functionality?", current_turn=1)
await client.commit(session_id, "Turn 1")

await client.set(session_id, "turn_2_user", "Calculate factorial", current_turn=2)
await client.set(session_id, "turn_2_assistant", "def factorial(n)...", current_turn=2)
await client.commit(session_id, "Turn 2")

await client.set(session_id, "turn_3_user", "Make it recursive", current_turn=3)
await client.commit(session_id, "Turn 3")

# Branch from Turn 2 to explore different path
new_session = await client.fork_session(
    session_id,
    "session_002",
    fork_at_turn=2,  # Branch from Turn 2
    name="Explore iterative approach"
)

# New session contains Turn 1, 2 data but not Turn 3
turn3 = await client.get_value(new_session, "turn_3_user")  # None
```

### Snapshot (System Snapshot)

```python
# Create snapshot
snapshot_id = await client.create_snapshot(
    "project_123",
    name="before_refactor",
    message="State before refactoring"
)

# ... perform some operations ...

# Rollback to snapshot
restored_count = await client.restore_snapshot(snapshot_id)
print(f"Restored {restored_count} nodes")
```

---

## Dual-Mode TTL

Versiona supports two TTL (Time-To-Live) modes:

### Time TTL (Seconds)

Suitable for real-time information like weather, stock prices, API responses.

```python
# Weather data expires after 30 minutes
await client.set(ctx_id, "weather", weather_data, ttl_seconds=1800)

# API response expires after 5 minutes
await client.set(ctx_id, "api_response", response, ttl_seconds=300)
```

### Turn TTL (Turns)

Suitable for process data in Agent loops.

```python
async def agent_loop(client, ctx_id, max_turns=10):
    for turn in range(max_turns):
        # Clean expired data at start of each turn
        await client.expire_by_turn(ctx_id, turn)

        # thinking expires after 3 turns
        thinking = await llm.think(prompt)
        await client.set_local(ctx_id, "thinking", thinking,
            ttl_turns=3, current_turn=turn)

        # Final output has no TTL, retained permanently
        if is_final:
            await client.set_output(ctx_id, "summary", summary)
```

---

## Graph Extension (Symbol Indexing)

Versiona supports an optional Graph Extension for symbol indexing and relationship graphs:

```python
# Initialize (with graph extension)
await client.init_schema(extensions=["graph"])

# Use pool to operate on graph directly
async with client.pool.acquire() as conn:
    # Add symbol
    await conn.execute("""
        INSERT INTO vg_symbol_index
        (context_id, symbol_type, symbol_key, symbol_name, content)
        VALUES ($1, $2, $3, $4, $5)
    """, "project_123", "function", "utils.py::calculate", "calculate",
        "def calculate(x, y): return x + y")

    # Search symbols (supports fuzzy search)
    results = await conn.fetch("""
        SELECT * FROM vg_symbol_index
        WHERE context_id = $1
        AND symbol_name ILIKE $2
    """, "project_123", "%calc%")

    # Create symbol relationships
    await conn.execute("""
        INSERT INTO vg_symbol_edges (source_id, target_id, edge_type, weight)
        VALUES ($1, $2, 'references', 1.0)
    """, source_id, target_id)
```

---

## API Reference

### VersionaClient

```python
# Create
client = await VersionaClient.create(dsn)

# Context operations
await client.create_context(id, parent_id, level, name, metadata)
await client.fork(source_id, new_id, level, inherit_output)
await client.get_node(context_id)
await client.get_children(context_id, level, include_nested)
await client.delete_context(context_id, hard)

# Data operations (supports dual-mode TTL)
await client.get(context_id, version, include_inherited, exclude_soft_deleted)
await client.get_value(context_id, key, default, current_turn)
await client.set(context_id, key, value, category, ttl_seconds, ttl_turns, current_turn)
await client.set_local(context_id, key, value, ttl_seconds, ttl_turns, current_turn)
await client.set_output(context_id, key, value)
await client.soft_delete(context_id, key)
await client.hard_delete(context_id, key)
await client.expire_by_turn(context_id, current_turn)

# Version operations
await client.commit(context_id, message, author_id, soft_delete_keys)
await client.checkout(context_id, version, create_new_version)
await client.get_history(context_id, limit, offset)
await client.diff(context_id, version_a, version_b)

# Branch operations
await client.create_branch(context_id, branch_name, from_version)
await client.list_branches(context_id)
await client.switch_branch(context_id, branch_name)
await client.delete_branch(context_id, branch_name)

# Tag operations
await client.create_tag(context_id, tag_name, version, message)
await client.list_tags(context_id)
await client.checkout_tag(context_id, tag_name)

# Snapshot operations
await client.create_snapshot(root_node_id, name, snapshot_type, message)
await client.restore_snapshot(snapshot_id)
await client.list_snapshots(root_node_id)

# Fork Session (Agent-specific)
await client.fork_session(source_id, new_id, fork_at_turn, name, copy_kv)

# Merge operations
await client.merge(source_id, target_id, merge_type, message)
await client.finalize(context_id, summary, output, artifacts)

# Convenience methods
await client.get_for_llm(context_id)
await client.cleanup_expired(current_turn)
```

### ExecutionContext

```python
async with client.execution_context(id, parent_id, level, auto_finalize, auto_merge) as ctx:
    await ctx.set_local(key, value, ttl)
    await ctx.set_output(key, value)
    await ctx.get(key, default)
    await ctx.append(key, value)
    await ctx.commit(message)
    child = await ctx.fork(new_id)
    data = await ctx.get_for_llm()
```

---

## Database Schema

| Table | Description |
|-------|-------------|
| `context_nodes` | Horizontal tree structure (parent_id, path, level) |
| `context_versions` | Vertical version history (node_id, version, data) |
| `context_branches` | Branch management |
| `context_merges` | Merge history |
| `context_tags` | Tags |
| `context_kv` | KV fast query storage |
| `context_snapshots` | System snapshots |

### Graph Extension Tables

| Table | Description |
|-------|-------------|
| `vg_symbol_types` | Symbol type registry |
| `vg_edge_types` | Edge type registry |
| `vg_symbol_index` | Symbol index |
| `vg_symbol_edges` | Symbol relationships |
| `vg_context_views` | Context View cache |

---

## Examples

See the [examples/](./examples/) directory for complete usage examples:

- **[agent/](./examples/agent/)** - AI Agent context management, tool usage, conversation branching
- **[enterprise/](./examples/enterprise/)** - Enterprise data audit, order tracking
- **[document/](./examples/document/)** - Document editing, versioning, Undo/Redo
- **[cad/](./examples/cad/)** - CAD drawing version control, entity management
- **[game/](./examples/game/)** - Game saves, state snapshots, replay

---

## Roadmap

### Core Enhancement
- [ ] Connection pooling optimization (pgbouncer)
- [ ] Batch operations (`batch_set()`, `batch_commit()`)
- [ ] CLI tool (`versiona inspect`, `versiona history`)
- [ ] SynapseFlow integration (State-Centric Agent Framework Library)

### Advanced Features
- [ ] Conflict resolution strategies
- [ ] Fine-grained access control
- [ ] Auto compression & archiving

### AI-Native Features
- [ ] Context smart summary
- [ ] Similar context search
- [ ] Context prediction & prefetch

---

## Author

**Perhapxin Lab**

- Email: perhapxin@gmail.com
- GitHub: [https://github.com/perhapxinlab](https://github.com/perhapxinlab)
- Website: [https://perhapxin.com](https://perhapxin.com)
