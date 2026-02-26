"""
Versiona Compression Extension - SQL Schema

Provides automatic compression queue and trigger.
"""

from __future__ import annotations


def get_compression_schema_sql(
    kv_table: str = "agent_kv",
    nodes_table: str = "agent_nodes",
    size_threshold: int = 100000,  # 100KB default
    token_threshold: int | None = None,  # Optional token-based threshold
) -> str:
    """
    Get the Compression extension schema SQL.

    Args:
        kv_table: Name of the KV table to monitor
        nodes_table: Name of the nodes table (for current_turn)
        size_threshold: Size threshold in bytes to trigger compression
        token_threshold: Optional token threshold (requires token_count column)

    Returns:
        SQL string to create queue table, trigger, and functions
    """
    # Build the threshold condition
    if token_threshold:
        threshold_condition = f"""
            (total_size > {size_threshold} OR
             (total_tokens IS NOT NULL AND total_tokens > {token_threshold}))
        """
        priority_calc = f"""
            CASE
                WHEN total_tokens IS NOT NULL AND total_tokens > {token_threshold * 2} THEN 20
                WHEN total_size > {size_threshold * 2} THEN 10
                WHEN total_tokens IS NOT NULL AND total_tokens > {token_threshold} THEN 5
                ELSE 1
            END
        """
    else:
        threshold_condition = f"total_size > {size_threshold}"
        priority_calc = f"""
            CASE
                WHEN total_size > {size_threshold * 2} THEN 10
                ELSE 1
            END
        """

    return f"""
-- ============================================================
-- Versiona Compression Extension
-- ============================================================

-- Compression Queue Table
CREATE TABLE IF NOT EXISTS compression_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id TEXT NOT NULL UNIQUE,  -- References {nodes_table}
    total_size BIGINT NOT NULL,
    total_tokens INT,              -- Optional, if token counting enabled
    priority INT DEFAULT 0,        -- Higher = more urgent
    status TEXT DEFAULT 'pending', -- pending, processing, completed, failed
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_compression_queue_status
    ON compression_queue(status, priority DESC)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_compression_queue_node
    ON compression_queue(node_id);

-- ============================================================
-- Trigger Function: Check context size after KV operations
-- ============================================================

CREATE OR REPLACE FUNCTION check_context_size_trigger()
RETURNS TRIGGER AS $$
DECLARE
    total_size BIGINT;
    total_tokens INT;
    calc_priority INT;
BEGIN
    -- Only check on INSERT or UPDATE (not DELETE)
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    -- Calculate total size for this node (excluding expired and deleted)
    SELECT
        COALESCE(SUM(pg_column_size(value)), 0),
        COALESCE(SUM(token_count), 0)
    INTO total_size, total_tokens
    FROM {kv_table}
    WHERE node_id = NEW.node_id
      AND is_soft_deleted = FALSE
      AND (expires_at IS NULL OR expires_at > NOW());

    -- Check if compression is needed
    IF {threshold_condition} THEN
        -- Calculate priority
        calc_priority := {priority_calc};

        -- Insert or update queue
        INSERT INTO compression_queue (
            node_id, total_size, total_tokens, priority
        )
        VALUES (
            NEW.node_id, total_size, total_tokens, calc_priority
        )
        ON CONFLICT (node_id)
        DO UPDATE SET
            total_size = EXCLUDED.total_size,
            total_tokens = EXCLUDED.total_tokens,
            priority = GREATEST(compression_queue.priority, EXCLUDED.priority),
            status = CASE
                WHEN compression_queue.status = 'completed' THEN 'pending'
                ELSE compression_queue.status
            END,
            created_at = CASE
                WHEN compression_queue.status = 'completed' THEN now()
                ELSE compression_queue.created_at
            END;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on KV table
DROP TRIGGER IF EXISTS trigger_context_size_check ON {kv_table};
CREATE TRIGGER trigger_context_size_check
    AFTER INSERT OR UPDATE ON {kv_table}
    FOR EACH ROW
    EXECUTE FUNCTION check_context_size_trigger();

-- ============================================================
-- Helper Functions
-- ============================================================

-- Get pending compression items
CREATE OR REPLACE FUNCTION get_pending_compressions(p_limit INT DEFAULT 10)
RETURNS TABLE (
    id UUID,
    node_id TEXT,
    total_size BIGINT,
    total_tokens INT,
    priority INT,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.id,
        q.node_id,
        q.total_size,
        q.total_tokens,
        q.priority,
        q.created_at
    FROM compression_queue q
    WHERE q.status = 'pending'
    ORDER BY q.priority DESC, q.created_at ASC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Mark compression as processing
CREATE OR REPLACE FUNCTION mark_compression_processing(p_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    affected INT;
BEGIN
    UPDATE compression_queue
    SET status = 'processing',
        started_at = now()
    WHERE id = p_id AND status = 'pending';

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected > 0;
END;
$$ LANGUAGE plpgsql;

-- Mark compression as completed
CREATE OR REPLACE FUNCTION mark_compression_completed(p_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE compression_queue
    SET status = 'completed',
        completed_at = now()
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Mark compression as failed
CREATE OR REPLACE FUNCTION mark_compression_failed(p_id UUID, p_error TEXT)
RETURNS VOID AS $$
BEGIN
    UPDATE compression_queue
    SET status = 'failed',
        error_message = p_error,
        completed_at = now()
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Reset stale processing items (for crash recovery)
CREATE OR REPLACE FUNCTION reset_stale_compressions(p_stale_minutes INT DEFAULT 30)
RETURNS INT AS $$
DECLARE
    affected INT;
BEGIN
    UPDATE compression_queue
    SET status = 'pending',
        started_at = NULL
    WHERE status = 'processing'
      AND started_at < now() - (p_stale_minutes || ' minutes')::INTERVAL;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$ LANGUAGE plpgsql;

-- Cleanup old completed/failed items
CREATE OR REPLACE FUNCTION cleanup_compression_queue(p_days INT DEFAULT 7)
RETURNS INT AS $$
DECLARE
    affected INT;
BEGIN
    DELETE FROM compression_queue
    WHERE status IN ('completed', 'failed')
      AND completed_at < now() - (p_days || ' days')::INTERVAL;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$ LANGUAGE plpgsql;
"""


def get_token_column_sql(kv_table: str = "agent_kv") -> str:
    """
    Get SQL to add token_count column to KV table.

    This is optional - only needed if you want token-based thresholds.

    Args:
        kv_table: Name of the KV table

    Returns:
        SQL string to add token_count column
    """
    return f"""
-- Add token_count column to KV table (optional)
ALTER TABLE {kv_table}
ADD COLUMN IF NOT EXISTS token_count INT;

CREATE INDEX IF NOT EXISTS idx_{kv_table}_tokens
    ON {kv_table}(node_id, token_count)
    WHERE token_count IS NOT NULL;
"""


def get_compression_table_names() -> list[str]:
    """Get all table names for the Compression extension."""
    return ["compression_queue"]
