"""
Versiona Graph Extension - LLM Feedback Module (Optional).

This module provides functionality for LLM to submit feedback
for graph corrections. It is only loaded when enabled in GraphConfig.

Usage:

    from versiona import VersionaClient
    from versiona.extensions.graph import GraphExtension, GraphConfig

    # Enable feedback in config
    config = GraphConfig(enable_feedback=True)
    graph = GraphExtension(client, config=config)

    await graph.init_schema()

    # Submit feedback
    await graph.feedback.submit(
        context_id="project_123",
        feedback_type="missing_edge",
        content={
            "source_type": "function",
            "source_key": "main.py::process",
            "target_type": "function",
            "target_key": "utils.py::helper",
            "edge_type": "calls",
            "confidence": 0.9,
            "reason": "process() calls helper() on line 42"
        }
    )

    # Process pending feedback
    applied = await graph.feedback.process_pending()
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from versiona.extensions.graph.types import (
    Feedback,
    FeedbackType,
    FeedbackStatus,
)

if TYPE_CHECKING:
    from versiona.extensions.graph.client import GraphExtension


class FeedbackModule:
    """
    LLM Feedback Module for Graph Extension.

    Allows LLM to submit corrections and suggestions for the symbol graph.
    Feedback can be auto-applied (if confidence is high) or queued for review.
    """

    def __init__(self, graph: "GraphExtension"):
        """
        Initialize FeedbackModule.

        Args:
            graph: GraphExtension instance
        """
        self.graph = graph

    @property
    def pool(self):
        """Get the connection pool."""
        return self.graph.pool

    async def submit(
        self,
        context_id: str,
        feedback_type: FeedbackType | str,
        content: dict[str, Any],
        symbol_id: UUID | None = None,
        edge_id: UUID | None = None,
    ) -> UUID:
        """
        Submit feedback from LLM.

        Args:
            context_id: Context ID
            feedback_type: Type of feedback
            content: Feedback content (schema depends on type)
            symbol_id: Related symbol (if applicable)
            edge_id: Related edge (if applicable)

        Returns:
            Feedback UUID

        Feedback content schemas by type:

        missing_edge:
            {
                "source_type": str,
                "source_key": str,
                "target_type": str,
                "target_key": str,
                "edge_type": str,
                "confidence": float,
                "reason": str
            }

        wrong_edge:
            {
                "edge_id": str,
                "issue": str,
                "suggested_fix": str
            }

        missing_symbol:
            {
                "symbol_type": str,
                "symbol_key": str,
                "symbol_name": str,
                "reason": str
            }

        wrong_content:
            {
                "symbol_id": str,
                "field": str,
                "current_value": any,
                "suggested_value": any,
                "reason": str
            }

        suggestion:
            {
                "description": str,
                "priority": str  # "low", "medium", "high"
            }
        """
        if isinstance(feedback_type, FeedbackType):
            feedback_type = feedback_type.value

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_submit_feedback($1, $2, $3, $4, $5)",
                context_id,
                feedback_type,
                json.dumps(content),
                symbol_id,
                edge_id,
            )
            return result

    async def submit_missing_edge(
        self,
        context_id: str,
        source_type: str,
        source_key: str,
        target_type: str,
        target_key: str,
        edge_type: str,
        confidence: float = 0.8,
        reason: str | None = None,
    ) -> UUID:
        """
        Convenience method to submit missing edge feedback.

        Args:
            context_id: Context ID
            source_type: Source symbol type
            source_key: Source symbol key
            target_type: Target symbol type
            target_key: Target symbol key
            edge_type: Suggested edge type
            confidence: Confidence score (0-1)
            reason: Explanation

        Returns:
            Feedback UUID
        """
        return await self.submit(
            context_id=context_id,
            feedback_type=FeedbackType.MISSING_EDGE,
            content={
                "source_type": source_type,
                "source_key": source_key,
                "target_type": target_type,
                "target_key": target_key,
                "edge_type": edge_type,
                "confidence": confidence,
                "reason": reason,
            },
        )

    async def submit_co_modified(
        self,
        context_id: str,
        symbol_ids: list[UUID],
        reason: str | None = None,
    ) -> list[UUID]:
        """
        Report that symbols were modified together.

        This creates co_modified edges or increments existing edge weights.

        Args:
            context_id: Context ID
            symbol_ids: List of symbol UUIDs that were modified together
            reason: Explanation

        Returns:
            List of feedback UUIDs
        """
        feedback_ids = []

        # Create feedback for each pair
        for i, source_id in enumerate(symbol_ids):
            for target_id in symbol_ids[i + 1:]:
                # Check if edge exists
                async with self.pool.acquire() as conn:
                    existing = await conn.fetchval("""
                        SELECT id FROM vg_symbol_edges
                        WHERE source_id = $1 AND target_id = $2 AND edge_type = 'co_modified'
                    """, source_id, target_id)

                    if existing:
                        # Increment weight
                        await self.graph.increment_edge_weight(
                            source_id, target_id, "co_modified", 0.1
                        )
                    else:
                        # Create edge
                        await self.graph.add_edge(
                            source_id, target_id, "co_modified",
                            weight=1.0, created_by="llm"
                        )

        return feedback_ids

    async def get_pending(
        self,
        context_id: str | None = None,
        feedback_type: FeedbackType | str | None = None,
        limit: int = 100,
    ) -> list[Feedback]:
        """
        Get pending feedback.

        Args:
            context_id: Filter by context
            feedback_type: Filter by type
            limit: Maximum results

        Returns:
            List of pending feedback
        """
        async with self.pool.acquire() as conn:
            query = """
                SELECT * FROM vg_llm_feedback
                WHERE status = 'pending'
            """
            params = []

            if context_id:
                params.append(context_id)
                query += f" AND context_id = ${len(params)}"

            if feedback_type:
                if isinstance(feedback_type, FeedbackType):
                    feedback_type = feedback_type.value
                params.append(feedback_type)
                query += f" AND feedback_type = ${len(params)}"

            query += f" ORDER BY created_at LIMIT {limit}"

            rows = await conn.fetch(query, *params)

            return [self._row_to_feedback(row) for row in rows]

    async def get_pending_count(
        self,
        context_id: str | None = None,
    ) -> int:
        """Get count of pending feedback."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_get_pending_feedback_count($1)",
                context_id,
            )
            return result or 0

    async def process_pending(
        self,
        context_id: str | None = None,
        auto_apply_threshold: float = 0.8,
    ) -> int:
        """
        Process pending feedback.

        Auto-applies feedback with confidence >= threshold.

        Args:
            context_id: Filter by context
            auto_apply_threshold: Minimum confidence for auto-apply

        Returns:
            Number of feedback items processed
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_process_pending_feedback($1, $2)",
                context_id,
                auto_apply_threshold,
            )
            return result or 0

    async def apply(self, feedback_id: UUID) -> bool:
        """
        Manually apply a feedback item.

        Args:
            feedback_id: Feedback UUID

        Returns:
            True if applied successfully
        """
        async with self.pool.acquire() as conn:
            # Get feedback
            row = await conn.fetchrow(
                "SELECT * FROM vg_llm_feedback WHERE id = $1",
                feedback_id,
            )

            if not row or row["status"] != "pending":
                return False

            feedback = self._row_to_feedback(row)
            content = feedback.feedback_content

            # Apply based on type
            if feedback.feedback_type == FeedbackType.MISSING_EDGE:
                await self.graph.add_edge_by_key(
                    feedback.context_id,
                    content["source_type"],
                    content["source_key"],
                    content["target_type"],
                    content["target_key"],
                    content["edge_type"],
                    weight=1.0,
                    created_by="llm",
                )

            # Mark as applied
            await conn.execute("""
                UPDATE vg_llm_feedback
                SET status = 'applied', processed_at = now()
                WHERE id = $1
            """, feedback_id)

            return True

    async def reject(
        self,
        feedback_id: UUID,
        reason: str | None = None,
    ) -> bool:
        """
        Reject a feedback item.

        Args:
            feedback_id: Feedback UUID
            reason: Rejection reason

        Returns:
            True if rejected successfully
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE vg_llm_feedback
                SET status = 'rejected', processed_at = now()
                WHERE id = $1 AND status = 'pending'
            """, feedback_id)

            return "UPDATE 1" in result

    async def cleanup_old(
        self,
        days: int = 30,
    ) -> int:
        """
        Cleanup old processed feedback.

        Args:
            days: Delete feedback older than this many days

        Returns:
            Number of items deleted
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM vg_llm_feedback
                WHERE status IN ('applied', 'rejected', 'expired')
                  AND processed_at < now() - ($1 || ' days')::INTERVAL
            """, str(days))

            # Parse "DELETE X" to get count
            return int(result.split()[-1]) if "DELETE" in result else 0

    def _row_to_feedback(self, row: Any) -> Feedback:
        """Convert database row to Feedback."""
        return Feedback(
            id=row["id"],
            context_id=row["context_id"],
            symbol_id=row["symbol_id"],
            edge_id=row["edge_id"],
            feedback_type=FeedbackType(row["feedback_type"]),
            feedback_content=json.loads(row["feedback_content"]) if row["feedback_content"] else {},
            status=FeedbackStatus(row["status"]),
            processed_at=row["processed_at"],
            created_at=row["created_at"],
        )
