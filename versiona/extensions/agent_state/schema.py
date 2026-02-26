"""
Versiona Agent State Extension - SQL Schema

State-driven agent execution state tracking.
"""

from __future__ import annotations


AGENT_STATE_SCHEMA_SQL = """
-- ============================================================
-- Versiona Agent State Extension
-- ============================================================
-- State-driven architecture for multi-system agent execution
-- This extension tracks which system/handler owns each session

-- Handler Status ENUM
DO $$ BEGIN
    CREATE TYPE agent_handler_status AS ENUM (
        'idle',           -- 閒置，等待輸入
        'pending',        -- 等待處理（剛被 handover）
        'executing',      -- 執行中
        'waiting_user',   -- 等待用戶回應
        'completed',      -- 完成
        'error'           -- 錯誤
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Main Agent State Table
CREATE TABLE IF NOT EXISTS agent_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 關聯到 Versiona context
    session_id TEXT NOT NULL UNIQUE,  -- = Versiona node_id

    -- Handler 資訊（誰在處理）
    current_handler VARCHAR(50) NOT NULL,
    -- "cad_system", "quote_system", "idle"

    handler_status agent_handler_status NOT NULL DEFAULT 'idle',

    -- 當前任務（fork 的 subagent）
    current_task VARCHAR(50),      -- "planning", "explore", "editor", "analysis"
    current_fork_id TEXT,          -- 正在執行的 fork 的 node_id

    -- Handover 資訊（跨 System）
    previous_handler VARCHAR(50),
    handover_reason TEXT,
    handover_at TIMESTAMPTZ,

    -- Handler 歷史
    handler_history JSONB DEFAULT '[]',
    -- [{"handler": "cad_system", "status": "completed", "at": "..."}]

    -- 時間戳
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Indexes
-- ============================================================

-- 快速查詢某 handler 的所有 pending sessions
CREATE INDEX IF NOT EXISTS idx_agent_state_handler
    ON agent_state(current_handler, handler_status);

-- 查詢特定狀態
CREATE INDEX IF NOT EXISTS idx_agent_state_status
    ON agent_state(handler_status);

-- 查詢 fork
CREATE INDEX IF NOT EXISTS idx_agent_state_fork
    ON agent_state(current_fork_id)
    WHERE current_fork_id IS NOT NULL;

-- ============================================================
-- Triggers
-- ============================================================

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_agent_state_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_agent_state_updated ON agent_state;
CREATE TRIGGER trigger_agent_state_updated
    BEFORE UPDATE ON agent_state
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_state_timestamp();

-- ============================================================
-- Helper Functions
-- ============================================================

-- Get or create agent state for a session
CREATE OR REPLACE FUNCTION get_or_create_agent_state(
    p_session_id TEXT,
    p_initial_handler VARCHAR(50) DEFAULT 'idle'
)
RETURNS agent_state AS $$
DECLARE
    v_state agent_state;
BEGIN
    -- Try to get existing
    SELECT * INTO v_state
    FROM agent_state
    WHERE session_id = p_session_id;

    IF v_state.id IS NOT NULL THEN
        RETURN v_state;
    END IF;

    -- Create new
    INSERT INTO agent_state (session_id, current_handler, handler_status)
    VALUES (p_session_id, p_initial_handler, 'idle')
    RETURNING * INTO v_state;

    RETURN v_state;
END;
$$ LANGUAGE plpgsql;

-- Start executing a task (fork subagent)
CREATE OR REPLACE FUNCTION start_agent_task(
    p_session_id TEXT,
    p_task VARCHAR(50),
    p_fork_id TEXT
)
RETURNS agent_state AS $$
DECLARE
    v_state agent_state;
BEGIN
    UPDATE agent_state
    SET handler_status = 'executing',
        current_task = p_task,
        current_fork_id = p_fork_id
    WHERE session_id = p_session_id
    RETURNING * INTO v_state;

    RETURN v_state;
END;
$$ LANGUAGE plpgsql;

-- Complete current task
CREATE OR REPLACE FUNCTION complete_agent_task(
    p_session_id TEXT,
    p_success BOOLEAN DEFAULT TRUE
)
RETURNS agent_state AS $$
DECLARE
    v_state agent_state;
    v_new_status agent_handler_status;
BEGIN
    v_new_status := CASE WHEN p_success THEN 'idle' ELSE 'error' END;

    UPDATE agent_state
    SET handler_status = v_new_status,
        current_task = NULL,
        current_fork_id = NULL
    WHERE session_id = p_session_id
    RETURNING * INTO v_state;

    RETURN v_state;
END;
$$ LANGUAGE plpgsql;

-- Handover to another system
CREATE OR REPLACE FUNCTION handover_agent(
    p_session_id TEXT,
    p_target_handler VARCHAR(50),
    p_reason TEXT DEFAULT NULL
)
RETURNS agent_state AS $$
DECLARE
    v_state agent_state;
    v_current_handler VARCHAR(50);
    v_history_entry JSONB;
BEGIN
    -- Get current handler
    SELECT current_handler INTO v_current_handler
    FROM agent_state
    WHERE session_id = p_session_id;

    -- Build history entry
    v_history_entry := jsonb_build_object(
        'handler', v_current_handler,
        'status', 'completed',
        'at', now()::TEXT,
        'reason', p_reason
    );

    -- Update state
    UPDATE agent_state
    SET previous_handler = current_handler,
        current_handler = p_target_handler,
        handler_status = 'pending',
        current_task = NULL,
        current_fork_id = NULL,
        handover_reason = p_reason,
        handover_at = now(),
        handler_history = handler_history || v_history_entry
    WHERE session_id = p_session_id
    RETURNING * INTO v_state;

    RETURN v_state;
END;
$$ LANGUAGE plpgsql;

-- Set handler status
CREATE OR REPLACE FUNCTION set_agent_status(
    p_session_id TEXT,
    p_status agent_handler_status
)
RETURNS agent_state AS $$
DECLARE
    v_state agent_state;
BEGIN
    UPDATE agent_state
    SET handler_status = p_status
    WHERE session_id = p_session_id
    RETURNING * INTO v_state;

    RETURN v_state;
END;
$$ LANGUAGE plpgsql;

-- Get sessions by handler and status
CREATE OR REPLACE FUNCTION get_sessions_by_handler(
    p_handler VARCHAR(50),
    p_status agent_handler_status DEFAULT NULL
)
RETURNS SETOF agent_state AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM agent_state
    WHERE current_handler = p_handler
      AND (p_status IS NULL OR handler_status = p_status)
    ORDER BY updated_at DESC;
END;
$$ LANGUAGE plpgsql;

-- Clean up completed/idle sessions older than X hours
CREATE OR REPLACE FUNCTION cleanup_old_agent_states(
    p_hours INT DEFAULT 24
)
RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    DELETE FROM agent_state
    WHERE handler_status IN ('completed', 'idle')
      AND updated_at < now() - (p_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
"""


def get_agent_state_schema_sql() -> str:
    """
    Get the Agent State extension schema SQL.

    Returns:
        SQL string to create all tables, indexes, and functions
    """
    return AGENT_STATE_SCHEMA_SQL


def get_agent_state_table_names() -> list[str]:
    """Get all table names for the Agent State extension."""
    return ["agent_state"]
