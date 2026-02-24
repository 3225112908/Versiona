"""
Versiona PostgreSQL Schema - Table Definitions.

Core table structure definitions:
- context_nodes: Horizontal tree structure
- context_versions: Vertical version history
- context_branches: Branch management
- context_merges: Merge history
- context_tags: Tags
- context_kv: Key-Value fast query (supports dual-mode TTL)
- context_snapshots: Snapshots (records all node version combinations at a point in time)
"""

from __future__ import annotations

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
# Context Nodes Table
# ============================================================

CONTEXT_NODES_SQL = """
-- ============================================================
-- Context Nodes (Horizontal Tree Structure)
-- ============================================================
CREATE TABLE IF NOT EXISTS context_nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES context_nodes(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'L1',  -- L0=Project, L1=Task, L2=Execution
    path LTREE NOT NULL,               -- For efficient tree queries

    -- Metadata
    name TEXT,
    description TEXT,
    metadata JSONB DEFAULT '{}',

    -- Status
    status TEXT DEFAULT 'active',      -- active, archived, deleted
    current_version INT DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_context_nodes_parent ON context_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_context_nodes_path ON context_nodes USING GIST (path);
CREATE INDEX IF NOT EXISTS idx_context_nodes_level ON context_nodes(level);
"""


# ============================================================
# Context Versions Table
# ============================================================

CONTEXT_VERSIONS_SQL = """
-- ============================================================
-- Context Versions (Vertical Version History)
-- ============================================================
CREATE TABLE IF NOT EXISTS context_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    version INT NOT NULL,

    -- Data
    local_data JSONB DEFAULT '{}',     -- Local data (not inherited)
    output_data JSONB DEFAULT '{}',    -- Output data (inheritable)

    -- Soft delete flag
    soft_deleted_keys TEXT[] DEFAULT '{}',

    -- Version info
    message TEXT,                      -- commit message
    author_id TEXT,

    -- Hash for integrity
    data_hash BYTEA,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, version)
);

CREATE INDEX IF NOT EXISTS idx_context_versions_node ON context_versions(node_id, version DESC);
"""


# ============================================================
# Context Branches Table
# ============================================================

CONTEXT_BRANCHES_SQL = """
-- ============================================================
-- Branches (Branch Management)
-- ============================================================
CREATE TABLE IF NOT EXISTS context_branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    head_version INT NOT NULL DEFAULT 0,

    -- Fork info
    forked_from_node TEXT REFERENCES context_nodes(id),
    forked_from_version INT,

    -- Metadata
    is_default BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, name)
);

CREATE INDEX IF NOT EXISTS idx_context_branches_node ON context_branches(node_id);
"""


# ============================================================
# Context Merges Table
# ============================================================

CONTEXT_MERGES_SQL = """
-- ============================================================
-- Merge History
-- ============================================================
CREATE TABLE IF NOT EXISTS context_merges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source
    source_node_id TEXT NOT NULL REFERENCES context_nodes(id),
    source_version INT NOT NULL,

    -- Target
    target_node_id TEXT NOT NULL REFERENCES context_nodes(id),
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

CREATE INDEX IF NOT EXISTS idx_context_merges_target ON context_merges(target_node_id);
"""


# ============================================================
# Context Tags Table
# ============================================================

CONTEXT_TAGS_SQL = """
-- ============================================================
-- Tags
-- ============================================================
CREATE TABLE IF NOT EXISTS context_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version INT NOT NULL,
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(node_id, name)
);

CREATE INDEX IF NOT EXISTS idx_context_tags_node ON context_tags(node_id);
"""


# ============================================================
# Context KV Table (with Dual-Mode TTL)
# ============================================================

CONTEXT_KV_SQL = """
-- ============================================================
-- Key-Value Store (Fast Query)
-- ============================================================
CREATE TABLE IF NOT EXISTS context_kv (
    node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,
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

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (node_id, key)
);

CREATE INDEX IF NOT EXISTS idx_context_kv_node ON context_kv(node_id);
CREATE INDEX IF NOT EXISTS idx_context_kv_expires ON context_kv(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_context_kv_turn_expires ON context_kv(node_id, expires_at_turn) WHERE expires_at_turn IS NOT NULL;
"""


# ============================================================
# Context Snapshots Table
# ============================================================

CONTEXT_SNAPSHOTS_SQL = """
-- ============================================================
-- Snapshots (Records version combinations of all nodes at a point in time)
-- ============================================================
--
-- Use cases:
--   - Full restore (e.g., state before Agent editing)
--   - Save points (manual saves)
--   - Version combination records
--
CREATE TABLE IF NOT EXISTS context_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Root node of the snapshot
    root_node_id TEXT NOT NULL REFERENCES context_nodes(id) ON DELETE CASCADE,

    -- Snapshot info
    name TEXT,
    message TEXT,
    snapshot_type TEXT DEFAULT 'manual',  -- auto, manual, before_agent, checkpoint

    -- Version mapping: Records the version of each child node at this snapshot
    node_versions JSONB NOT NULL,
    -- { "node_id_1": 3, "node_id_2": 5, ... }

    -- Metadata
    metadata JSONB DEFAULT '{}',

    -- Association
    author_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_context_snapshots_root ON context_snapshots(root_node_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_context_snapshots_type ON context_snapshots(snapshot_type);
"""


# ============================================================
# Helper Functions
# ============================================================

def get_tables_sql() -> str:
    """Get SQL for all tables."""
    return "\n".join([
        EXTENSIONS_SQL,
        CONTEXT_NODES_SQL,
        CONTEXT_VERSIONS_SQL,
        CONTEXT_BRANCHES_SQL,
        CONTEXT_MERGES_SQL,
        CONTEXT_TAGS_SQL,
        CONTEXT_KV_SQL,
        CONTEXT_SNAPSHOTS_SQL,
    ])


def get_table_names() -> list[str]:
    """Get all table names."""
    return [
        "context_nodes",
        "context_versions",
        "context_branches",
        "context_merges",
        "context_tags",
        "context_kv",
        "context_snapshots",
    ]
