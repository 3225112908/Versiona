"""
Versiona Graph Extension - Client.

This module provides the main GraphExtension class for interacting with
the symbol index and relationship graph.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from versiona.extensions.graph.types import (
    Symbol,
    Edge,
    SearchResult,
    TraversalResult,
    ContextView,
    GraphConfig,
    SymbolTypeConfig,
    EdgeTypeConfig,
)
from versiona.extensions.graph.schema import (
    get_graph_schema_sql,
    get_graph_table_names,
)
from versiona.extensions.graph.functions import (
    get_graph_functions_sql,
    get_graph_function_names,
)

if TYPE_CHECKING:
    from versiona.client import VersionaClient


class GraphExtension:
    """
    Versiona Graph Extension.

    Provides symbol indexing and relationship graph functionality for
    context-aware operations.

    Usage:

        from versiona import VersionaClient
        from versiona.extensions.graph import GraphExtension

        client = await VersionaClient.create(dsn)
        graph = GraphExtension(client)

        # Initialize schema
        await graph.init_schema()

        # Add symbols
        symbol_id = await graph.add_symbol(
            context_id="project_123",
            symbol_type="function",
            symbol_key="utils/helper.py::calculate",
            symbol_name="calculate",
            content="def calculate(x, y): ..."
        )

        # Search
        results = await graph.search("project_123", "calculate")

        # Get related symbols
        related = await graph.get_related(symbol_id, depth=2)
    """

    def __init__(
        self,
        client: "VersionaClient",
        config: GraphConfig | None = None,
    ):
        """
        Initialize GraphExtension.

        Args:
            client: VersionaClient instance
            config: GraphConfig for customization
        """
        self.client = client
        self.config = config or GraphConfig()
        self._schema_initialized = False
        self._feedback_module: "FeedbackModule | None" = None

    @property
    def pool(self):
        """Get the connection pool from the client."""
        return self.client.pool

    # =========================================================================
    # Schema Management
    # =========================================================================

    async def init_schema(self) -> None:
        """
        Initialize the Graph extension schema.

        This creates all necessary tables and functions.
        """
        async with self.pool.acquire() as conn:
            # Create tables
            await conn.execute(get_graph_schema_sql(
                include_feedback=self.config.enable_feedback
            ))

            # Create functions
            await conn.execute(get_graph_functions_sql(
                include_feedback=self.config.enable_feedback
            ))

        self._schema_initialized = True

        # Initialize feedback module if enabled
        if self.config.enable_feedback:
            from versiona.extensions.graph.feedback import FeedbackModule
            self._feedback_module = FeedbackModule(self)

    async def check_schema(self) -> bool:
        """Check if the Graph extension schema exists."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'vg_symbol_index'
                )
            """)
            return bool(result)

    async def get_table_names(self) -> list[str]:
        """Get all table names for this extension."""
        return get_graph_table_names(include_feedback=self.config.enable_feedback)

    async def get_function_names(self) -> list[str]:
        """Get all function names for this extension."""
        return get_graph_function_names(include_feedback=self.config.enable_feedback)

    # =========================================================================
    # Type Registration
    # =========================================================================

    async def register_symbol_type(
        self,
        name: str,
        description: str | None = None,
        default_ttl_seconds: int | None = None,
        auto_index: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a custom symbol type.

        Args:
            name: Type name (e.g., "layer", "function")
            description: Human-readable description
            default_ttl_seconds: Default TTL for symbols of this type
            auto_index: Whether to auto-index symbols of this type
            metadata: Additional metadata
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO vg_symbol_types (name, description, default_ttl_seconds, auto_index, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    default_ttl_seconds = EXCLUDED.default_ttl_seconds,
                    auto_index = EXCLUDED.auto_index,
                    metadata = vg_symbol_types.metadata || EXCLUDED.metadata
            """, name, description, default_ttl_seconds, auto_index,
                json.dumps(metadata or {}))

    async def register_edge_type(
        self,
        name: str,
        description: str | None = None,
        is_directional: bool = True,
        auto_create: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a custom edge type.

        Args:
            name: Type name (e.g., "references", "contains")
            description: Human-readable description
            is_directional: Whether the edge has direction
            auto_create: Whether to auto-create edges of this type
            metadata: Additional metadata
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO vg_edge_types (name, description, is_directional, auto_create, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    is_directional = EXCLUDED.is_directional,
                    auto_create = EXCLUDED.auto_create,
                    metadata = vg_edge_types.metadata || EXCLUDED.metadata
            """, name, description, is_directional, auto_create,
                json.dumps(metadata or {}))

    async def list_symbol_types(self) -> list[SymbolTypeConfig]:
        """List all registered symbol types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, description, default_ttl_seconds, auto_index, metadata
                FROM vg_symbol_types ORDER BY name
            """)
            return [
                SymbolTypeConfig(
                    name=row["name"],
                    description=row["description"],
                    default_ttl_seconds=row["default_ttl_seconds"],
                    auto_index=row["auto_index"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )
                for row in rows
            ]

    async def list_edge_types(self) -> list[EdgeTypeConfig]:
        """List all registered edge types."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, description, is_directional, auto_create, metadata
                FROM vg_edge_types ORDER BY name
            """)
            return [
                EdgeTypeConfig(
                    name=row["name"],
                    description=row["description"],
                    is_directional=row["is_directional"],
                    auto_create=row["auto_create"],
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                )
                for row in rows
            ]

    # =========================================================================
    # Symbol Operations
    # =========================================================================

    async def add_symbol(
        self,
        context_id: str,
        symbol_type: str,
        symbol_key: str,
        symbol_name: str | None = None,
        content: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> UUID:
        """
        Add or update a symbol.

        Args:
            context_id: Context ID (namespace)
            symbol_type: Symbol type (e.g., "function", "layer")
            symbol_key: Unique key within context/type
            symbol_name: Display name
            content: Symbol content (for search)
            properties: Additional properties (e.g., bbox for spatial)

        Returns:
            Symbol UUID
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_upsert_symbol($1, $2, $3, $4, $5, $6)",
                context_id,
                symbol_type,
                symbol_key,
                symbol_name,
                content,
                json.dumps(properties or {}),
            )
            return result

    async def add_symbols_bulk(
        self,
        symbols: list[dict[str, Any]],
    ) -> int:
        """
        Bulk add symbols.

        Args:
            symbols: List of symbol dicts with keys:
                - context_id (required)
                - symbol_type (required)
                - symbol_key (required)
                - symbol_name (optional)
                - content (optional)
                - properties (optional)

        Returns:
            Number of symbols added/updated
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_bulk_upsert_symbols($1)",
                json.dumps(symbols),
            )
            return result or 0

    async def get_symbol(
        self,
        symbol_id: UUID | None = None,
        context_id: str | None = None,
        symbol_type: str | None = None,
        symbol_key: str | None = None,
    ) -> Symbol | None:
        """
        Get a symbol by ID or by context/type/key.

        Args:
            symbol_id: Symbol UUID (if known)
            context_id: Context ID
            symbol_type: Symbol type
            symbol_key: Symbol key

        Returns:
            Symbol or None if not found
        """
        async with self.pool.acquire() as conn:
            if symbol_id:
                row = await conn.fetchrow(
                    "SELECT * FROM vg_symbol_index WHERE id = $1",
                    symbol_id,
                )
            else:
                row = await conn.fetchrow(
                    """SELECT * FROM vg_symbol_index
                       WHERE context_id = $1 AND symbol_type = $2 AND symbol_key = $3""",
                    context_id, symbol_type, symbol_key,
                )

            if not row:
                return None

            return self._row_to_symbol(row)

    async def delete_symbol(
        self,
        symbol_id: UUID | None = None,
        context_id: str | None = None,
        symbol_type: str | None = None,
        symbol_key: str | None = None,
    ) -> bool:
        """Delete a symbol."""
        async with self.pool.acquire() as conn:
            if symbol_id:
                result = await conn.execute(
                    "DELETE FROM vg_symbol_index WHERE id = $1",
                    symbol_id,
                )
            else:
                result = await conn.execute(
                    """DELETE FROM vg_symbol_index
                       WHERE context_id = $1 AND symbol_type = $2 AND symbol_key = $3""",
                    context_id, symbol_type, symbol_key,
                )
            return "DELETE" in result

    async def delete_symbols_by_context(
        self,
        context_id: str,
        symbol_type: str | None = None,
    ) -> int:
        """Delete all symbols in a context."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_delete_symbols_by_context($1, $2)",
                context_id, symbol_type,
            )
            return result or 0

    async def touch_symbol(self, symbol_id: UUID) -> None:
        """Record symbol access (for ranking)."""
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT vg_touch_symbol($1)", symbol_id)

    async def touch_symbols(self, symbol_ids: list[UUID]) -> int:
        """Batch record symbol access."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_touch_symbols($1)",
                symbol_ids,
            )
            return result or 0

    # =========================================================================
    # Edge Operations
    # =========================================================================

    async def add_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        edge_type: str,
        weight: float = 1.0,
        created_by: str = "auto",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """
        Add or update an edge.

        Args:
            source_id: Source symbol UUID
            target_id: Target symbol UUID
            edge_type: Edge type (e.g., "contains", "references")
            weight: Edge weight (for ranking)
            created_by: Creator identifier
            confidence: Confidence score (for LLM-created edges)
            metadata: Additional metadata

        Returns:
            Edge UUID
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_add_edge($1, $2, $3, $4, $5, $6, $7)",
                source_id, target_id, edge_type, weight,
                created_by, confidence, json.dumps(metadata or {}),
            )
            return result

    async def add_edge_by_key(
        self,
        context_id: str,
        source_type: str,
        source_key: str,
        target_type: str,
        target_key: str,
        edge_type: str,
        weight: float = 1.0,
        created_by: str = "auto",
    ) -> UUID | None:
        """
        Add an edge by symbol keys.

        Args:
            context_id: Context ID
            source_type: Source symbol type
            source_key: Source symbol key
            target_type: Target symbol type
            target_key: Target symbol key
            edge_type: Edge type
            weight: Edge weight
            created_by: Creator identifier

        Returns:
            Edge UUID or None if symbols not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_add_edge_by_key($1, $2, $3, $4, $5, $6, $7, $8)",
                context_id, source_type, source_key,
                target_type, target_key, edge_type, weight, created_by,
            )
            return result

    async def get_edges(
        self,
        symbol_id: UUID,
        direction: str = "both",
        edge_types: list[str] | None = None,
    ) -> list[Edge]:
        """
        Get edges connected to a symbol.

        Args:
            symbol_id: Symbol UUID
            direction: "outgoing", "incoming", or "both"
            edge_types: Filter by edge types

        Returns:
            List of edges
        """
        async with self.pool.acquire() as conn:
            if direction == "outgoing":
                query = "SELECT * FROM vg_symbol_edges WHERE source_id = $1"
            elif direction == "incoming":
                query = "SELECT * FROM vg_symbol_edges WHERE target_id = $1"
            else:
                query = "SELECT * FROM vg_symbol_edges WHERE source_id = $1 OR target_id = $1"

            if edge_types:
                query += " AND edge_type = ANY($2)"
                rows = await conn.fetch(query, symbol_id, edge_types)
            else:
                rows = await conn.fetch(query, symbol_id)

            return [self._row_to_edge(row) for row in rows]

    async def increment_edge_weight(
        self,
        source_id: UUID,
        target_id: UUID,
        edge_type: str,
        increment: float = 0.1,
    ) -> float | None:
        """Increment edge weight (for co-access tracking)."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_increment_edge_weight($1, $2, $3, $4)",
                source_id, target_id, edge_type, increment,
            )
            return result

    # =========================================================================
    # Search Operations
    # =========================================================================

    async def search(
        self,
        context_id: str,
        query: str | None = None,
        symbol_types: list[str] | None = None,
        limit: int | None = None,
        order_by: str = "relevance",
    ) -> list[SearchResult]:
        """
        Search symbols.

        Args:
            context_id: Context ID
            query: Search query (matches name, key, content)
            symbol_types: Filter by symbol types
            limit: Maximum results
            order_by: Sort order ("relevance", "recent", "frequent", "modified")

        Returns:
            List of search results with relevance scores
        """
        limit = limit or self.config.default_search_limit

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vg_search_symbols($1, $2, $3, $4, $5)",
                context_id, query, symbol_types, limit, order_by,
            )

            return [
                SearchResult(
                    symbol=Symbol(
                        id=row["id"],
                        context_id=context_id,
                        symbol_type=row["symbol_type"],
                        symbol_key=row["symbol_key"],
                        symbol_name=row["symbol_name"],
                        content=row["content"],
                        content_hash=None,
                        properties=json.loads(row["properties"]) if row["properties"] else {},
                        access_count=0,
                        modification_count=0,
                        last_accessed_at=None,
                        last_modified_at=None,
                        created_at=None,
                        updated_at=None,
                    ),
                    relevance_score=row["relevance_score"],
                )
                for row in rows
            ]

    async def search_by_properties(
        self,
        context_id: str,
        filter_props: dict[str, Any],
        symbol_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[Symbol]:
        """
        Search symbols by properties (e.g., spatial queries).

        Args:
            context_id: Context ID
            filter_props: Property filter (uses JSONB @> operator)
            symbol_types: Filter by symbol types
            limit: Maximum results

        Returns:
            List of matching symbols
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vg_search_by_properties($1, $2, $3, $4)",
                context_id, json.dumps(filter_props), symbol_types, limit,
            )

            return [self._row_to_symbol(row) for row in rows]

    # =========================================================================
    # Graph Traversal
    # =========================================================================

    async def traverse(
        self,
        start_id: UUID,
        depth: int = 2,
        edge_types: list[str] | None = None,
        direction: str = "both",
    ) -> list[TraversalResult]:
        """
        Traverse the symbol graph.

        Args:
            start_id: Starting symbol UUID
            depth: Maximum traversal depth
            edge_types: Filter by edge types
            direction: "outgoing", "incoming", or "both"

        Returns:
            List of traversal results with paths
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vg_traverse_graph($1, $2, $3, $4)",
                start_id, depth, edge_types, direction,
            )

            return [
                TraversalResult(
                    symbol_id=row["symbol_id"],
                    distance=row["distance"],
                    path_ids=row["path_ids"],
                    path_types=row["path_types"],
                )
                for row in rows
            ]

    async def get_neighbors(
        self,
        symbol_id: UUID,
        edge_types: list[str] | None = None,
        direction: str = "both",
    ) -> list[tuple[UUID, str, float, str]]:
        """
        Get direct neighbors of a symbol.

        Returns:
            List of (neighbor_id, edge_type, weight, direction) tuples
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vg_get_neighbors($1, $2, $3)",
                symbol_id, edge_types, direction,
            )

            return [
                (row["neighbor_id"], row["edge_type"], row["weight"], row["direction"])
                for row in rows
            ]

    async def get_related(
        self,
        symbol_id: UUID,
        depth: int = 1,
        edge_types: list[str] | None = None,
        include_content: bool = True,
    ) -> list[Symbol]:
        """
        Get related symbols with full data.

        Args:
            symbol_id: Starting symbol UUID
            depth: Maximum traversal depth
            edge_types: Filter by edge types
            include_content: Whether to include content field

        Returns:
            List of related symbols
        """
        traversal = await self.traverse(symbol_id, depth, edge_types)

        if not traversal:
            return []

        symbol_ids = [t.symbol_id for t in traversal]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM vg_symbol_index WHERE id = ANY($1)",
                symbol_ids,
            )

            symbols = [self._row_to_symbol(row) for row in rows]

            if not include_content:
                for s in symbols:
                    s.content = None

            return symbols

    # =========================================================================
    # Context View Generation
    # =========================================================================

    async def generate_view(
        self,
        context_id: str,
        view_type: str = "summary",
        focus_symbol_id: UUID | None = None,
        token_budget: int = 50000,
        cache_ttl_seconds: int | None = None,
    ) -> str:
        """
        Generate a context view for LLM consumption.

        Args:
            context_id: Context ID
            view_type: View type ("summary", "focused", or custom)
            focus_symbol_id: Focus symbol for "focused" view
            token_budget: Token budget limit
            cache_ttl_seconds: Cache TTL (None to use default)

        Returns:
            Plain text context view
        """
        cache_ttl = cache_ttl_seconds or self.config.default_view_cache_ttl

        async with self.pool.acquire() as conn:
            # Check cache
            cache_key = f"{view_type}:{focus_symbol_id}:{token_budget}"
            cached = await conn.fetchval("""
                SELECT view_content FROM vg_context_views
                WHERE context_id = $1 AND cache_key = $2 AND expires_at > now()
            """, context_id, cache_key)

            if cached:
                return cached

            # Generate view
            if view_type == "summary":
                content = await conn.fetchval(
                    "SELECT vg_generate_summary_view($1, $2)",
                    context_id, token_budget,
                )
            elif view_type == "focused" and focus_symbol_id:
                content = await conn.fetchval(
                    "SELECT vg_generate_focused_view($1, $2, $3, $4)",
                    context_id, focus_symbol_id, 2, token_budget,
                )
            else:
                content = await conn.fetchval(
                    "SELECT vg_generate_summary_view($1, $2)",
                    context_id, token_budget,
                )

            # Cache result
            await conn.execute("""
                INSERT INTO vg_context_views (context_id, view_name, view_content, cache_key, expires_at)
                VALUES ($1, $2, $3, $4, now() + ($5 || ' seconds')::INTERVAL)
                ON CONFLICT (context_id, view_name, cache_key) DO UPDATE SET
                    view_content = EXCLUDED.view_content,
                    expires_at = EXCLUDED.expires_at
            """, context_id, view_type, content, cache_key, str(cache_ttl))

            return content or ""

    async def invalidate_views(self, context_id: str) -> int:
        """Invalidate all cached views for a context."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM vg_context_views WHERE context_id = $1",
                context_id,
            )
            # Parse "DELETE X" to get count
            return int(result.split()[-1]) if "DELETE" in result else 0

    # =========================================================================
    # Statistics & Maintenance
    # =========================================================================

    async def get_stats(self, context_id: str) -> dict[str, Any]:
        """Get statistics for a context."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT vg_get_stats($1)",
                context_id,
            )
            return json.loads(result) if result else {}

    async def cleanup(self, context_id: str | None = None) -> dict[str, int]:
        """
        Cleanup expired and orphan data.

        Args:
            context_id: Specific context to cleanup (None for all)

        Returns:
            Cleanup statistics
        """
        async with self.pool.acquire() as conn:
            views_cleaned = await conn.fetchval("SELECT vg_cleanup_expired_views()")

            orphans_cleaned = 0
            if context_id:
                orphans_cleaned = await conn.fetchval(
                    "SELECT vg_cleanup_orphan_symbols($1, $2)",
                    context_id, 24,
                )

            return {
                "views_cleaned": views_cleaned or 0,
                "orphans_cleaned": orphans_cleaned or 0,
            }

    # =========================================================================
    # Feedback Module Access
    # =========================================================================

    @property
    def feedback(self) -> "FeedbackModule":
        """
        Access the feedback module (if enabled).

        Raises:
            RuntimeError: If feedback is not enabled
        """
        if not self.config.enable_feedback:
            raise RuntimeError(
                "Feedback module is not enabled. "
                "Set enable_feedback=True in GraphConfig."
            )
        if self._feedback_module is None:
            raise RuntimeError(
                "Feedback module not initialized. "
                "Call init_schema() first."
            )
        return self._feedback_module

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_symbol(self, row: Any) -> Symbol:
        """Convert database row to Symbol."""
        return Symbol(
            id=row["id"],
            context_id=row["context_id"],
            symbol_type=row["symbol_type"],
            symbol_key=row["symbol_key"],
            symbol_name=row["symbol_name"],
            content=row["content"],
            content_hash=row.get("content_hash"),
            properties=json.loads(row["properties"]) if row["properties"] else {},
            access_count=row.get("access_count", 0),
            modification_count=row.get("modification_count", 0),
            last_accessed_at=row.get("last_accessed_at"),
            last_modified_at=row.get("last_modified_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_edge(self, row: Any) -> Edge:
        """Convert database row to Edge."""
        return Edge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            edge_type=row["edge_type"],
            weight=row["weight"],
            created_by=row["created_by"],
            confidence=row["confidence"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
        )
