"""
Versiona PostgreSQL Schema - Table Definitions.

Core table structure definitions (customizable via VersionaConfig):
- {prefix}nodes: Horizontal tree structure
- {prefix}versions: Vertical version history
- {prefix}branches: Branch management
- {prefix}merges: Merge history
- {prefix}tags: Tags
- {prefix}kv: Key-Value fast query (supports dual-mode TTL)
- {prefix}snapshots: Snapshots (records all node version combinations at a point in time)

Customization:
- table_prefix: Change table names (e.g., "dxf_" -> dxf_nodes)
- custom_enums: Add custom ENUM types
- custom_node_columns: Add columns to nodes table
- custom_version_columns: Add columns to versions table
- custom_kv_columns: Add columns to kv table
- custom_indexes: Add custom indexes
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from versiona.context.types import VersionaConfig


# ============================================================
# Extensions SQL
# ============================================================

EXTENSIONS_SQL = """
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "ltree";
"""


# ============================================================
# Schema Builder (with customization support)
# ============================================================

class SchemaBuilder:
    """
    Builds SQL schema with customization support.

    Usage:
        from versiona.context.types import VersionaConfig

        config = VersionaConfig(
            table_prefix="dxf_",
            custom_enums={"entity_type": ["LINE", "CIRCLE", "ARC"]},
            custom_node_columns={"handle": "VARCHAR(20)"},
        )

        builder = SchemaBuilder(config)
        sql = builder.build()
    """

    def __init__(self, config: "VersionaConfig | None" = None):
        """
        Initialize schema builder.

        Args:
            config: Versiona configuration. If None, uses defaults.
        """
        if config is None:
            # Import here to avoid circular import
            from versiona.context.types import VersionaConfig
            config = VersionaConfig()
        self.config = config
        self.prefix = config.table_prefix

    def build(self) -> str:
        """Build complete schema SQL."""
        parts = [
            EXTENSIONS_SQL,
            self._build_enums(),
            self._build_nodes_table(),
            self._build_versions_table(),
            self._build_branches_table(),
            self._build_merges_table(),
            self._build_tags_table(),
            self._build_kv_table(),
            self._build_snapshots_table(),
            self._build_custom_indexes(),
        ]
        return "\n".join(parts)

    def _build_enums(self) -> str:
        """Build custom ENUM types."""
        if not self.config.custom_enums:
            return ""

        parts = ["-- Custom ENUM types"]
        for enum_name, values in self.config.custom_enums.items():
            values_str = ", ".join(f"'{v}'" for v in values)
            parts.append(f"""
DO $$ BEGIN
    CREATE TYPE {enum_name} AS ENUM ({values_str});
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
""")
        return "\n".join(parts)

    def _build_custom_columns(self, columns: dict[str, str]) -> str:
        """Build custom column definitions."""
        if not columns:
            return ""
        lines = []
        for col_name, col_type in columns.items():
            lines.append(f"    {col_name} {col_type},")
        return "\n" + "\n".join(lines)

    def _build_nodes_table(self) -> str:
        """Build nodes table."""
        table = f"{self.prefix}nodes"
        custom_cols = self._build_custom_columns(self.config.custom_node_columns)

        return f"""
-- ============================================================
-- {table} (Horizontal Tree Structure)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES {table}(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'L1',  -- L0=Project, L1=Task, L2=Execution
    path LTREE NOT NULL,               -- For efficient tree queries

    -- Metadata
    name TEXT,
    description TEXT,
    metadata JSONB DEFAULT '{{}}',

    -- Status
    status TEXT DEFAULT 'active',      -- active, archived, deleted
    current_version INT DEFAULT 0,
{custom_cols}
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}nodes_parent ON {table}(parent_id);
CREATE INDEX IF NOT EXISTS idx_{self.prefix}nodes_path ON {table} USING GIST (path);
CREATE INDEX IF NOT EXISTS idx_{self.prefix}nodes_level ON {table}(level);
"""

    def _build_versions_table(self) -> str:
        """Build versions table."""
        table = f"{self.prefix}versions"
        nodes_table = f"{self.prefix}nodes"
        custom_cols = self._build_custom_columns(self.config.custom_version_columns)

        # Build conditional data columns based on exclude_version_columns
        exclude = self.config.exclude_version_columns
        data_cols = []
        if "local_data" not in exclude:
            data_cols.append("    local_data JSONB DEFAULT '{}',     -- Local data (not inherited)")
        if "output_data" not in exclude:
            data_cols.append("    output_data JSONB DEFAULT '{}',    -- Output data (inheritable)")

        soft_delete_col = ""
        if "soft_deleted_keys" not in exclude:
            soft_delete_col = "\n    -- Soft delete flag\n    soft_deleted_keys TEXT[] DEFAULT '{}',"

        # Build data section
        data_section = ""
        if data_cols:
            data_section = "\n    -- Data\n" + "\n".join(data_cols)

        return f"""
-- ============================================================
-- {table} (Vertical Version History)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES {nodes_table}(id) ON DELETE CASCADE,
    version INT NOT NULL,
{data_section}
{soft_delete_col}
    -- Version info
    message TEXT,                      -- commit message
    author_id TEXT,

    -- Hash for integrity
    data_hash BYTEA,
{custom_cols}
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, version)
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}versions_node ON {table}(node_id, version DESC);
"""

    def _build_branches_table(self) -> str:
        """Build branches table."""
        table = f"{self.prefix}branches"
        nodes_table = f"{self.prefix}nodes"

        return f"""
