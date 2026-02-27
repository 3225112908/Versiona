"""
Versiona Client - Async PostgreSQL Client.

Direct connection to PostgreSQL, no HTTP API Server needed.
Uses asyncpg for async non-blocking operations.

Usage Example:

    from versiona import VersionaClient

    # Create client
    client = await VersionaClient.create("postgresql://user:pass@localhost/db")

    # Create Context
    ctx_id = await client.create_context("project_123", level="L0")

    # Fork child Context
    task_id = await client.fork("project_123", "task_abc")

    # Set data (supports dual-mode TTL)
    await client.set(task_id, "thinking", ["Analyzing requirements..."], ttl_turns=3, current_turn=0)
    await client.set_output(task_id, "summary", "Task completed")

    # Commit
    await client.commit(task_id, message="Task completed")

    # Merge back to parent
    await client.merge(task_id)

    # Close
    await client.close()
"""

from __future__ import annotations

import json
import asyncio
from typing import Any
from uuid import uuid4

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

# Import types from context module
from versiona.context.types import (
    ContextLevel,
    DataCategory,
    ContextNode,
    ContextVersion,
    ContextData,
    DiffResult,
    Branch,
    Tag,
    VersionaConfig,
)


# ============================================================
# Versiona Client
# ============================================================


class VersionaClient:
    """
    Versiona Async Client.

    Direct connection to PostgreSQL, supports:
    - Dual-dimension Context (horizontal tree + vertical versions)
    - Async non-blocking operations
    - Connection pooling
    - Auto cleanup
    """

    def __init__(self, config: VersionaConfig | None = None):
        """
        Initialize client.

        Args:
            config: Configuration
        """
        if asyncpg is None:
            raise ImportError("asyncpg is required. Install with: pip install asyncpg")

        self.config = config or VersionaConfig()
        self._pool: asyncpg.Pool | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._is_connected = False

    @classmethod
    async def create(
        cls,
        dsn: str | None = None,
        config: VersionaConfig | None = None,
        **kwargs: Any,
    ) -> "VersionaClient":
        """
        Create and connect client.

        Args:
            dsn: PostgreSQL connection string
            config: Pre-built VersionaConfig object (takes precedence over dsn/kwargs)
            **kwargs: Other configuration parameters (ignored if config is provided)

        Returns:
            Connected client

        Examples:
            # Simple usage with DSN
            client = await VersionaClient.create("postgresql://localhost/db")

            # With pre-built config (recommended for custom schemas)
            config = VersionaConfig(
                dsn="postgresql://localhost/db",
                table_prefix="dxf_",
                content_storage_mode="inline",
                custom_node_columns={"content": "TEXT"},
            )
            client = await VersionaClient.create(config=config)
        """
        if config is not None:
            # Use provided config directly
            pass
        elif dsn:
            config = VersionaConfig(dsn=dsn, **kwargs)
        else:
            config = VersionaConfig(**kwargs)

        client = cls(config)
        await client.connect()
        return client

    async def connect(self) -> None:
        """Connect to the database."""
        if self._is_connected:
            return

        self._pool = await asyncpg.create_pool(
            self.config.dsn,
            min_size=self.config.min_pool_size,
            max_size=self.config.max_pool_size,
            command_timeout=self.config.command_timeout,
        )
        self._is_connected = True

        # Start auto cleanup
        if self.config.auto_cleanup:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        """Close the connection."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._pool:
            await self._pool.close()
            self._pool = None

        self._is_connected = False

    async def __aenter__(self) -> "VersionaClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._pool

    # =========================================================================
    # Schema Management
    # =========================================================================

    async def init_schema(
        self,
        extensions: list[str] | None = None,
        extension_options: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """
        Initialize the database schema.

        Uses the client's config (table_prefix, custom columns, etc.) to generate schema.

        Args:
            extensions: List of extensions to load (e.g., ["graph"])
            extension_options: Options for each extension
                e.g., {"graph": {"include_feedback": True}}
        """
        from versiona.db.schema import get_schema_sql, get_extension_schema, get_extension_functions

        async with self.pool.acquire() as conn:
            # Create core schema with config
            core_sql = get_schema_sql(self.config)
            await conn.execute(core_sql)

            # Load extensions if specified
            if extensions:
                extension_options = extension_options or {}
                for ext_name in extensions:
                    opts = extension_options.get(ext_name, {})
                    # Pass table prefix to extensions
                    opts.setdefault("table_prefix", self.config.table_prefix)

                    schema_sql = get_extension_schema(ext_name, **opts)
                    await conn.execute(schema_sql)

                    functions_sql = get_extension_functions(ext_name, **opts)
                    if functions_sql:
                        await conn.execute(functions_sql)

    async def init_extension(
        self,
        extension_name: str,
        **options: Any,
    ) -> None:
        """
        Initialize a single extension's schema.

        Args:
            extension_name: Extension name (e.g., "graph")
            **options: Extension options
        """
        from versiona.db.schema import get_extension_schema, get_extension_functions

        async with self.pool.acquire() as conn:
            # Create tables
            schema_sql = get_extension_schema(extension_name, **options)
            await conn.execute(schema_sql)

            # Create functions
            functions_sql = get_extension_functions(extension_name, **options)
            if functions_sql:
                await conn.execute(functions_sql)

    async def check_schema(self) -> bool:
        """Check if schema exists."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'context_nodes'
                )
            """)
            return bool(result)

    async def check_extension(self, extension_name: str) -> bool:
        """
        Check if extension schema exists.

        Args:
            extension_name: Extension name

        Returns:
            True if extension tables exist
        """
        # Main table name for each extension
        extension_tables = {
            "graph": "vg_symbol_index",
        }

        table_name = extension_tables.get(extension_name)
        if not table_name:
            return False

        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = $1
                )
            """, table_name)
            return bool(result)

    # =========================================================================
    # Context Node Operations (Horizontal Tree)
    # =========================================================================

    async def create_context(
        self,
        context_id: str,
        parent_id: str | None = None,
        level: ContextLevel | str = ContextLevel.TASK,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a Context node.

        Args:
            context_id: Context ID
            parent_id: Parent node ID (if any)
            level: Level (L0, L1, L2)
            name: Name
            metadata: Metadata

        Returns:
            Context ID
        """
        level_str = level.value if isinstance(level, ContextLevel) else level

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT create_context_node($1, $2, $3, $4, $5)",
                context_id,
                parent_id,
                level_str,
                name,
                json.dumps(metadata or {}),
            )
            return result

    async def fork(
        self,
        source_id: str,
        new_id: str | None = None,
        level: ContextLevel | str | None = None,
        inherit_output: bool = True,
    ) -> str:
        """
        Fork a child Context (horizontal branch).

        Args:
            source_id: Source Context ID
            new_id: New Context ID (auto-generated if not provided)
            level: New Context level (auto-inferred if not provided)
            inherit_output: Whether to inherit output data

        Returns:
            New Context ID
        """
        new_id = new_id or f"ctx_{uuid4().hex[:8]}"
        level_str = level.value if isinstance(level, ContextLevel) else level

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT fork_context($1, $2, $3, $4)",
                source_id,
                new_id,
                level_str,
                inherit_output,
            )
            return result

    async def get_node(self, context_id: str) -> ContextNode | None:
        """Get Context node information."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, parent_id, level, name, status, current_version,
                       metadata, created_at, updated_at
                FROM context_nodes WHERE id = $1
            """, context_id)

            if not row:
                return None

            return ContextNode(
                id=row["id"],
                parent_id=row["parent_id"],
                level=ContextLevel(row["level"]),
                name=row["name"],
                status=row["status"],
                current_version=row["current_version"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def get_children(
        self,
        context_id: str,
        level: ContextLevel | str | None = None,
        include_nested: bool = False,
    ) -> list[dict[str, Any]]:
        """Get list of child nodes."""
        level_str = level.value if isinstance(level, ContextLevel) else level

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT get_children($1, $2, $3)",
                context_id,
                level_str,
                include_nested,
            )
            return json.loads(result) if result else []

    async def delete_context(
        self,
        context_id: str,
        hard: bool = False,
    ) -> bool:
        """Delete a Context."""
        async with self.pool.acquire() as conn:
            if hard:
                await conn.execute(
                    "DELETE FROM context_nodes WHERE id = $1",
                    context_id,
                )
            else:
                await conn.execute(
                    "UPDATE context_nodes SET status = 'deleted' WHERE id = $1",
                    context_id,
                )
            return True

    # =========================================================================
    # Context Data Operations
    # =========================================================================

    async def get(
        self,
        context_id: str,
        version: int | None = None,
        include_inherited: bool = True,
        exclude_soft_deleted: bool = True,
    ) -> ContextData | None:
        """
        Get Context data.

        Args:
            context_id: Context ID
            version: Version number (default: current version)
            include_inherited: Whether to include inherited data
            exclude_soft_deleted: Whether to exclude soft deleted data

        Returns:
            Context data
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT get_context($1, $2, $3, $4)",
                context_id,
                version,
                include_inherited,
                exclude_soft_deleted,
            )

            if not result:
                return None

            data = json.loads(result)
            return ContextData(
                node_id=data["node_id"],
                version=data["version"],
                level=ContextLevel(data["level"]),
                local_data=data.get("local_data", {}),
                output_data=data.get("output_data", {}),
                inherited=data.get("inherited", {}),
                soft_deleted_keys=data.get("soft_deleted_keys", []),
            )

    async def get_value(
        self,
        context_id: str,
        key: str,
        default: Any = None,
        current_turn: int | None = None,
    ) -> Any:
        """
        Get a single value (using KV fast query).

        Automatically filters out time-expired and turn-expired data.

        Args:
            context_id: Context ID
            key: Key
            default: Default value
            current_turn: Current turn (for turn expiration check)
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT kv_get($1, $2, false, $3)",
                context_id,
                key,
                current_turn,
            )

            if result is None:
                return default

            return json.loads(result)

    async def set(
        self,
        context_id: str,
        key: str,
        value: Any,
        category: DataCategory | str = DataCategory.LOCAL,
        ttl_seconds: int | None = None,
        ttl_turns: int | None = None,
        current_turn: int | None = None,
    ) -> None:
        """
        Set data (KV fast operation, does not create version).

        Supports dual-mode TTL:
        - Time TTL: For real-time information (weather, stock prices, API responses)
        - Turn TTL: For Agent loop process data (thinking, tool_results)

        Args:
            context_id: Context ID
            key: Key
            value: Value
            category: Category (local/output)
            ttl_seconds: Time TTL (seconds), expires after time
            ttl_turns: Turn TTL (turns), expires after N turns
            current_turn: Current turn (required when using turn TTL)

        Examples:
            # Time TTL - real-time information
            await client.set(ctx_id, "weather", data, ttl_seconds=1800)

            # Turn TTL - Agent loop process data
            await client.set(ctx_id, "tool_results", data, ttl_turns=5, current_turn=10)

            # Both (whichever comes first expires)
            await client.set(ctx_id, "data", data, ttl_seconds=3600, ttl_turns=10, current_turn=5)
        """
        category_str = category.value if isinstance(category, DataCategory) else category

        # Auto-set time TTL
        if ttl_seconds is None and key in self.config.default_time_ttl:
            ttl_seconds = self.config.default_time_ttl[key]

        # Auto-set turn TTL (only when current_turn is provided)
        if ttl_turns is None and current_turn is not None and key in self.config.default_turn_ttl:
            ttl_turns = self.config.default_turn_ttl[key]

        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT kv_set($1, $2, $3, $4, $5, $6, $7)",
                context_id,
                key,
                json.dumps(value),
                category_str,
                ttl_seconds,
                ttl_turns,
                current_turn,
            )

    async def set_local(
        self,
        context_id: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        ttl_turns: int | None = None,
        current_turn: int | None = None,
    ) -> None:
        """Set local data (not inherited)."""
        await self.set(context_id, key, value, DataCategory.LOCAL, ttl_seconds, ttl_turns, current_turn)

    async def set_output(
        self,
        context_id: str,
        key: str,
        value: Any,
    ) -> None:
        """Set output data (inheritable, no TTL)."""
        await self.set(context_id, key, value, DataCategory.OUTPUT, None, None, None)

    async def append(
        self,
        context_id: str,
        key: str,
        value: Any,
        category: DataCategory | str = DataCategory.LOCAL,
        current_turn: int | None = None,
    ) -> None:
        """Append to a list."""
        existing = await self.get_value(context_id, key, [], current_turn)
        if not isinstance(existing, list):
            existing = [existing] if existing else []
        existing.append(value)
        await self.set(context_id, key, existing, category, None, None, current_turn)

    async def soft_delete(
        self,
        context_id: str,
        key: str,
    ) -> None:
        """Soft delete a key."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "SELECT kv_soft_delete($1, $2)",
                context_id,
                key,
            )

    async def hard_delete(
        self,
        context_id: str,
        key: str,
    ) -> None:
        """Hard delete a key."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM context_kv WHERE node_id = $1 AND key = $2",
                context_id,
                key,
            )

    async def get_all(
        self,
        context_id: str,
        category: str | None = None,
        current_turn: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all KV data.

        Args:
            context_id: Context ID
            category: Category filter (local/output)
            current_turn: Current turn (for filtering expired data)

        Returns:
            List of KV items, each containing key, value, category, created_at_turn, expires_at_turn
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT key, value, category, created_at_turn, expires_at_turn
                FROM context_kv
                WHERE node_id = $1
                AND NOT is_soft_deleted
                AND ($2::TEXT IS NULL OR category = $2::TEXT)
                AND (expires_at IS NULL OR expires_at > now())
                AND (expires_at_turn IS NULL OR $3::INT IS NULL OR expires_at_turn > $3::INT)
            """, context_id, category, current_turn)

            return [
                {
                    "key": row["key"],
                    "value": json.loads(row["value"]) if row["value"] else None,
                    "category": row["category"],
                    "created_at_turn": row["created_at_turn"],
                    "expires_at_turn": row["expires_at_turn"],
                }
                for row in rows
            ]

    # Aliases for backward compatibility
    kv_get = get_value
    kv_set = set
    kv_get_all = get_all
    kv_soft_delete = soft_delete

    async def expire_by_turn(
        self,
        context_id: str,
        current_turn: int,
    ) -> int:
        """
        Soft delete all turn-expired data.

        Recommended to call at the beginning of each Agent loop turn to clean up expired process data.

        Args:
            context_id: Context ID
            current_turn: Current turn

        Returns:
            Number of soft deleted items

        Example:
            # Agent loop
            for turn in range(max_turns):
                # Clean up expired data
                await client.expire_by_turn(ctx_id, turn)

                # Execute current turn
                thinking = await llm.think(...)
                await client.set_local(ctx_id, "thinking", thinking, ttl_turns=3, current_turn=turn)

                result = await tool.execute(...)
                await client.set_local(ctx_id, "tool_results", result, ttl_turns=5, current_turn=turn)
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT kv_expire_by_turn($1, $2)",
                context_id,
                current_turn,
            )
            return result or 0

    # =========================================================================
    # Version Operations (Vertical Versions)
    # =========================================================================

    async def commit(
        self,
        context_id: str,
        message: str | None = None,
        author_id: str | None = None,
        soft_delete_keys: list[str] | None = None,
    ) -> int:
        """
        Commit (create new version).

        Collects current KV data and creates a new version snapshot.

        Args:
            context_id: Context ID
            message: Commit message
            author_id: Author ID
            soft_delete_keys: Keys to soft delete

        Returns:
            New version number
        """
        async with self.pool.acquire() as conn:
            # Collect KV data
            rows = await conn.fetch("""
                SELECT key, value, category FROM context_kv
                WHERE node_id = $1 AND NOT is_soft_deleted
                AND (expires_at IS NULL OR expires_at > now())
            """, context_id)

            local_data = {}
            output_data = {}

            for row in rows:
                val = json.loads(row["value"]) if row["value"] else None
                if row["category"] == "output":
                    output_data[row["key"]] = val
                else:
                    local_data[row["key"]] = val

            # Create version
            new_version = await conn.fetchval(
                "SELECT commit_context($1, $2, $3, $4, $5, $6)",
                context_id,
                json.dumps(local_data),
                json.dumps(output_data),
                soft_delete_keys,
                message,
                author_id,
            )

            return new_version

    async def checkout(
        self,
        context_id: str,
        version: int,
        create_new_version: bool = True,
    ) -> int:
        """
        Checkout (switch to specified version).

        Args:
            context_id: Context ID
            version: Target version number
            create_new_version: Whether to create a new version (recommended True)

        Returns:
            Current version number
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT checkout_version($1, $2, $3)",
                context_id,
                version,
                create_new_version,
            )
            return result

    async def get_history(
        self,
        context_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get version history."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT get_version_history($1, $2, $3)",
                context_id,
                limit,
                offset,
            )
            return json.loads(result) if result else []

    async def diff(
        self,
        context_id: str,
        version_a: int,
        version_b: int,
    ) -> DiffResult:
        """Compare two versions."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT diff_versions($1, $2, $3)",
                context_id,
                version_a,
                version_b,
            )

            data = json.loads(result)
            return DiffResult(
                node_id=data["node_id"],
                from_version=data["from_version"],
                to_version=data["to_version"],
                added=data.get("added", {}),
                removed=data.get("removed", {}),
                modified=data.get("modified", {}),
            )

    # =========================================================================
    # Branch Operations
    # =========================================================================

    async def create_branch(
        self,
        context_id: str,
        branch_name: str,
        from_version: int | None = None,
    ) -> Branch:
        """
        Create a branch.

        Args:
            context_id: Context ID
            branch_name: Branch name
            from_version: From which version to create (default: current version)

        Returns:
            Branch object
        """
        async with self.pool.acquire() as conn:
            # Get current version
            if from_version is None:
                from_version = await conn.fetchval(
                    "SELECT current_version FROM context_nodes WHERE id = $1",
                    context_id,
                )

            # Create branch
            row = await conn.fetchrow("""
                INSERT INTO context_branches (node_id, name, head_version)
                VALUES ($1, $2, $3)
                RETURNING id, node_id, name, head_version, is_default,
                          forked_from_node, forked_from_version, created_at
            """, context_id, branch_name, from_version)

            return Branch(
                id=str(row["id"]),
                node_id=row["node_id"],
                name=row["name"],
                head_version=row["head_version"],
                is_default=row["is_default"],
                forked_from_node=row["forked_from_node"],
                forked_from_version=row["forked_from_version"],
                created_at=row["created_at"],
            )

    async def list_branches(self, context_id: str) -> list[Branch]:
        """List all branches."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, node_id, name, head_version, is_default,
                       forked_from_node, forked_from_version, created_at
                FROM context_branches WHERE node_id = $1
                ORDER BY is_default DESC, created_at
            """, context_id)

            return [
                Branch(
                    id=str(row["id"]),
                    node_id=row["node_id"],
                    name=row["name"],
                    head_version=row["head_version"],
                    is_default=row["is_default"],
                    forked_from_node=row["forked_from_node"],
                    forked_from_version=row["forked_from_version"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def get_branch(self, context_id: str, branch_name: str) -> Branch | None:
        """Get branch information."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, node_id, name, head_version, is_default,
                       forked_from_node, forked_from_version, created_at
                FROM context_branches
                WHERE node_id = $1 AND name = $2
            """, context_id, branch_name)

            if not row:
                return None

            return Branch(
                id=str(row["id"]),
                node_id=row["node_id"],
                name=row["name"],
                head_version=row["head_version"],
                is_default=row["is_default"],
                forked_from_node=row["forked_from_node"],
                forked_from_version=row["forked_from_version"],
                created_at=row["created_at"],
            )

    async def switch_branch(self, context_id: str, branch_name: str) -> int:
        """
        Switch to the specified branch.

        Args:
            context_id: Context ID
            branch_name: Branch name

        Returns:
            Version number after switching
        """
        async with self.pool.acquire() as conn:
            # Get branch head_version
            head_version = await conn.fetchval("""
                SELECT head_version FROM context_branches
                WHERE node_id = $1 AND name = $2
            """, context_id, branch_name)

            if head_version is None:
                raise ValueError(f"Branch not found: {branch_name}")

            # Update current_version
            await conn.execute("""
                UPDATE context_nodes SET current_version = $1, updated_at = now()
                WHERE id = $2
            """, head_version, context_id)

            # Update default branch
            await conn.execute("""
                UPDATE context_branches SET is_default = false WHERE node_id = $1
            """, context_id)
            await conn.execute("""
                UPDATE context_branches SET is_default = true
                WHERE node_id = $1 AND name = $2
            """, context_id, branch_name)

            return head_version

    async def delete_branch(self, context_id: str, branch_name: str) -> bool:
        """Delete a branch (cannot delete default branch)."""
        async with self.pool.acquire() as conn:
            # Check if it's the default branch
            is_default = await conn.fetchval("""
                SELECT is_default FROM context_branches
                WHERE node_id = $1 AND name = $2
            """, context_id, branch_name)

            if is_default:
                raise ValueError("Cannot delete default branch")

            await conn.execute("""
                DELETE FROM context_branches WHERE node_id = $1 AND name = $2
            """, context_id, branch_name)

            return True

    # =========================================================================
    # Tag Operations
    # =========================================================================

    async def create_tag(
        self,
        context_id: str,
        tag_name: str,
        version: int | None = None,
        message: str | None = None,
    ) -> Tag:
        """
        Create a tag (tag a version).

        Args:
            context_id: Context ID
            tag_name: Tag name
            version: Version number (default: current version)
            message: Tag message

        Returns:
            Tag object
        """
        async with self.pool.acquire() as conn:
            # Ensure tags table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS context_tags (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    version INT NOT NULL,
                    message TEXT,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(node_id, name)
                )
            """)

            # Get current version
            if version is None:
                version = await conn.fetchval(
                    "SELECT current_version FROM context_nodes WHERE id = $1",
                    context_id,
                )

            # Create tag
            row = await conn.fetchrow("""
                INSERT INTO context_tags (node_id, name, version, message)
                VALUES ($1, $2, $3, $4)
                RETURNING id, node_id, name, version, message, created_at
            """, context_id, tag_name, version, message)

            return Tag(
                id=str(row["id"]),
                node_id=row["node_id"],
                name=row["name"],
                version=row["version"],
                message=row["message"],
                created_at=row["created_at"],
            )

    async def list_tags(self, context_id: str) -> list[Tag]:
        """List all tags."""
        async with self.pool.acquire() as conn:
            # Ensure table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS context_tags (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    version INT NOT NULL,
                    message TEXT,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(node_id, name)
                )
            """)

            rows = await conn.fetch("""
                SELECT id, node_id, name, version, message, created_at
                FROM context_tags WHERE node_id = $1
                ORDER BY version DESC
            """, context_id)

            return [
                Tag(
                    id=str(row["id"]),
                    node_id=row["node_id"],
                    name=row["name"],
                    version=row["version"],
                    message=row["message"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def get_tag(self, context_id: str, tag_name: str) -> Tag | None:
        """Get tag information."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, node_id, name, version, message, created_at
                FROM context_tags
                WHERE node_id = $1 AND name = $2
            """, context_id, tag_name)

            if not row:
                return None

            return Tag(
                id=str(row["id"]),
                node_id=row["node_id"],
                name=row["name"],
                version=row["version"],
                message=row["message"],
                created_at=row["created_at"],
            )

    async def checkout_tag(self, context_id: str, tag_name: str) -> int:
        """Checkout to the version corresponding to the tag."""
        tag = await self.get_tag(context_id, tag_name)
        if not tag:
            raise ValueError(f"Tag not found: {tag_name}")

        return await self.checkout(context_id, tag.version)

    async def delete_tag(self, context_id: str, tag_name: str) -> bool:
        """Delete a tag."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM context_tags WHERE node_id = $1 AND name = $2
            """, context_id, tag_name)
            return True

    # =========================================================================
    # Revert & Reset Operations
    # =========================================================================

    async def revert(
        self,
        context_id: str,
        version: int,
        message: str | None = None,
    ) -> int:
        """
        Revert (undo to specified version, creating a new commit).

        Unlike checkout, revert creates a new commit that represents
        "reverting to the state of v{version}".

        Args:
            context_id: Context ID
            version: Version to revert to
            message: Commit message

        Returns:
            New version number
        """
        async with self.pool.acquire() as conn:
            # Get target version data
            row = await conn.fetchrow("""
                SELECT local_data, output_data, soft_deleted_keys
                FROM context_versions
                WHERE node_id = $1 AND version = $2
            """, context_id, version)

            if not row:
                raise ValueError(f"Version not found: {version}")

            # Create new version (using target version data)
            new_version = await self.commit(
                context_id,
                message=message or f"Revert to v{version}",
            )

            # Update KV table to match target version
            local_data = json.loads(row["local_data"]) if row["local_data"] else {}
            output_data = json.loads(row["output_data"]) if row["output_data"] else {}

            # Clear current KV
            await conn.execute(
                "DELETE FROM context_kv WHERE node_id = $1",
                context_id,
            )

            # Rewrite target version data
            for key, value in local_data.items():
                await self.set_local(context_id, key, value)
            for key, value in output_data.items():
                await self.set_output(context_id, key, value)

            return new_version

    async def reset(
        self,
        context_id: str,
        version: int,
        hard: bool = False,
    ) -> int:
        """
        Reset (reset to specified version).

        Args:
            context_id: Context ID
            version: Target version
            hard: If True, delete subsequent versions; otherwise just move HEAD

        Returns:
            Current version number
        """
        async with self.pool.acquire() as conn:
            # Check if version exists
            exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM context_versions WHERE node_id = $1 AND version = $2
                )
            """, context_id, version)

            if not exists:
                raise ValueError(f"Version not found: {version}")

            if hard:
                # Hard reset: delete subsequent versions
                await conn.execute("""
                    DELETE FROM context_versions
                    WHERE node_id = $1 AND version > $2
                """, context_id, version)

            # Update current_version
            await conn.execute("""
                UPDATE context_nodes SET current_version = $1, updated_at = now()
                WHERE id = $2
            """, version, context_id)

            # Update default branch head
            await conn.execute("""
                UPDATE context_branches SET head_version = $1, updated_at = now()
                WHERE node_id = $2 AND is_default = true
            """, version, context_id)

            # Sync KV table
            row = await conn.fetchrow("""
                SELECT local_data, output_data FROM context_versions
                WHERE node_id = $1 AND version = $2
            """, context_id, version)

            # Clear and rebuild KV
            await conn.execute("DELETE FROM context_kv WHERE node_id = $1", context_id)

            if row:
                local_data = json.loads(row["local_data"]) if row["local_data"] else {}
                output_data = json.loads(row["output_data"]) if row["output_data"] else {}

                for key, value in local_data.items():
                    await self.set_local(context_id, key, value)
                for key, value in output_data.items():
                    await self.set_output(context_id, key, value)

            return version

    # =========================================================================
    # Merge Operations
    # =========================================================================

    async def merge(
        self,
        source_id: str,
        target_id: str | None = None,
        merge_type: str = "output_only",
        message: str | None = None,
    ) -> int:
        """
        Merge Context.

        Args:
            source_id: Source Context ID
            target_id: Target Context ID (default: parent)
            merge_type: Merge type (output_only, full)
            message: Merge message

        Returns:
            Target's new version number
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT merge_context($1, $2, $3, $4)",
                source_id,
                target_id,
                merge_type,
                message,
            )
            return result

    async def finalize(
        self,
        context_id: str,
        summary: str | None = None,
        output: Any = None,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Complete Context execution.

        1. Soft delete all local data
        2. Set output
        3. Commit
        4. Return output data

        Args:
            context_id: Context ID
            summary: Summary
            output: Output
            artifacts: Produced files

        Returns:
            Output data
        """
        # Get all local keys
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT key FROM context_kv
                WHERE node_id = $1 AND category = 'local'
            """, context_id)

            local_keys = [row["key"] for row in rows]

        # Set output
        if summary:
            await self.set_output(context_id, "summary", summary)
        if output is not None:
            await self.set_output(context_id, "output", output)
        if artifacts:
            await self.set_output(context_id, "artifacts", artifacts)

        # Commit with soft delete
        await self.commit(
            context_id,
            message="Finalized",
            soft_delete_keys=local_keys,
        )

        # Return output
        ctx_data = await self.get(context_id, exclude_soft_deleted=True)
        return ctx_data.output_data if ctx_data else {}

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    async def get_for_llm(
        self,
        context_id: str,
    ) -> dict[str, Any]:
        """
        Get data for LLM consumption.

        Excludes soft deleted, includes inherited.
        """
        ctx_data = await self.get(
            context_id,
            include_inherited=True,
            exclude_soft_deleted=True,
        )

        if not ctx_data:
            return {}

        # Merge inherited + output + local (excluding soft deleted)
        result = {}
        result.update(ctx_data.inherited)
        result.update(ctx_data.output_data)
        result.update(ctx_data.local_data)

        return result

    async def get_for_display(
        self,
        context_id: str,
    ) -> dict[str, Any]:
        """
        Get data for frontend display.

        Includes all data (including soft deleted), but marked.
        """
        ctx_data = await self.get(
            context_id,
            include_inherited=True,
            exclude_soft_deleted=False,
        )

        if not ctx_data:
            return {}

        return {
            "node_id": ctx_data.node_id,
            "version": ctx_data.version,
            "level": ctx_data.level.value,
            "local_data": ctx_data.local_data,
            "output_data": ctx_data.output_data,
            "inherited": ctx_data.inherited,
            "soft_deleted_keys": ctx_data.soft_deleted_keys,
        }

    # =========================================================================
    # Snapshot Operations
    # =========================================================================

    async def create_snapshot(
        self,
        root_node_id: str,
        name: str | None = None,
        snapshot_type: str = "manual",
        message: str | None = None,
        author_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a snapshot (record version combination of all child nodes at a point in time).

        Args:
            root_node_id: Root node ID
            name: Snapshot name
            snapshot_type: Snapshot type (auto, manual, before_agent, checkpoint)
            message: Snapshot message
            author_id: Author ID
            metadata: Metadata

        Returns:
            Snapshot ID
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT create_snapshot($1, $2, $3, $4, $5, $6)",
                root_node_id,
                name,
                snapshot_type,
                message,
                author_id,
                json.dumps(metadata or {}),
            )
            return str(result)

    async def restore_snapshot(
        self,
        snapshot_id: str,
        author_id: str | None = None,
    ) -> int:
        """
        Restore snapshot (rollback all nodes to their versions at snapshot time).

        Args:
            snapshot_id: Snapshot ID
            author_id: Operator ID

        Returns:
            Number of restored nodes
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT restore_snapshot($1::UUID, $2)",
                snapshot_id,
                author_id,
            )
            return result or 0

    async def list_snapshots(
        self,
        root_node_id: str,
        snapshot_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List snapshots.

        Args:
            root_node_id: Root node ID
            snapshot_type: Snapshot type filter
            limit: Limit count
            offset: Offset

        Returns:
            Snapshot list
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, message, snapshot_type,
                       jsonb_array_length(
                           COALESCE(
                               (SELECT jsonb_agg(k) FROM jsonb_object_keys(node_versions) AS k),
                               '[]'::jsonb
                           )
                       ) AS node_count,
                       created_at, author_id
                FROM context_snapshots
                WHERE root_node_id = $1
                AND ($2::TEXT IS NULL OR snapshot_type = $2::TEXT)
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
            """, root_node_id, snapshot_type, limit, offset)

            return [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "message": row["message"],
                    "snapshot_type": row["snapshot_type"],
                    "node_count": row["node_count"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "author_id": row["author_id"],
                }
                for row in rows
            ]

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Get snapshot details."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT get_snapshot($1::UUID)",
                snapshot_id,
            )
            return json.loads(result) if result else None

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT delete_snapshot($1::UUID)",
                snapshot_id,
            )
            return result or False

    # =========================================================================
    # Fork Session (Agent-specific)
    # =========================================================================

    async def fork_session(
        self,
        source_id: str,
        new_id: str,
        fork_at_turn: int,
        name: str | None = None,
        copy_kv: bool = True,
    ) -> str:
        """
        Fork Session (for Agent: fork from a turn, copy KV).

        Different from fork():
        - fork(): Create child node, inherit output_data
        - fork_session(): Create root node, copy KV up to a turn

        Args:
            source_id: Source Session ID
            new_id: New Session ID
            fork_at_turn: Turn to fork from
            name: New Session name
            copy_kv: Whether to copy KV

        Returns:
            New Session ID
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT fork_session($1, $2, $3, $4, $5)",
                source_id,
                new_id,
                fork_at_turn,
                name,
                copy_kv,
            )
            return result

    # =========================================================================
    # Direct Node Content Operations (for inline content mode)
    # =========================================================================

    async def update_node_content(
        self,
        context_id: str,
        content: str | None = None,
        **custom_columns: Any,
    ) -> bool:
        """
        直接更新 node 的自訂欄位（不創建版本）。

        適用場景：
        - DXF entity 內容更新
        - 任何需要直接存在 node 上的資料（而非 KV 表）

        Args:
            context_id: Node ID
            content: Content to update (if node has 'content' column)
            **custom_columns: Other custom columns to update
                (e.g., min_x=0, max_x=100, color_override=7)

        Returns:
            Whether update was successful

        Example:
            await client.update_node_content(
                entity_id,
                content=yaml_content,
                min_x=0, max_x=100,
                min_y=0, max_y=50,
            )
        """
        columns = []
        values = [context_id]
        idx = 2

        if content is not None:
            columns.append(f"content = ${idx}")
            values.append(content)
            idx += 1

        for col, val in custom_columns.items():
            columns.append(f"{col} = ${idx}")
            values.append(val)
            idx += 1

        if not columns:
            return False

        async with self.pool.acquire() as conn:
            result = await conn.execute(f"""
                UPDATE {self.config.nodes_table}
                SET {", ".join(columns)}, updated_at = NOW()
                WHERE id = $1
            """, *values)

        return "UPDATE 1" in result

    async def update_nodes_content_batch(
        self,
        updates: list[dict[str, Any]],
    ) -> int:
        """
        批量更新多個 node 的內容（使用事務）。

        Args:
            updates: List of dicts with "id" and custom columns
                [{"id": "node1", "content": "...", "min_x": 0}, ...]

        Returns:
            Number of updated nodes

        Example:
            await client.update_nodes_content_batch([
                {"id": id1, "content": content1, "min_x": 0, "max_x": 100},
                {"id": id2, "content": content2, "min_x": 50, "max_x": 150},
            ])
        """
        if not updates:
            return 0

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                updated = 0
                for u in updates:
                    u = dict(u)  # Copy to avoid modifying original
                    node_id = u.pop("id")
                    columns = []
                    values = [node_id]
                    idx = 2

                    for col, val in u.items():
                        columns.append(f"{col} = ${idx}")
                        values.append(val)
                        idx += 1

                    if columns:
                        result = await conn.execute(f"""
                            UPDATE {self.config.nodes_table}
                            SET {", ".join(columns)}, updated_at = NOW()
                            WHERE id = $1
                        """, *values)
                        if "UPDATE 1" in result:
                            updated += 1

        return updated

    async def get_node_content(
        self,
        context_id: str,
        columns: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """
        直接讀取 node 的自訂欄位。

        Args:
            context_id: Node ID
            columns: Columns to fetch (default: all custom columns from config)

        Returns:
            Dict of column values, or None if node not found

        Example:
            data = await client.get_node_content(entity_id, ["content", "min_x", "max_x"])
            # Returns: {"content": "...", "min_x": 0, "max_x": 100}
        """
        cols = columns or list(self.config.custom_node_columns.keys())
        if not cols:
            return None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT {", ".join(cols)}
                FROM {self.config.nodes_table}
                WHERE id = $1
            """, context_id)

        return dict(row) if row else None

    async def get_nodes_content_batch(
        self,
        context_ids: list[str],
        columns: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        批量讀取多個 node 的自訂欄位。

        Args:
            context_ids: List of node IDs
            columns: Columns to fetch (default: all custom columns from config)

        Returns:
            Dict mapping node_id -> column values

        Example:
            data = await client.get_nodes_content_batch(
                [id1, id2, id3],
                ["content", "min_x", "max_x"]
            )
            # Returns: {id1: {...}, id2: {...}, id3: {...}}
        """
        if not context_ids:
            return {}

        cols = columns or list(self.config.custom_node_columns.keys())
        if not cols:
            return {}

        # Always include id for mapping
        select_cols = ["id"] + [c for c in cols if c != "id"]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT {", ".join(select_cols)}
                FROM {self.config.nodes_table}
                WHERE id = ANY($1)
            """, context_ids)

        result = {}
        for row in rows:
            row_dict = dict(row)
            node_id = row_dict.pop("id")
            result[node_id] = row_dict

        return result

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def cleanup_expired(self, current_turn: int | None = None) -> int:
        """
        Clean up expired data (time expired + turn expired).

        Args:
            current_turn: Current turn (for cleaning turn-expired data)

        Returns:
            Number of cleaned items
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("SELECT cleanup_expired($1)", current_turn)
            return result or 0

    async def _cleanup_loop(self) -> None:
        """Cleanup loop (only handles time expiration)."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                await self.cleanup_expired()  # Don't pass turn, only clean up time-expired
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Log error in production


# ============================================================
# Context Manager Helper
# ============================================================


class ExecutionContext:
    """
    Execution Context wrapper.

    Provides a friendlier API to operate on a single Context.

    Usage example:

        async with client.execution_context("task_123", parent="project_abc") as ctx:
            await ctx.set_local("thinking", ["Analyzing..."])
            await ctx.set_output("summary", "Completed")
            # Auto finalize and merge
    """

    def __init__(
        self,
        client: VersionaClient,
        context_id: str,
        parent_id: str | None = None,
        level: ContextLevel = ContextLevel.EXECUTION,
        auto_finalize: bool = True,
        auto_merge: bool = True,
    ):
        self.client = client
        self.context_id = context_id
        self.parent_id = parent_id
        self.level = level
        self.auto_finalize = auto_finalize
        self.auto_merge = auto_merge
        self._created = False

    async def __aenter__(self) -> "ExecutionContext":
        if self.parent_id:
            await self.client.fork(self.parent_id, self.context_id, self.level)
        else:
            await self.client.create_context(self.context_id, level=self.level)
        self._created = True
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            # Exception occurred, don't finalize
            return

        if self.auto_finalize:
            await self.client.finalize(self.context_id)

        if self.auto_merge and self.parent_id:
            await self.client.merge(self.context_id)

    async def set_local(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set local data."""
        await self.client.set_local(self.context_id, key, value, ttl)

    async def set_output(self, key: str, value: Any) -> None:
        """Set output data."""
        await self.client.set_output(self.context_id, key, value)

    async def get(self, key: str, default: Any = None) -> Any:
        """Get data."""
        return await self.client.get_value(self.context_id, key, default)

    async def append(self, key: str, value: Any) -> None:
        """Append to a list."""
        await self.client.append(self.context_id, key, value)

    async def commit(self, message: str | None = None) -> int:
        """Create a version."""
        return await self.client.commit(self.context_id, message)

    async def fork(self, new_id: str | None = None) -> "ExecutionContext":
        """Fork a child Context."""
        new_id = new_id or f"ctx_{uuid4().hex[:8]}"
        return ExecutionContext(
            self.client,
            new_id,
            self.context_id,
            ContextLevel.EXECUTION,
        )

    async def get_for_llm(self) -> dict[str, Any]:
        """Get data for LLM."""
        return await self.client.get_for_llm(self.context_id)


# Add execution_context method to VersionaClient
def _execution_context(
    self: VersionaClient,
    context_id: str,
    parent_id: str | None = None,
    level: ContextLevel = ContextLevel.EXECUTION,
    auto_finalize: bool = True,
    auto_merge: bool = True,
) -> ExecutionContext:
    """
    Create an execution Context.

    Args:
        context_id: Context ID
        parent_id: Parent Context ID
        level: Level
        auto_finalize: Whether to auto finalize
        auto_merge: Whether to auto merge to parent

    Returns:
        ExecutionContext wrapper
    """
    return ExecutionContext(
        self,
        context_id,
        parent_id,
        level,
        auto_finalize,
        auto_merge,
    )

VersionaClient.execution_context = _execution_context
