"""
Versiona Agent State Extension - Client

Provides high-level API for state-driven agent execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from .types import AgentState, HandlerStatus

if TYPE_CHECKING:
    from asyncpg import Pool


class AgentStateClient:
    """
    Agent State Client

    Provides high-level API for state-driven agent execution tracking.

    Usage:
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

        # Get all pending sessions for a handler
        sessions = await client.get_pending_sessions("cad_system")
    """

    def __init__(self, pool: "Pool"):
        """
        Initialize client with database pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    async def get_or_create(
        self,
        session_id: str,
        initial_handler: str = "idle",
    ) -> AgentState:
        """
        Get or create agent state for a session.

        Args:
            session_id: Versiona node_id (session context)
            initial_handler: Initial handler if creating new

        Returns:
            AgentState
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM get_or_create_agent_state($1, $2)",
                session_id,
                initial_handler,
            )
            return AgentState.from_row(dict(row))

    async def get(self, session_id: str) -> AgentState | None:
        """
        Get agent state for a session.

        Args:
            session_id: Versiona node_id

        Returns:
            AgentState or None if not found
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agent_state WHERE session_id = $1",
                session_id,
            )
            if not row:
                return None
            return AgentState.from_row(dict(row))

    async def start_task(
        self,
        session_id: str,
        task: str,
        fork_id: str,
    ) -> AgentState:
        """
        Start executing a task (fork a subagent).

        This updates the state to 'executing' and records the task/fork info.

        Args:
            session_id: Versiona node_id
            task: Task name (e.g., "planning", "explore", "editor")
            fork_id: The fork's node_id

        Returns:
            Updated AgentState
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM start_agent_task($1, $2, $3)",
                session_id,
                task,
                fork_id,
            )
            return AgentState.from_row(dict(row))

    async def complete_task(
        self,
        session_id: str,
        success: bool = True,
    ) -> AgentState:
        """
        Complete the current task.

        Clears task/fork info and sets status to 'idle' or 'error'.

        Args:
            session_id: Versiona node_id
            success: Whether task completed successfully

        Returns:
            Updated AgentState
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM complete_agent_task($1, $2)",
                session_id,
                success,
            )
            return AgentState.from_row(dict(row))

    async def handover(
        self,
        session_id: str,
        target_handler: str,
        reason: str | None = None,
    ) -> AgentState:
        """
        Handover session to another system/handler.

        This is the key state-driven operation that triggers the target
        system to start processing.

        Args:
            session_id: Versiona node_id
            target_handler: Target system (e.g., "quote_system")
            reason: Reason for handover

        Returns:
            Updated AgentState
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM handover_agent($1, $2, $3)",
                session_id,
                target_handler,
                reason,
            )
            return AgentState.from_row(dict(row))

    async def set_status(
        self,
        session_id: str,
        status: HandlerStatus | str,
    ) -> AgentState:
        """
        Set handler status.

        Args:
            session_id: Versiona node_id
            status: New status

        Returns:
            Updated AgentState
        """
        if isinstance(status, str):
            status = HandlerStatus(status)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM set_agent_status($1, $2)",
                session_id,
                status.value,
            )
            return AgentState.from_row(dict(row))

    async def get_pending_sessions(
        self,
        handler: str,
    ) -> list[AgentState]:
        """
        Get all pending sessions for a handler.

        Use this to find sessions waiting to be processed after a handover.

        Args:
            handler: Handler name

        Returns:
            List of AgentState with status='pending'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM get_sessions_by_handler($1, $2)",
                handler,
                "pending",
            )
            return [AgentState.from_row(dict(row)) for row in rows]

    async def get_executing_sessions(
        self,
        handler: str,
    ) -> list[AgentState]:
        """
        Get all executing sessions for a handler.

        Args:
            handler: Handler name

        Returns:
            List of AgentState with status='executing'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM get_sessions_by_handler($1, $2)",
                handler,
                "executing",
            )
            return [AgentState.from_row(dict(row)) for row in rows]

    async def get_all_sessions(
        self,
        handler: str,
    ) -> list[AgentState]:
        """
        Get all sessions for a handler (any status).

        Args:
            handler: Handler name

        Returns:
            List of AgentState
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM get_sessions_by_handler($1, NULL)",
                handler,
            )
            return [AgentState.from_row(dict(row)) for row in rows]

    async def get_sessions_by_status(
        self,
        status: HandlerStatus | str,
    ) -> list[AgentState]:
        """
        Get all sessions with a specific status.

        Args:
            status: Handler status

        Returns:
            List of AgentState
        """
        if isinstance(status, str):
            status = HandlerStatus(status)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_state WHERE handler_status = $1 ORDER BY updated_at DESC",
                status.value,
            )
            return [AgentState.from_row(dict(row)) for row in rows]

    async def delete(self, session_id: str) -> bool:
        """
        Delete agent state for a session.

        Args:
            session_id: Versiona node_id

        Returns:
            True if deleted
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM agent_state WHERE session_id = $1",
                session_id,
            )
            return result == "DELETE 1"

    async def cleanup_old(self, hours: int = 24) -> int:
        """
        Clean up old completed/idle sessions.

        Args:
            hours: Delete sessions older than this

        Returns:
            Number of deleted sessions
        """
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT cleanup_old_agent_states($1)",
                hours,
            )
            return count

    async def update(
        self,
        session_id: str,
        handler: str | None = None,
        status: HandlerStatus | str | None = None,
        task: str | None = None,
        fork_id: str | None = None,
    ) -> AgentState | None:
        """
        Update agent state fields.

        Args:
            session_id: Versiona node_id
            handler: New handler (optional)
            status: New status (optional)
            task: New task (optional)
            fork_id: New fork_id (optional)

        Returns:
            Updated AgentState or None if not found
        """
        if isinstance(status, str):
            status = HandlerStatus(status)

        # Build update query dynamically
        updates = []
        params = [session_id]
        param_idx = 2

        if handler is not None:
            updates.append(f"current_handler = ${param_idx}")
            params.append(handler)
            param_idx += 1

        if status is not None:
            updates.append(f"handler_status = ${param_idx}")
            params.append(status.value)
            param_idx += 1

        if task is not None:
            updates.append(f"current_task = ${param_idx}")
            params.append(task)
            param_idx += 1

        if fork_id is not None:
            updates.append(f"current_fork_id = ${param_idx}")
            params.append(fork_id)
            param_idx += 1

        if not updates:
            # Nothing to update, just return current state
            return await self.get(session_id)

        query = f"""
            UPDATE agent_state
            SET {', '.join(updates)}
            WHERE session_id = $1
            RETURNING *
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            if not row:
                return None
            return AgentState.from_row(dict(row))
