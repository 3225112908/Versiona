"""
Versiona Compression Extension - Client

Provides high-level API for compression queue operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .types import CompressionQueueItem, CompressionStatus

if TYPE_CHECKING:
    from asyncpg import Pool


class CompressionQueueClient:
    """
    Compression Queue Client

    Provides API for managing the compression queue.

    Usage:
        client = CompressionQueueClient(db_pool)

        # Get pending items
        pending = await client.get_pending(limit=10)

        for item in pending:
            # Mark as processing
            success = await client.mark_processing(item.id)
            if not success:
                continue  # Another worker got it

            try:
                # Do compression (your logic)
                compressed = await compress_context(item.node_id)

                # Mark complete
                await client.complete(item.id)
            except Exception as e:
                await client.fail(item.id, str(e))
    """

    def __init__(self, pool: "Pool"):
        """
        Initialize client with database pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    async def get_pending(
        self,
        limit: int = 10,
    ) -> list[CompressionQueueItem]:
        """
        Get pending compression items.

        Items are returned sorted by priority (desc) and creation time (asc).

        Args:
            limit: Maximum number of items

        Returns:
            List of pending items
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM compression_queue
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT $1
                """,
                limit,
            )

            return [CompressionQueueItem.from_row(dict(row)) for row in rows]

    async def get_by_node(
        self,
        node_id: str,
    ) -> CompressionQueueItem | None:
        """
        Get compression item for a specific node.

        Args:
            node_id: Node ID

        Returns:
            Queue item or None
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM compression_queue WHERE node_id = $1",
                node_id,
            )

            if not row:
                return None

            return CompressionQueueItem.from_row(dict(row))

    async def mark_processing(
        self,
        item_id: UUID | str,
    ) -> bool:
        """
        Mark item as processing (atomic).

        Returns False if item was already taken by another worker.

        Args:
            item_id: Queue item ID

        Returns:
            True if successfully marked, False if already taken
        """
        if isinstance(item_id, str):
            item_id = UUID(item_id)

        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT mark_compression_processing($1)",
                item_id,
            )
            return result

    async def complete(
        self,
        item_id: UUID | str,
    ) -> None:
        """
        Mark item as completed.

        Args:
            item_id: Queue item ID
        """
        if isinstance(item_id, str):
            item_id = UUID(item_id)

        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT mark_compression_completed($1)",
                item_id,
            )

    async def fail(
        self,
        item_id: UUID | str,
        error_message: str,
    ) -> None:
        """
        Mark item as failed.

        Args:
            item_id: Queue item ID
            error_message: Error description
        """
        if isinstance(item_id, str):
            item_id = UUID(item_id)

        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT mark_compression_failed($1, $2)",
                item_id,
                error_message,
            )

    async def reset_stale(
        self,
        stale_minutes: int = 30,
    ) -> int:
        """
        Reset stale processing items back to pending.

        Useful for crash recovery.

        Args:
            stale_minutes: Minutes after which processing is considered stale

        Returns:
            Number of items reset
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT reset_stale_compressions($1)",
                stale_minutes,
            )
            return result or 0

    async def cleanup(
        self,
        days: int = 7,
    ) -> int:
        """
        Clean up old completed/failed items.

        Args:
            days: Delete items older than this many days

        Returns:
            Number of items deleted
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT cleanup_compression_queue($1)",
                days,
            )
            return result or 0

    async def get_stats(self) -> dict:
        """
        Get queue statistics.

        Returns:
            Dict with counts by status
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM compression_queue
                GROUP BY status
                """
            )

            stats = {
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
            }

            for row in rows:
                stats[row["status"]] = row["count"]

            return stats

    async def force_enqueue(
        self,
        node_id: str,
        priority: int = 10,
    ) -> UUID:
        """
        Force enqueue a node for compression.

        Useful for manual compression requests.

        Args:
            node_id: Node ID to compress
            priority: Priority level

        Returns:
            Queue item ID
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                """
                INSERT INTO compression_queue (node_id, total_size, priority, status)
                VALUES ($1, 0, $2, 'pending')
                ON CONFLICT (node_id)
                DO UPDATE SET
                    priority = GREATEST(compression_queue.priority, $2),
                    status = 'pending',
                    created_at = now()
                RETURNING id
                """,
                node_id,
                priority,
            )
            return result
