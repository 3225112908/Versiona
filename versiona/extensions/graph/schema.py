"""
Versiona Graph Extension - SQL Schema definitions.

This module contains the table definitions for the Graph extension.
Schema is modular and can be installed independently of the core Versiona schema.
"""

from __future__ import annotations


# ============================================================
# Core Tables Schema
# ============================================================

GRAPH_TABLES_SQL = """
-- ============================================================
-- Versiona Graph Extension - Core Tables
-- Prefix: vg_ (versiona graph)
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- -----------------------------------------------------
-- Symbol Type Registry
-- Users can register custom symbol types
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_symbol_types (
    name TEXT PRIMARY KEY,
    description TEXT,

    -- Default settings for this type
    default_ttl_seconds INT,
    auto_index BOOLEAN DEFAULT true,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Insert default symbol types (generic types only, domain-specific types should be added by users)
INSERT INTO vg_symbol_types (name, description) VALUES
    ('generic', 'Generic symbol'),
    ('file', 'File'),
    ('function', 'Function or method'),
    ('class', 'Class'),
    ('variable', 'Variable'),
    ('module', 'Module'),
    ('config', 'Configuration'),
    ('document', 'Document or text')
ON CONFLICT (name) DO NOTHING;


-- -----------------------------------------------------
-- Edge Type Registry
-- Users can register custom edge types
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_edge_types (
    name TEXT PRIMARY KEY,
    description TEXT,

    -- Edge characteristics
    is_directional BOOLEAN DEFAULT true,
    auto_create BOOLEAN DEFAULT false,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Insert default edge types
INSERT INTO vg_edge_types (name, description, is_directional, auto_create) VALUES
    ('contains', 'Parent contains child', true, true),
    ('references', 'A references B', true, true),
    ('depends_on', 'A depends on B', true, false),
    ('related_to', 'Generic relation', false, false),
    ('similar_to', 'Similarity relation', false, false),
    ('derived_from', 'A is derived from B', true, false),
    ('co_modified', 'Often modified together', false, false),
    ('co_accessed', 'Often accessed together', false, false),
    ('custom', 'User-defined', true, false)
ON CONFLICT (name) DO NOTHING;


-- -----------------------------------------------------
-- Symbol Index
-- Main table for storing symbols
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_symbol_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context association
    -- This can be context_nodes.id or any custom namespace
    context_id TEXT NOT NULL,

    -- Symbol identification
    symbol_type TEXT NOT NULL REFERENCES vg_symbol_types(name),
    symbol_key TEXT NOT NULL,           -- Unique identifier (path, qualified name, etc.)
    symbol_name TEXT,                   -- Display name

    -- Content (plain text for search)
    content TEXT,                       -- Full content or summary
    content_hash TEXT,                  -- For dedup and change detection

    -- Statistics (for smart selection)
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    modification_count INT DEFAULT 0,
    last_modified_at TIMESTAMPTZ,

    -- Extensible properties (scenario-specific)
    properties JSONB DEFAULT '{}',
    -- Examples:
    -- {"language": "python", "line_start": 10, "line_end": 50}
    -- {"bbox": {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 100}}

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Unique constraint
    UNIQUE(context_id, symbol_type, symbol_key)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vg_symbols_context ON vg_symbol_index(context_id);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_type ON vg_symbol_index(symbol_type);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_key ON vg_symbol_index(symbol_key);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_name_trgm ON vg_symbol_index USING gin(symbol_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_content_trgm ON vg_symbol_index USING gin(content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_access ON vg_symbol_index(last_accessed_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_modified ON vg_symbol_index(last_modified_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_vg_symbols_properties ON vg_symbol_index USING gin(properties);


-- -----------------------------------------------------
-- Symbol Edges
-- Relationships between symbols
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_symbol_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Connected symbols
    source_id UUID NOT NULL REFERENCES vg_symbol_index(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES vg_symbol_index(id) ON DELETE CASCADE,

    -- Edge type
    edge_type TEXT NOT NULL REFERENCES vg_edge_types(name),

    -- Weight (for ranking, PageRank, etc.)
    weight FLOAT DEFAULT 1.0,

    -- Source (who created this edge)
    created_by TEXT DEFAULT 'auto',     -- 'auto', 'user', 'llm', 'rule:{name}'
    confidence FLOAT DEFAULT 1.0,       -- LLM edges can have confidence

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Prevent duplicates
    UNIQUE(source_id, target_id, edge_type)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vg_edges_source ON vg_symbol_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_vg_edges_target ON vg_symbol_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_vg_edges_type ON vg_symbol_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_vg_edges_created_by ON vg_symbol_edges(created_by);


-- -----------------------------------------------------
-- Context Views
-- Cached context views for LLM consumption
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_context_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Association
    context_id TEXT NOT NULL,

    -- View content
    view_name TEXT NOT NULL,            -- 'summary', 'detail', 'focused', custom
    view_content TEXT NOT NULL,         -- Plain text for LLM

    -- Generation info
    token_estimate INT,
    included_symbols UUID[],
    generation_params JSONB,            -- Parameters used to generate

    -- Cache control
    cache_key TEXT,                     -- For cache hits
    expires_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(context_id, view_name, cache_key)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vg_views_context ON vg_context_views(context_id);
CREATE INDEX IF NOT EXISTS idx_vg_views_cache ON vg_context_views(cache_key);
CREATE INDEX IF NOT EXISTS idx_vg_views_expires ON vg_context_views(expires_at)
    WHERE expires_at IS NOT NULL;
"""


