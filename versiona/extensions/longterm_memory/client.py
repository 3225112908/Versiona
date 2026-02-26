"""
Versiona Longterm Memory Extension - Client

Provides high-level API for memory operations.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from uuid import UUID

from .types import Memory, MemoryType

if TYPE_CHECKING:
    from asyncpg import Pool, Connection


class LongtermMemoryClient:
    """
    Longterm Memory Client

    Provides high-level API for storing and recalling memories.

    Usage:
        client = LongtermMemoryClient(db_pool)

        # Store a preference
        memory_id = await client.store(
            memory_type=MemoryType.PREFERENCE,
            key="electrical_line_color",
            content={"color": "red", "reason": "user explicitly requested"},
            project_id=project_id,
            user_id=user_id,
        )

        # Recall memories
        memories = await client.recall(
            project_id=project_id,
            user_id=user_id,
            limit=50,
        )
    """

    def __init__(self, pool: "Pool"):
        """
        Initialize client with database pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    async def store(
        self,
        memory_type: MemoryType | str,
        key: str,
        content: dict[str, Any],
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        source_session_id: str | None = None,
        source_description: str | None = None,
        importance: float = 1.0,
    ) -> UUID:
        """
        Store or update a memory.

        Args:
            memory_type: Type of memory (preference, fact, pattern, correction)
            key: Unique key within scope
            content: Memory content as dict
            project_id: Project scope (None = cross-project)
            user_id: User scope (None = cross-user)
            source_session_id: Session where this was learned
            source_description: Brief description of source
            importance: Importance weight (default 1.0)

        Returns:
            Memory ID
        """
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)

        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None

        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT upsert_memory($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                project_id,
                user_id,
                memory_type.value,
                key,
                json.dumps(content),
                source_session_id,
                source_description,
                importance,
            )
            return result

    async def recall(
        self,
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        memory_type: MemoryType | str | None = None,
        limit: int = 50,
        update_access: bool = True,
    ) -> list[Memory]:
        """
        Recall relevant memories.

        Memories are returned sorted by relevance:
        1. Project + User specific (highest)
        2. User specific (cross-project)
        3. Project specific (cross-user)
        4. Global (lowest)

        Args:
            project_id: Filter by project
            user_id: Filter by user
            memory_type: Filter by type
            limit: Maximum number of memories
            update_access: Whether to update access counts

        Returns:
            List of Memory objects
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM recall_memories($1, $2, $3, $4)
                """,
                project_id,
                user_id,
                memory_type.value if memory_type else None,
                limit,
            )

            memories = []
            for row in rows:
                # Convert row to dict
                memory_data = {
                    "id": row["id"],
                    "project_id": project_id,  # From query params
                    "user_id": user_id,
                    "memory_type": row["memory_type"],
                    "key": row["key"],
                    "content": row["content"],
                    "importance": row["importance"],
                    "access_count": row["access_count"],
                    "source_session_id": None,
                    "source_description": None,
                    "last_accessed_at": None,
                    "created_at": None,
                    "updated_at": None,
                }

                # Get full memory data if needed
                full_row = await conn.fetchrow(
                    "SELECT * FROM longterm_memory WHERE id = $1",
                    row["id"]
                )
                if full_row:
                    memory = Memory.from_row(dict(full_row))
                    memories.append(memory)

                    # Update access count
                    if update_access:
                        await conn.execute(
                            "SELECT increment_memory_access($1)",
                            row["id"]
                        )

            return memories

    async def get(
        self,
        memory_id: UUID | str,
        update_access: bool = True,
    ) -> Memory | None:
        """
        Get a specific memory by ID.

        Args:
            memory_id: Memory ID
            update_access: Whether to update access count

        Returns:
            Memory object or None
        """
        if isinstance(memory_id, str):
            memory_id = UUID(memory_id)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM longterm_memory WHERE id = $1",
                memory_id
            )

            if not row:
                return None

            if update_access:
                await conn.execute(
                    "SELECT increment_memory_access($1)",
                    memory_id
                )

            return Memory.from_row(dict(row))

    async def get_by_key(
        self,
        key: str,
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        memory_type: MemoryType | str | None = None,
    ) -> Memory | None:
        """
        Get memory by key within scope.

        Args:
            key: Memory key
            project_id: Project scope
            user_id: User scope
            memory_type: Memory type

        Returns:
            Memory object or None
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM longterm_memory
                WHERE key = $1
                  AND COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::UUID) =
                      COALESCE($2, '00000000-0000-0000-0000-000000000000'::UUID)
                  AND COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::UUID) =
                      COALESCE($3, '00000000-0000-0000-0000-000000000000'::UUID)
                  AND ($4 IS NULL OR memory_type = $4)
                """,
                key,
                project_id,
                user_id,
                memory_type.value if memory_type else None,
            )

            if not row:
                return None

            return Memory.from_row(dict(row))

    async def delete(
        self,
        memory_id: UUID | str,
    ) -> bool:
        """
        Delete a memory.

        Args:
            memory_id: Memory ID

        Returns:
            True if deleted
        """
        if isinstance(memory_id, str):
            memory_id = UUID(memory_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM longterm_memory WHERE id = $1",
                memory_id
            )
            return result == "DELETE 1"

    async def delete_by_key(
        self,
        key: str,
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
    ) -> bool:
        """
        Delete memory by key within scope.

        Args:
            key: Memory key
            project_id: Project scope
            user_id: User scope

        Returns:
            True if deleted
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM longterm_memory
                WHERE key = $1
                  AND COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::UUID) =
                      COALESCE($2, '00000000-0000-0000-0000-000000000000'::UUID)
                  AND COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::UUID) =
                      COALESCE($3, '00000000-0000-0000-0000-000000000000'::UUID)
                """,
                key,
                project_id,
                user_id,
            )
            return "DELETE" in result

    async def update_importance(
        self,
        memory_id: UUID | str,
        importance: float,
    ) -> bool:
        """
        Update memory importance.

        Args:
            memory_id: Memory ID
            importance: New importance value

        Returns:
            True if updated
        """
        if isinstance(memory_id, str):
            memory_id = UUID(memory_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE longterm_memory
                SET importance = $2, updated_at = now()
                WHERE id = $1
                """,
                memory_id,
                importance,
            )
            return result == "UPDATE 1"

    async def list_by_type(
        self,
        memory_type: MemoryType | str,
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        """
        List memories by type.

        Args:
            memory_type: Memory type to filter
            project_id: Project scope
            user_id: User scope
            limit: Maximum number

        Returns:
            List of Memory objects
        """
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)
        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM longterm_memory
                WHERE memory_type = $1
                  AND ($2 IS NULL OR project_id IS NULL OR project_id = $2)
                  AND ($3 IS NULL OR user_id IS NULL OR user_id = $3)
                ORDER BY importance DESC, created_at DESC
                LIMIT $4
                """,
                memory_type.value,
                project_id,
                user_id,
                limit,
            )

            return [Memory.from_row(dict(row)) for row in rows]

    async def search(
        self,
        query: str,
        project_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """
        Search memories by content.

        Args:
            query: Search query
            project_id: Project scope
            user_id: User scope
            limit: Maximum number

        Returns:
            List of Memory objects
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id) if project_id else None
        if isinstance(user_id, str):
            user_id = UUID(user_id) if user_id else None

        async with self._pool.acquire() as conn:
            # Simple JSONB containment search
            rows = await conn.fetch(
                """
                SELECT * FROM longterm_memory
                WHERE content::text ILIKE $1
                  AND ($2 IS NULL OR project_id IS NULL OR project_id = $2)
                  AND ($3 IS NULL OR user_id IS NULL OR user_id = $3)
                ORDER BY importance DESC, created_at DESC
                LIMIT $4
                """,
                f"%{query}%",
                project_id,
                user_id,
                limit,
            )

            return [Memory.from_row(dict(row)) for row in rows]