-- ============================================================
-- {table} (Branch Management)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES {nodes_table}(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    head_version INT NOT NULL DEFAULT 0,

    -- Fork info
    forked_from_node TEXT REFERENCES {nodes_table}(id),
    forked_from_version INT,

    -- Metadata
    is_default BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{{}}',

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, name)
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}branches_node ON {table}(node_id);
"""

    def _build_merges_table(self) -> str:
        """Build merges table."""
        table = f"{self.prefix}merges"
        nodes_table = f"{self.prefix}nodes"

        return f"""
-- ============================================================
-- {table} (Merge History)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source
    source_node_id TEXT NOT NULL REFERENCES {nodes_table}(id),
    source_version INT NOT NULL,

    -- Target
    target_node_id TEXT NOT NULL REFERENCES {nodes_table}(id),
    target_version_before INT NOT NULL,
    target_version_after INT NOT NULL,

    -- Merge info
    merge_type TEXT DEFAULT 'output_only',  -- output_only, full, selective
    merged_keys TEXT[],
    conflict_resolution JSONB,

    -- Metadata
    message TEXT,
    author_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}merges_target ON {table}(target_node_id);
"""

    def _build_tags_table(self) -> str:
        """Build tags table."""
        table = f"{self.prefix}tags"
        nodes_table = f"{self.prefix}nodes"

        return f"""
-- ============================================================
-- {table} (Tags)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES {nodes_table}(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version INT NOT NULL,
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, name)
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}tags_node ON {table}(node_id);
"""

    def _build_kv_table(self) -> str:
        """Build kv table."""
        table = f"{self.prefix}kv"
        nodes_table = f"{self.prefix}nodes"
        custom_cols = self._build_custom_columns(self.config.custom_kv_columns)

        return f"""
-- ============================================================
-- {table} (Key-Value Store with Dual-Mode TTL)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    node_id TEXT NOT NULL REFERENCES {nodes_table}(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value JSONB,

    -- Metadata
    category TEXT DEFAULT 'local',     -- local, output
    is_soft_deleted BOOLEAN DEFAULT false,

    -- Dual-mode TTL
    -- Time TTL: Real-time info (weather, stock prices, API responses)
    ttl_seconds INT,
    expires_at TIMESTAMPTZ,

    -- Turn TTL: Process data in Agent loop (tool_calls, tool_results)
    ttl_turns INT,                     -- Expires after N turns
    created_at_turn INT,               -- Turn when created
    expires_at_turn INT,               -- Expires when reaching this turn

    -- Version tracking
    version INT NOT NULL,
{custom_cols}
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (node_id, key)
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}kv_node ON {table}(node_id);
CREATE INDEX IF NOT EXISTS idx_{self.prefix}kv_expires ON {table}(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_{self.prefix}kv_turn_expires ON {table}(node_id, expires_at_turn) WHERE expires_at_turn IS NOT NULL;
"""

    def _build_snapshots_table(self) -> str:
        """Build snapshots table."""
        table = f"{self.prefix}snapshots"
        nodes_table = f"{self.prefix}nodes"

        return f"""
-- ============================================================
-- {table} (Version Snapshots)
-- ============================================================
CREATE TABLE IF NOT EXISTS {table} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Root node of the snapshot
    root_node_id TEXT NOT NULL REFERENCES {nodes_table}(id) ON DELETE CASCADE,

    -- Snapshot info
    name TEXT,
    message TEXT,
    snapshot_type TEXT DEFAULT 'manual',  -- auto, manual, before_agent, checkpoint

    -- Version mapping: Records the version of each child node at this snapshot
    node_versions JSONB NOT NULL,
    -- {{ "node_id_1": 3, "node_id_2": 5, ... }}

    -- Metadata
    metadata JSONB DEFAULT '{{}}',

    -- Association
    author_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_{self.prefix}snapshots_root ON {table}(root_node_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_{self.prefix}snapshots_type ON {table}(snapshot_type);
"""

    def _build_custom_indexes(self) -> str:
        """Build custom indexes."""
        if not self.config.custom_indexes:
            return ""

        parts = ["-- Custom indexes"]
        for table_suffix, column_expr, index_type in self.config.custom_indexes:
            table = f"{self.prefix}{table_suffix}"
            # Sanitize column name for index name
            col_safe = column_expr.replace("(", "_").replace(")", "_").replace(",", "_").replace(" ", "")
            index_name = f"idx_{self.prefix}{table_suffix}_{col_safe}"

            if index_type.upper() == "GIN":
                parts.append(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} USING GIN ({column_expr});")
            elif index_type.upper() == "GIST":
                parts.append(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} USING GIST ({column_expr});")
            else:
                parts.append(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column_expr});")

        return "\n".join(parts)


# ============================================================
# Legacy API (backward compatible)
# ============================================================

# Default table definitions (using default prefix "context_")
_default_builder = None


def _get_default_builder() -> SchemaBuilder:
    """Get default schema builder (lazy init)."""
    global _default_builder
    if _default_builder is None:
        _default_builder = SchemaBuilder()
    return _default_builder


def get_tables_sql(config: "VersionaConfig | None" = None) -> str:
    """
    Get SQL for all tables.

    Args:
        config: Optional configuration for customization.
                If None, uses default "context_" prefix.

    Returns:
        SQL string to create all tables.
    """
    if config is not None:
        return SchemaBuilder(config).build()
    return _get_default_builder().build()


def get_table_names(prefix: str = "context_") -> list[str]:
    """
    Get all table names with given prefix.

    Args:
        prefix: Table prefix (default: "context_")

    Returns:
        List of table names.
    """
    return [
        f"{prefix}nodes",
        f"{prefix}versions",
        f"{prefix}branches",
        f"{prefix}merges",
        f"{prefix}tags",
        f"{prefix}kv",
        f"{prefix}snapshots",
    ]