# ============================================================
# Feedback Tables Schema (Optional)
# ============================================================

GRAPH_FEEDBACK_TABLES_SQL = """
-- ============================================================
-- Versiona Graph Extension - Feedback Tables (Optional)
-- For LLM-assisted graph corrections
-- ============================================================

-- -----------------------------------------------------
-- LLM Feedback
-- Store feedback from LLM for graph corrections
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS vg_llm_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Association
    context_id TEXT NOT NULL,
    symbol_id UUID REFERENCES vg_symbol_index(id) ON DELETE SET NULL,
    edge_id UUID REFERENCES vg_symbol_edges(id) ON DELETE SET NULL,

    -- Feedback type
    feedback_type TEXT NOT NULL,
    -- 'missing_edge': Should have an edge but doesn't
    -- 'wrong_edge': Edge exists but is incorrect
    -- 'missing_symbol': Symbol should exist but doesn't
    -- 'wrong_content': Symbol content is incorrect
    -- 'suggestion': General suggestion

    -- Feedback content
    feedback_content JSONB NOT NULL,
    -- Example: {"edge_type": "references", "target_key": "xxx", "reason": "..."}

    -- Processing status
    status TEXT DEFAULT 'pending',      -- 'pending', 'applied', 'rejected', 'expired'
    processed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vg_feedback_context ON vg_llm_feedback(context_id);
CREATE INDEX IF NOT EXISTS idx_vg_feedback_status ON vg_llm_feedback(status);
CREATE INDEX IF NOT EXISTS idx_vg_feedback_type ON vg_llm_feedback(feedback_type);
"""


# ============================================================
# Helper Functions
# ============================================================

def get_graph_schema_sql(include_feedback: bool = False) -> str:
    """
    Get the complete Graph extension schema SQL.

    Args:
        include_feedback: Include LLM feedback tables (default: False)

    Returns:
        SQL string to create all tables
    """
    sql = GRAPH_TABLES_SQL
    if include_feedback:
        sql += "\n" + GRAPH_FEEDBACK_TABLES_SQL
    return sql


def get_graph_table_names(include_feedback: bool = False) -> list[str]:
    """Get all table names for the Graph extension."""
    tables = [
        "vg_symbol_types",
        "vg_edge_types",
        "vg_symbol_index",
        "vg_symbol_edges",
        "vg_context_views",
    ]
    if include_feedback:
        tables.append("vg_llm_feedback")
    return tables
