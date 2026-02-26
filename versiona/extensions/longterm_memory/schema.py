"""
Versiona Longterm Memory Extension - SQL Schema

Provides persistent cross-session memory storage.
"""

from __future__ import annotations


LONGTERM_MEMORY_SCHEMA_SQL = """
-- ============================================================
-- Versiona Longterm Memory Extension
-- ============================================================

-- Memory Type ENUM
DO $$ BEGIN
    CREATE TYPE longterm_memory_type AS ENUM (
        'preference',   -- 用戶偏好
        'fact',         -- 學到的事實
        'pattern',      -- 行為模式
        'correction'    -- LLM 被糾正的錯誤
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Main Memory Table
CREATE TABLE IF NOT EXISTS longterm_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope (NULL = cross-project/cross-user)
    project_id UUID,
    user_id UUID,

    -- Classification
    memory_type longterm_memory_type NOT NULL,

    -- Content
    key TEXT NOT NULL,
    content JSONB NOT NULL,

    -- Source tracking
    source_session_id TEXT,       -- Which session this was learned from
    source_description TEXT,      -- Brief description of source

    -- Relevance scoring
    importance FLOAT DEFAULT 1.0, -- Higher = more important
    access_count INT DEFAULT 0,   -- How many times accessed
    last_accessed_at TIMESTAMPTZ, -- Last access time

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_longterm_memory_project
    ON longterm_memory(project_id)
    WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_longterm_memory_user
    ON longterm_memory(user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_longterm_memory_type
    ON longterm_memory(memory_type);

CREATE INDEX IF NOT EXISTS idx_longterm_memory_key
    ON longterm_memory(key);

CREATE INDEX IF NOT EXISTS idx_longterm_memory_importance
    ON longterm_memory(importance DESC);

CREATE INDEX IF NOT EXISTS idx_longterm_memory_access
    ON longterm_memory(last_accessed_at DESC NULLS LAST);

-- Unique constraint (handles NULL properly with COALESCE)
-- This ensures no duplicate key for the same scope
CREATE UNIQUE INDEX IF NOT EXISTS idx_longterm_memory_unique
    ON longterm_memory(
        COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::UUID),
        COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::UUID),
        memory_type,
        key
    );

-- Full-text search on content (optional, for keyword search)
CREATE INDEX IF NOT EXISTS idx_longterm_memory_content_gin
    ON longterm_memory USING GIN (content);

-- ============================================================
-- Helper Functions
-- ============================================================

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_longterm_memory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_longterm_memory_updated ON longterm_memory;
CREATE TRIGGER trigger_longterm_memory_updated
    BEFORE UPDATE ON longterm_memory
    FOR EACH ROW
    EXECUTE FUNCTION update_longterm_memory_timestamp();

-- Increment access count function
CREATE OR REPLACE FUNCTION increment_memory_access(p_memory_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE longterm_memory
    SET access_count = access_count + 1,
        last_accessed_at = now()
    WHERE id = p_memory_id;
END;
$$ LANGUAGE plpgsql;

-- Recall memories with relevance scoring
CREATE OR REPLACE FUNCTION recall_memories(
    p_project_id UUID DEFAULT NULL,
    p_user_id UUID DEFAULT NULL,
    p_memory_type longterm_memory_type DEFAULT NULL,
    p_limit INT DEFAULT 50
)
RETURNS TABLE (
    id UUID,
    project_id UUID,
    user_id UUID,
    memory_type longterm_memory_type,
    key TEXT,
    content JSONB,
    importance FLOAT,
    access_count INT,
    relevance_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.project_id,
        m.user_id,
        m.memory_type,
        m.key,
        m.content,
        m.importance,
        m.access_count,
        -- Relevance score: importance * scope_weight * recency_weight
        (m.importance *
         -- Scope weight: more specific = higher priority
         CASE
             WHEN m.project_id = p_project_id AND m.user_id = p_user_id THEN 4.0
             WHEN m.user_id = p_user_id AND m.project_id IS NULL THEN 3.0
             WHEN m.project_id = p_project_id AND m.user_id IS NULL THEN 2.0
             ELSE 1.0
         END *
         -- Recency weight: recently accessed = slightly higher
         CASE
             WHEN m.last_accessed_at > now() - INTERVAL '1 day' THEN 1.2
             WHEN m.last_accessed_at > now() - INTERVAL '7 days' THEN 1.1
             ELSE 1.0
         END
        )::FLOAT AS relevance_score
    FROM longterm_memory m
    WHERE
        -- Match scope (NULL means include global)
        (p_project_id IS NULL OR m.project_id IS NULL OR m.project_id = p_project_id)
        AND (p_user_id IS NULL OR m.user_id IS NULL OR m.user_id = p_user_id)
        -- Filter by type if specified
        AND (p_memory_type IS NULL OR m.memory_type = p_memory_type)
    ORDER BY relevance_score DESC, m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Upsert memory (insert or update)
CREATE OR REPLACE FUNCTION upsert_memory(
    p_project_id UUID,
    p_user_id UUID,
    p_memory_type longterm_memory_type,
    p_key TEXT,
    p_content JSONB,
    p_source_session_id TEXT DEFAULT NULL,
    p_source_description TEXT DEFAULT NULL,
    p_importance FLOAT DEFAULT 1.0
)
RETURNS UUID AS $$
DECLARE
    v_id UUID;
    v_project_coalesce UUID := COALESCE(p_project_id, '00000000-0000-0000-0000-000000000000'::UUID);
    v_user_coalesce UUID := COALESCE(p_user_id, '00000000-0000-0000-0000-000000000000'::UUID);
BEGIN
    -- Try to find existing
    SELECT id INTO v_id
    FROM longterm_memory
    WHERE COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::UUID) = v_project_coalesce
      AND COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::UUID) = v_user_coalesce
      AND memory_type = p_memory_type
      AND key = p_key;

    IF v_id IS NOT NULL THEN
        -- Update existing
        UPDATE longterm_memory
        SET content = p_content,
            source_session_id = COALESCE(p_source_session_id, source_session_id),
            source_description = COALESCE(p_source_description, source_description),
            importance = p_importance,
            updated_at = now()
        WHERE id = v_id;
    ELSE
        -- Insert new
        INSERT INTO longterm_memory (
            project_id, user_id, memory_type, key, content,
            source_session_id, source_description, importance
        )
        VALUES (
            p_project_id, p_user_id, p_memory_type, p_key, p_content,
            p_source_session_id, p_source_description, p_importance
        )
        RETURNING id INTO v_id;
    END IF;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;
"""


def get_longterm_memory_schema_sql() -> str:
    """
    Get the Longterm Memory extension schema SQL.

    Returns:
        SQL string to create all tables, indexes, and functions
    """
    return LONGTERM_MEMORY_SCHEMA_SQL


def get_longterm_memory_table_names() -> list[str]:
    """Get all table names for the Longterm Memory extension."""
    return ["longterm_memory"]
