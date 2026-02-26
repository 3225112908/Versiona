"""
Versiona Agent State Extension

State-driven agent execution state tracking.

This extension provides state management for multi-system agent architectures
where sessions can be handed over between different systems/handlers.

Key Concepts:
- Session: A Versiona context node representing an agent conversation
- Handler: The system currently responsible for processing the session
- State-Driven: State changes (in the DB) drive execution, not direct calls
- Fork: Within a system, subagents run in forked contexts
- Handover: Cross-system transfer via state change

Usage:
    from versiona.extensions.agent_state import (
        AgentStateClient,
        AgentState,
        HandlerStatus,
        get_agent_state_schema_sql,
    )

    # Get schema SQL
    sql = get_agent_state_schema_sql()

    # Create client
    client = AgentStateClient(db_pool)

    # Get or create state for a session
    state = await client.get_or_create("session_123", "cad_system")

    # Start a subagent task (fork)
    state = await client.start_task(
        "session_123",
        task="planning",
        fork_id="planning_fork_xyz"
    )

    # Complete task
    state = await client.complete_task("session_123", success=True)

    # Handover to another system
    state = await client.handover(
        "session_123",
        target_handler="quote_system",
        reason="需要報價"
    )

    # Get all pending sessions for a handler (state-driven polling)
    sessions = await client.get_pending_sessions("cad_system")

State Flow:
    1. Session created → state: idle, handler: initial_handler
    2. User input → state: executing, task: "planning"
    3. Planning complete → state: idle
    4. Need another system → handover → state: pending, handler: target_system
    5. Target system picks up → state: executing
    6. Done → state: completed

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    agent_state (Extension)                  │
    │                                                             │
    │  session_id: "ctx_abc123"    ←── 關聯 Versiona node        │
    │  current_handler: "cad_system"                              │
    │  handler_status: "executing"                                │
    │  current_task: "planning"                                   │
    │  current_fork_id: "planning_fork_xyz"                      │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
                                │
                                │ session_id 關聯
                                ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                    Versiona (通用)                          │
    │                                                             │
    │  context_nodes: id="ctx_abc123" (主幹)                     │
    │       └── child: id="planning_fork_xyz" (fork)             │
    │                                                             │
    │  context_kv: 執行細節、tool results、thinking...           │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
"""

from .schema import get_agent_state_schema_sql, get_agent_state_table_names
from .types import AgentState, HandlerStatus, HandoverRecord
from .client import AgentStateClient

__all__ = [
    # Schema
    "get_agent_state_schema_sql",
    "get_agent_state_table_names",
    # Types
    "AgentState",
    "HandlerStatus",
    "HandoverRecord",
    # Client
    "AgentStateClient",
]
