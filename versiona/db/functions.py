"""
Versiona PostgreSQL Schema - SQL Functions.

Core function definitions:
- create_context_node: Create Context node
- fork_context: Fork child Context
- fork_session: Fork Session (copy KV up to a specific turn)
- commit_context: Create new version
- get_context: Get Context data
- merge_context: Merge Context
- diff_versions: Compare versions
- kv_* series: Key-Value operations (supports dual-mode TTL)
- snapshot_* series: Snapshot operations
"""

from __future__ import annotations


# ============================================================
# Node Functions
# ============================================================

NODE_FUNCTIONS_SQL = """
-- Create Context Node
CREATE OR REPLACE FUNCTION create_context_node(
    p_id TEXT,
    p_parent_id TEXT DEFAULT NULL,
    p_level TEXT DEFAULT 'L1',
    p_name TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS TEXT AS $$
DECLARE
    v_path LTREE;
    v_parent_path LTREE;
BEGIN
    -- Calculate path
    IF p_parent_id IS NULL THEN
        v_path := p_id::LTREE;
    ELSE
        SELECT path INTO v_parent_path FROM context_nodes WHERE id = p_parent_id;
        IF v_parent_path IS NULL THEN
            RAISE EXCEPTION 'Parent node not found: %', p_parent_id;
        END IF;
        v_path := v_parent_path || p_id::LTREE;
    END IF;

    -- Insert node
    INSERT INTO context_nodes (id, parent_id, level, path, name, metadata)
    VALUES (p_id, p_parent_id, p_level, v_path, p_name, p_metadata);

    -- Create initial version
    INSERT INTO context_versions (node_id, version, message)
    VALUES (p_id, 1, 'Initial version');

    -- Update current_version
    UPDATE context_nodes SET current_version = 1 WHERE id = p_id;

    -- Create default branch
    INSERT INTO context_branches (node_id, name, head_version, is_default)
    VALUES (p_id, 'main', 1, true);

    RETURN p_id;
END;
$$ LANGUAGE plpgsql;

-- Fork Context (Horizontal Branching)
CREATE OR REPLACE FUNCTION fork_context(
    p_source_id TEXT,
    p_new_id TEXT,
    p_level TEXT DEFAULT NULL,
    p_inherit_output BOOLEAN DEFAULT true
) RETURNS TEXT AS $$
DECLARE
    v_source_node context_nodes%ROWTYPE;
    v_source_version context_versions%ROWTYPE;
    v_new_path LTREE;
    v_new_level TEXT;
BEGIN
    -- Get source node
    SELECT * INTO v_source_node FROM context_nodes WHERE id = p_source_id;
    IF v_source_node IS NULL THEN
        RAISE EXCEPTION 'Source node not found: %', p_source_id;
    END IF;

    -- Get source node current version
    SELECT * INTO v_source_version
    FROM context_versions
    WHERE node_id = p_source_id AND version = v_source_node.current_version;

    -- Calculate new path (as child of source node)
    v_new_path := v_source_node.path || p_new_id::LTREE;

    -- Determine level
    v_new_level := COALESCE(p_level,
        CASE v_source_node.level
            WHEN 'L0' THEN 'L1'
            WHEN 'L1' THEN 'L2'
            ELSE 'L2'
        END
    );

    -- Create new node
    INSERT INTO context_nodes (id, parent_id, level, path, name, metadata, current_version)
    VALUES (p_new_id, p_source_id, v_new_level, v_new_path,
            'Fork of ' || p_source_id,
            jsonb_build_object('forked_from', p_source_id, 'forked_version', v_source_node.current_version),
            1);

    -- Create initial version
    INSERT INTO context_versions (node_id, version, output_data, message)
    VALUES (
        p_new_id,
        1,
        CASE WHEN p_inherit_output THEN v_source_version.output_data ELSE '{}' END,
        'Forked from ' || p_source_id || ':v' || v_source_node.current_version
    );

    -- Create default branch
    INSERT INTO context_branches (node_id, name, head_version, is_default, forked_from_node, forked_from_version)
    VALUES (p_new_id, 'main', 1, true, p_source_id, v_source_node.current_version);

    RETURN p_new_id;
END;
$$ LANGUAGE plpgsql;

-- Get child node list
CREATE OR REPLACE FUNCTION get_children(
    p_node_id TEXT,
    p_level TEXT DEFAULT NULL,
    p_include_nested BOOLEAN DEFAULT false
) RETURNS JSONB AS $$
DECLARE
    v_node context_nodes%ROWTYPE;
    v_result JSONB;
BEGIN
    SELECT * INTO v_node FROM context_nodes WHERE id = p_node_id;
    IF v_node IS NULL THEN
        RETURN '[]';
    END IF;

    IF p_include_nested THEN
        -- Get all descendants
        SELECT jsonb_agg(jsonb_build_object(
            'id', n.id,
            'parent_id', n.parent_id,
            'level', n.level,
            'name', n.name,
            'status', n.status,
            'current_version', n.current_version,
            'created_at', n.created_at
        ))
        INTO v_result
        FROM context_nodes n
        WHERE n.path <@ v_node.path AND n.id != p_node_id
        AND (p_level IS NULL OR n.level = p_level);
    ELSE
        -- Get direct children only
        SELECT jsonb_agg(jsonb_build_object(
            'id', n.id,
            'parent_id', n.parent_id,
            'level', n.level,
            'name', n.name,
            'status', n.status,
            'current_version', n.current_version,
            'created_at', n.created_at
        ))
        INTO v_result
        FROM context_nodes n
        WHERE n.parent_id = p_node_id
        AND (p_level IS NULL OR n.level = p_level);
    END IF;

    RETURN COALESCE(v_result, '[]');
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Version Functions
# ============================================================

VERSION_FUNCTIONS_SQL = """
-- Commit (Create new version)
CREATE OR REPLACE FUNCTION commit_context(
    p_node_id TEXT,
    p_local_data JSONB DEFAULT NULL,
    p_output_data JSONB DEFAULT NULL,
    p_soft_deleted_keys TEXT[] DEFAULT NULL,
    p_message TEXT DEFAULT NULL,
    p_author_id TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_current_version INT;
    v_new_version INT;
    v_prev_version context_versions%ROWTYPE;
    v_new_local JSONB;
    v_new_output JSONB;
    v_new_soft_deleted TEXT[];
BEGIN
    -- Get current version
    SELECT current_version INTO v_current_version FROM context_nodes WHERE id = p_node_id;
    IF v_current_version IS NULL THEN
        RAISE EXCEPTION 'Node not found: %', p_node_id;
    END IF;

    -- Get previous version data
    SELECT * INTO v_prev_version FROM context_versions
    WHERE node_id = p_node_id AND version = v_current_version;

    -- Merge data
    v_new_local := COALESCE(v_prev_version.local_data, '{}') || COALESCE(p_local_data, '{}');
    v_new_output := COALESCE(v_prev_version.output_data, '{}') || COALESCE(p_output_data, '{}');
    v_new_soft_deleted := COALESCE(p_soft_deleted_keys, v_prev_version.soft_deleted_keys);

    -- Create new version
    v_new_version := v_current_version + 1;

    INSERT INTO context_versions (
        node_id, version, local_data, output_data, soft_deleted_keys, message, author_id
    ) VALUES (
        p_node_id, v_new_version, v_new_local, v_new_output, v_new_soft_deleted, p_message, p_author_id
    );

    -- Update node's current_version
    UPDATE context_nodes
    SET current_version = v_new_version, updated_at = now()
    WHERE id = p_node_id;

    -- Update default branch head
    UPDATE context_branches
    SET head_version = v_new_version, updated_at = now()
    WHERE node_id = p_node_id AND is_default = true;

    RETURN v_new_version;
END;
$$ LANGUAGE plpgsql;

-- Get Context (Get context data with inheritance support)
CREATE OR REPLACE FUNCTION get_context(
    p_node_id TEXT,
    p_version INT DEFAULT NULL,
    p_include_inherited BOOLEAN DEFAULT true,
    p_exclude_soft_deleted BOOLEAN DEFAULT true
) RETURNS JSONB AS $$
DECLARE
    v_node context_nodes%ROWTYPE;
    v_version context_versions%ROWTYPE;
    v_result JSONB := '{}';
    v_inherited JSONB := '{}';
    v_parent_id TEXT;
BEGIN
    -- Get node
    SELECT * INTO v_node FROM context_nodes WHERE id = p_node_id;
    IF v_node IS NULL THEN
        RETURN NULL;
    END IF;

    -- Get specified version or current version
    SELECT * INTO v_version FROM context_versions
    WHERE node_id = p_node_id AND version = COALESCE(p_version, v_node.current_version);

    IF v_version IS NULL THEN
        RETURN NULL;
    END IF;

    -- Build result
    v_result := jsonb_build_object(
        'node_id', v_node.id,
        'version', v_version.version,
        'level', v_node.level,
        'local_data', v_version.local_data,
        'output_data', v_version.output_data,
        'soft_deleted_keys', v_version.soft_deleted_keys
    );

    -- If inheritance of parent's output is needed
    IF p_include_inherited AND v_node.parent_id IS NOT NULL THEN
        v_inherited := get_inherited_output(v_node.parent_id);
        v_result := v_result || jsonb_build_object('inherited', v_inherited);
    END IF;

    -- If excluding soft deleted
    IF p_exclude_soft_deleted AND v_version.soft_deleted_keys IS NOT NULL AND array_length(v_version.soft_deleted_keys, 1) > 0 THEN
        -- Remove soft deleted keys from local_data
        FOR i IN 1..array_length(v_version.soft_deleted_keys, 1) LOOP
            v_result := v_result #- ARRAY['local_data', v_version.soft_deleted_keys[i]];
        END LOOP;
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Get inherited output (recursive upward)
CREATE OR REPLACE FUNCTION get_inherited_output(
    p_node_id TEXT
) RETURNS JSONB AS $$
DECLARE
    v_result JSONB := '{}';
    v_node context_nodes%ROWTYPE;
    v_version context_versions%ROWTYPE;
BEGIN
    SELECT * INTO v_node FROM context_nodes WHERE id = p_node_id;
    IF v_node IS NULL THEN
        RETURN '{}';
    END IF;

    -- First get parent's inherited data (recursive)
    IF v_node.parent_id IS NOT NULL THEN
        v_result := get_inherited_output(v_node.parent_id);
    END IF;

    -- Then merge current node's output
    SELECT * INTO v_version FROM context_versions
    WHERE node_id = p_node_id AND version = v_node.current_version;

    IF v_version IS NOT NULL THEN
        v_result := v_result || COALESCE(v_version.output_data, '{}');
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Diff (Compare two versions)
CREATE OR REPLACE FUNCTION diff_versions(
    p_node_id TEXT,
    p_version_a INT,
    p_version_b INT
) RETURNS JSONB AS $$
DECLARE
    v_version_a context_versions%ROWTYPE;
    v_version_b context_versions%ROWTYPE;
    v_diff JSONB := '{}';
    v_key TEXT;
    v_val_a JSONB;
    v_val_b JSONB;
    v_added JSONB := '{}';
    v_removed JSONB := '{}';
    v_modified JSONB := '{}';
BEGIN
    SELECT * INTO v_version_a FROM context_versions WHERE node_id = p_node_id AND version = p_version_a;
    SELECT * INTO v_version_b FROM context_versions WHERE node_id = p_node_id AND version = p_version_b;

    IF v_version_a IS NULL OR v_version_b IS NULL THEN
        RAISE EXCEPTION 'Version not found';
    END IF;

    -- Compare local_data
    FOR v_key IN SELECT jsonb_object_keys(v_version_b.local_data) LOOP
        v_val_a := v_version_a.local_data -> v_key;
        v_val_b := v_version_b.local_data -> v_key;

        IF v_val_a IS NULL THEN
            v_added := v_added || jsonb_build_object(v_key, v_val_b);
        ELSIF v_val_a != v_val_b THEN
            v_modified := v_modified || jsonb_build_object(v_key, jsonb_build_object('old', v_val_a, 'new', v_val_b));
        END IF;
    END LOOP;

    FOR v_key IN SELECT jsonb_object_keys(v_version_a.local_data) LOOP
        IF NOT v_version_b.local_data ? v_key THEN
            v_removed := v_removed || jsonb_build_object(v_key, v_version_a.local_data -> v_key);
        END IF;
    END LOOP;

    -- Same processing for output_data
    FOR v_key IN SELECT jsonb_object_keys(v_version_b.output_data) LOOP
        v_val_a := v_version_a.output_data -> v_key;
        v_val_b := v_version_b.output_data -> v_key;

        IF v_val_a IS NULL THEN
            v_added := v_added || jsonb_build_object(v_key, v_val_b);
        ELSIF v_val_a != v_val_b THEN
            v_modified := v_modified || jsonb_build_object(v_key, jsonb_build_object('old', v_val_a, 'new', v_val_b));
        END IF;
    END LOOP;

    FOR v_key IN SELECT jsonb_object_keys(v_version_a.output_data) LOOP
        IF NOT v_version_b.output_data ? v_key THEN
            v_removed := v_removed || jsonb_build_object(v_key, v_version_a.output_data -> v_key);
        END IF;
    END LOOP;

    v_diff := jsonb_build_object(
        'node_id', p_node_id,
        'from_version', p_version_a,
        'to_version', p_version_b,
        'added', v_added,
        'removed', v_removed,
        'modified', v_modified
    );

    RETURN v_diff;
END;
$$ LANGUAGE plpgsql;

-- Checkout (Switch to specified version)
CREATE OR REPLACE FUNCTION checkout_version(
    p_node_id TEXT,
    p_version INT,
    p_create_new_version BOOLEAN DEFAULT true
) RETURNS INT AS $$
DECLARE
    v_target_version context_versions%ROWTYPE;
    v_current_version INT;
    v_new_version INT;
BEGIN
    SELECT * INTO v_target_version FROM context_versions
    WHERE node_id = p_node_id AND version = p_version;

    IF v_target_version IS NULL THEN
        RAISE EXCEPTION 'Version not found: %:%', p_node_id, p_version;
    END IF;

    IF p_create_new_version THEN
        -- Get current version number
        SELECT current_version INTO v_current_version FROM context_nodes WHERE id = p_node_id;
        v_new_version := v_current_version + 1;

        -- Create new version (fully copy target version data, not merge)
        INSERT INTO context_versions (
            node_id, version, local_data, output_data, soft_deleted_keys, message, author_id
        ) VALUES (
            p_node_id,
            v_new_version,
            v_target_version.local_data,
            v_target_version.output_data,
            v_target_version.soft_deleted_keys,
            'Checkout from v' || p_version,
            NULL
        );

        -- Update node's current_version
        UPDATE context_nodes
        SET current_version = v_new_version, updated_at = now()
        WHERE id = p_node_id;

        -- Update default branch head
        UPDATE context_branches
        SET head_version = v_new_version, updated_at = now()
        WHERE node_id = p_node_id AND is_default = true;

        RETURN v_new_version;
    ELSE
        -- Directly update current_version (dangerous operation, will lose reference to subsequent versions)
        UPDATE context_nodes SET current_version = p_version, updated_at = now() WHERE id = p_node_id;
        RETURN p_version;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Get version history
CREATE OR REPLACE FUNCTION get_version_history(
    p_node_id TEXT,
    p_limit INT DEFAULT 50,
    p_offset INT DEFAULT 0
) RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_agg(jsonb_build_object(
        'version', v.version,
        'message', v.message,
        'author_id', v.author_id,
        'created_at', v.created_at,
        'local_keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(v.local_data) k),
        'output_keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(v.output_data) k),
        'soft_deleted_keys', v.soft_deleted_keys
    ) ORDER BY v.version DESC)
    INTO v_result
    FROM context_versions v
    WHERE v.node_id = p_node_id
    LIMIT p_limit OFFSET p_offset;

    RETURN COALESCE(v_result, '[]');
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Merge Functions
# ============================================================

MERGE_FUNCTIONS_SQL = """
-- Merge Context (Merge child node to parent node)
CREATE OR REPLACE FUNCTION merge_context(
    p_source_id TEXT,
    p_target_id TEXT DEFAULT NULL,  -- NULL = merge to parent
    p_merge_type TEXT DEFAULT 'output_only',  -- output_only, full
    p_message TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_source_node context_nodes%ROWTYPE;
    v_source_version context_versions%ROWTYPE;
    v_target_id TEXT;
    v_target_version_before INT;
    v_target_version_after INT;
    v_merge_data JSONB;
BEGIN
    -- Get source node
    SELECT * INTO v_source_node FROM context_nodes WHERE id = p_source_id;
    IF v_source_node IS NULL THEN
        RAISE EXCEPTION 'Source node not found: %', p_source_id;
    END IF;

    -- Determine target
    v_target_id := COALESCE(p_target_id, v_source_node.parent_id);
    IF v_target_id IS NULL THEN
        RAISE EXCEPTION 'No target specified and source has no parent';
    END IF;

    -- Get source version
    SELECT * INTO v_source_version FROM context_versions
    WHERE node_id = p_source_id AND version = v_source_node.current_version;

    -- Get target current version
    SELECT current_version INTO v_target_version_before FROM context_nodes WHERE id = v_target_id;

    -- Decide what to merge based on merge_type
    IF p_merge_type = 'output_only' THEN
        v_merge_data := v_source_version.output_data;
    ELSE
        v_merge_data := v_source_version.local_data || v_source_version.output_data;
    END IF;

    -- Execute commit to target
    v_target_version_after := commit_context(
        v_target_id,
        NULL,  -- local_data
        v_merge_data,  -- output_data
        NULL,  -- soft_deleted_keys
        COALESCE(p_message, 'Merge from ' || p_source_id),
        NULL
    );

    -- Record merge history
    INSERT INTO context_merges (
        source_node_id, source_version,
        target_node_id, target_version_before, target_version_after,
        merge_type, message
    ) VALUES (
        p_source_id, v_source_node.current_version,
        v_target_id, v_target_version_before, v_target_version_after,
        p_merge_type, p_message
    );

    RETURN v_target_version_after;
END;
$$ LANGUAGE plpgsql;


-- Fork Session (For Agent: fork from a specific turn, copy KV)
-- This differs from fork_context:
--   - fork_context: Creates child node, inherits output_data
--   - fork_session: Creates root node, copies KV up to a specific turn
CREATE OR REPLACE FUNCTION fork_session(
    p_source_id TEXT,
    p_new_id TEXT,
    p_fork_at_turn INT,
    p_name TEXT DEFAULT NULL,
    p_copy_kv BOOLEAN DEFAULT true
) RETURNS TEXT AS $$
DECLARE
    v_source_node context_nodes%ROWTYPE;
BEGIN
    -- Get source node
    SELECT * INTO v_source_node FROM context_nodes WHERE id = p_source_id;
    IF v_source_node IS NULL THEN
        RAISE EXCEPTION 'Source session not found: %', p_source_id;
    END IF;

    -- Create new root node (not a child node)
    INSERT INTO context_nodes (id, parent_id, level, path, name, metadata, current_version)
    VALUES (
        p_new_id,
        NULL,  -- Root node, no parent
        v_source_node.level,
        p_new_id::LTREE,
        COALESCE(p_name, 'Fork from ' || p_source_id || ' at turn ' || p_fork_at_turn),
        jsonb_build_object(
            'forked_from_session', p_source_id,
            'forked_at_turn', p_fork_at_turn
        ),
        1
    );

    -- Create initial version
    INSERT INTO context_versions (node_id, version, message)
    VALUES (p_new_id, 1, 'Forked from ' || p_source_id || ' at turn ' || p_fork_at_turn);

    -- Create default branch
    INSERT INTO context_branches (node_id, name, head_version, is_default)
    VALUES (p_new_id, 'main', 1, true);

    -- Copy KV (up to fork_at_turn, and not expired)
    IF p_copy_kv THEN
        INSERT INTO context_kv (
            node_id, key, value, category, version,
            ttl_seconds, expires_at, ttl_turns, created_at_turn, expires_at_turn
        )
        SELECT
            p_new_id, key, value, category, 1,
            ttl_seconds, expires_at, ttl_turns, created_at_turn, expires_at_turn
        FROM context_kv
        WHERE node_id = p_source_id
        AND NOT is_soft_deleted
        AND (expires_at IS NULL OR expires_at > now())
        AND (expires_at_turn IS NULL OR expires_at_turn > p_fork_at_turn)
        AND (created_at_turn IS NULL OR created_at_turn <= p_fork_at_turn);
    END IF;

    RETURN p_new_id;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# KV Functions (with Dual-Mode TTL)
# ============================================================

KV_FUNCTIONS_SQL = """
-- Key-Value fast operations (supports dual-mode TTL)
CREATE OR REPLACE FUNCTION kv_set(
    p_node_id TEXT,
    p_key TEXT,
    p_value JSONB,
    p_category TEXT DEFAULT 'local',
    p_ttl_seconds INT DEFAULT NULL,
    p_ttl_turns INT DEFAULT NULL,
    p_current_turn INT DEFAULT NULL
) RETURNS VOID AS $$
DECLARE
    v_version INT;
    v_expires_at TIMESTAMPTZ;
    v_expires_at_turn INT;
BEGIN
    SELECT current_version INTO v_version FROM context_nodes WHERE id = p_node_id;
    IF v_version IS NULL THEN
        RAISE EXCEPTION 'Node not found: %', p_node_id;
    END IF;

    -- Time TTL
    IF p_ttl_seconds IS NOT NULL THEN
        v_expires_at := now() + (p_ttl_seconds || ' seconds')::INTERVAL;
    END IF;

    -- Turn TTL
    IF p_ttl_turns IS NOT NULL AND p_current_turn IS NOT NULL THEN
        v_expires_at_turn := p_current_turn + p_ttl_turns;
    END IF;

    INSERT INTO context_kv (
        node_id, key, value, category, version,
        ttl_seconds, expires_at,
        ttl_turns, created_at_turn, expires_at_turn
    )
    VALUES (
        p_node_id, p_key, p_value, p_category, v_version,
        p_ttl_seconds, v_expires_at,
        p_ttl_turns, p_current_turn, v_expires_at_turn
    )
    ON CONFLICT (node_id, key) DO UPDATE SET
        value = EXCLUDED.value,
        category = EXCLUDED.category,
        version = EXCLUDED.version,
        ttl_seconds = EXCLUDED.ttl_seconds,
        expires_at = EXCLUDED.expires_at,
        ttl_turns = EXCLUDED.ttl_turns,
        created_at_turn = EXCLUDED.created_at_turn,
        expires_at_turn = EXCLUDED.expires_at_turn,
        is_soft_deleted = false,
        updated_at = now();
END;
$$ LANGUAGE plpgsql;

-- Get KV (supports time and turn expiration check)
CREATE OR REPLACE FUNCTION kv_get(
    p_node_id TEXT,
    p_key TEXT,
    p_include_expired BOOLEAN DEFAULT false,
    p_current_turn INT DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_result context_kv%ROWTYPE;
BEGIN
    SELECT * INTO v_result FROM context_kv
    WHERE node_id = p_node_id AND key = p_key
    AND NOT is_soft_deleted
    AND (p_include_expired OR (
        -- Time not expired
        (expires_at IS NULL OR expires_at > now())
        AND
        -- Turn not expired
        (expires_at_turn IS NULL OR p_current_turn IS NULL OR expires_at_turn > p_current_turn)
    ));

    IF v_result IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN v_result.value;
END;
$$ LANGUAGE plpgsql;

-- Get all valid KV (supports dual-mode expiration check)
CREATE OR REPLACE FUNCTION kv_get_all(
    p_node_id TEXT,
    p_category TEXT DEFAULT NULL,
    p_current_turn INT DEFAULT NULL
) RETURNS TABLE (
    key TEXT,
    value JSONB,
    category TEXT,
    created_at_turn INT,
    expires_at_turn INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT kv.key, kv.value, kv.category, kv.created_at_turn, kv.expires_at_turn
    FROM context_kv kv
    WHERE kv.node_id = p_node_id
    AND NOT kv.is_soft_deleted
    AND (p_category IS NULL OR kv.category = p_category)
    AND (kv.expires_at IS NULL OR kv.expires_at > now())
    AND (kv.expires_at_turn IS NULL OR p_current_turn IS NULL OR kv.expires_at_turn > p_current_turn);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION kv_soft_delete(
    p_node_id TEXT,
    p_key TEXT
) RETURNS VOID AS $$
BEGIN
    UPDATE context_kv SET is_soft_deleted = true, updated_at = now()
    WHERE node_id = p_node_id AND key = p_key;
END;
$$ LANGUAGE plpgsql;

-- Soft delete turn-expired data
CREATE OR REPLACE FUNCTION kv_expire_by_turn(
    p_node_id TEXT,
    p_current_turn INT
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    UPDATE context_kv
    SET is_soft_deleted = true, updated_at = now()
    WHERE node_id = p_node_id
    AND expires_at_turn IS NOT NULL
    AND expires_at_turn <= p_current_turn
    AND NOT is_soft_deleted;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Clean up expired data (time + turn)
CREATE OR REPLACE FUNCTION cleanup_expired(
    p_current_turn INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_time_count INT := 0;
    v_turn_count INT := 0;
BEGIN
    -- Clean up time-expired
    DELETE FROM context_kv WHERE expires_at IS NOT NULL AND expires_at < now();
    GET DIAGNOSTICS v_time_count = ROW_COUNT;

    -- Clean up turn-expired (if current turn is provided)
    IF p_current_turn IS NOT NULL THEN
        DELETE FROM context_kv
        WHERE expires_at_turn IS NOT NULL AND expires_at_turn <= p_current_turn;
        GET DIAGNOSTICS v_turn_count = ROW_COUNT;
    END IF;

    RETURN v_time_count + v_turn_count;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Snapshot Functions
# ============================================================

SNAPSHOT_FUNCTIONS_SQL = """
-- Create snapshot (record version combinations of all child nodes at a point in time)
CREATE OR REPLACE FUNCTION create_snapshot(
    p_root_node_id TEXT,
    p_name TEXT DEFAULT NULL,
    p_snapshot_type TEXT DEFAULT 'manual',
    p_message TEXT DEFAULT NULL,
    p_author_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_snapshot_id UUID;
    v_root_path LTREE;
    v_node_versions JSONB;
BEGIN
    -- Get root node path
    SELECT path INTO v_root_path FROM context_nodes WHERE id = p_root_node_id;
    IF v_root_path IS NULL THEN
        RAISE EXCEPTION 'Root node not found: %', p_root_node_id;
    END IF;

    -- Collect current versions of all child nodes (including self)
    SELECT jsonb_object_agg(id, current_version)
    INTO v_node_versions
    FROM context_nodes
    WHERE path <@ v_root_path;

    -- Create snapshot
    INSERT INTO context_snapshots (
        root_node_id, name, message, snapshot_type,
        node_versions, metadata, author_id
    ) VALUES (
        p_root_node_id,
        COALESCE(p_name, 'Snapshot ' || to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
        p_message,
        p_snapshot_type,
        v_node_versions,
        p_metadata,
        p_author_id
    ) RETURNING id INTO v_snapshot_id;

    RETURN v_snapshot_id;
END;
$$ LANGUAGE plpgsql;

-- Restore snapshot (rollback all nodes to the version at snapshot time)
CREATE OR REPLACE FUNCTION restore_snapshot(
    p_snapshot_id UUID,
    p_author_id TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_snapshot context_snapshots%ROWTYPE;
    v_node_id TEXT;
    v_target_version INT;
    v_current_version INT;
    v_new_version INT;
    v_restored_count INT := 0;
    v_target_data context_versions%ROWTYPE;
BEGIN
    -- Get snapshot
    SELECT * INTO v_snapshot FROM context_snapshots WHERE id = p_snapshot_id;
    IF v_snapshot IS NULL THEN
        RAISE EXCEPTION 'Snapshot not found: %', p_snapshot_id;
    END IF;

    -- Iterate each node
    FOR v_node_id, v_target_version IN
        SELECT key, value::INT FROM jsonb_each_text(v_snapshot.node_versions)
    LOOP
        -- Get current version
        SELECT current_version INTO v_current_version FROM context_nodes WHERE id = v_node_id;

        -- Only rollback when versions differ
        IF v_current_version IS NOT NULL AND v_current_version != v_target_version THEN
            -- Get target version data
            SELECT * INTO v_target_data FROM context_versions
            WHERE node_id = v_node_id AND version = v_target_version;

            IF v_target_data.node_id IS NOT NULL THEN
                v_new_version := v_current_version + 1;

                -- Create new version (fully copy target version data, not merge)
                INSERT INTO context_versions (
                    node_id, version, local_data, output_data, soft_deleted_keys, message, author_id
                ) VALUES (
                    v_node_id,
                    v_new_version,
                    v_target_data.local_data,
                    v_target_data.output_data,
                    v_target_data.soft_deleted_keys,
                    'Restore from snapshot: ' || v_snapshot.name,
                    p_author_id
                );

                -- Update node's current_version
                UPDATE context_nodes
                SET current_version = v_new_version, updated_at = now()
                WHERE id = v_node_id;

                -- Update default branch head
                UPDATE context_branches
                SET head_version = v_new_version, updated_at = now()
                WHERE node_id = v_node_id AND is_default = true;

                v_restored_count := v_restored_count + 1;
            END IF;
        END IF;
    END LOOP;

    RETURN v_restored_count;
END;
$$ LANGUAGE plpgsql;

-- List snapshots
CREATE OR REPLACE FUNCTION list_snapshots(
    p_root_node_id TEXT,
    p_snapshot_type TEXT DEFAULT NULL,
    p_limit INT DEFAULT 50,
    p_offset INT DEFAULT 0
) RETURNS TABLE (
    id UUID,
    name TEXT,
    message TEXT,
    snapshot_type TEXT,
    node_count INT,
    created_at TIMESTAMPTZ,
    author_id TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.name,
        s.message,
        s.snapshot_type,
        (SELECT COUNT(*)::INT FROM jsonb_object_keys(s.node_versions)) AS node_count,
        s.created_at,
        s.author_id
    FROM context_snapshots s
    WHERE s.root_node_id = p_root_node_id
    AND (p_snapshot_type IS NULL OR s.snapshot_type = p_snapshot_type)
    ORDER BY s.created_at DESC
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Get snapshot details
CREATE OR REPLACE FUNCTION get_snapshot(
    p_snapshot_id UUID
) RETURNS JSONB AS $$
DECLARE
    v_snapshot context_snapshots%ROWTYPE;
BEGIN
    SELECT * INTO v_snapshot FROM context_snapshots WHERE id = p_snapshot_id;
    IF v_snapshot IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN jsonb_build_object(
        'id', v_snapshot.id,
        'root_node_id', v_snapshot.root_node_id,
        'name', v_snapshot.name,
        'message', v_snapshot.message,
        'snapshot_type', v_snapshot.snapshot_type,
        'node_versions', v_snapshot.node_versions,
        'metadata', v_snapshot.metadata,
        'author_id', v_snapshot.author_id,
        'created_at', v_snapshot.created_at
    );
END;
$$ LANGUAGE plpgsql;

-- Delete snapshot
CREATE OR REPLACE FUNCTION delete_snapshot(
    p_snapshot_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM context_snapshots WHERE id = p_snapshot_id;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted > 0;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Triggers
# ============================================================

TRIGGERS_SQL = """
-- ============================================================
-- Triggers
-- ============================================================

-- Auto update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_context_nodes_updated_at ON context_nodes;
CREATE TRIGGER tr_context_nodes_updated_at
    BEFORE UPDATE ON context_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS tr_context_branches_updated_at ON context_branches;
CREATE TRIGGER tr_context_branches_updated_at
    BEFORE UPDATE ON context_branches
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
"""


# ============================================================
# Batch Operations (Roadmap Feature)
# ============================================================

BATCH_FUNCTIONS_SQL = """
-- ============================================================
-- Batch Set KV
-- ============================================================
-- Efficiently set multiple key-value pairs in one transaction

CREATE OR REPLACE FUNCTION batch_kv_set(
    p_node_id TEXT,
    p_items JSONB,  -- [{"key": "...", "value": {...}, "category": "local", "ttl_seconds": null, "ttl_turns": null}, ...]
    p_current_turn INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_item JSONB;
    v_count INT := 0;
    v_version INT;
    v_expires_at TIMESTAMPTZ;
    v_expires_at_turn INT;
BEGIN
    SELECT current_version INTO v_version FROM context_nodes WHERE id = p_node_id;
    IF v_version IS NULL THEN
        RAISE EXCEPTION 'Node not found: %', p_node_id;
    END IF;

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        -- Calculate TTL
        v_expires_at := NULL;
        v_expires_at_turn := NULL;

        IF (v_item->>'ttl_seconds')::INT IS NOT NULL THEN
            v_expires_at := now() + ((v_item->>'ttl_seconds') || ' seconds')::INTERVAL;
        END IF;

        IF (v_item->>'ttl_turns')::INT IS NOT NULL AND p_current_turn IS NOT NULL THEN
            v_expires_at_turn := p_current_turn + (v_item->>'ttl_turns')::INT;
        END IF;

        INSERT INTO context_kv (
            node_id, key, value, category, version,
            ttl_seconds, expires_at, ttl_turns, created_at_turn, expires_at_turn
        )
        VALUES (
            p_node_id,
            v_item->>'key',
            v_item->'value',
            COALESCE(v_item->>'category', 'local'),
            v_version,
            (v_item->>'ttl_seconds')::INT,
            v_expires_at,
            (v_item->>'ttl_turns')::INT,
            p_current_turn,
            v_expires_at_turn
        )
        ON CONFLICT (node_id, key) DO UPDATE SET
            value = EXCLUDED.value,
            category = EXCLUDED.category,
            version = EXCLUDED.version,
            ttl_seconds = EXCLUDED.ttl_seconds,
            expires_at = EXCLUDED.expires_at,
            ttl_turns = EXCLUDED.ttl_turns,
            created_at_turn = EXCLUDED.created_at_turn,
            expires_at_turn = EXCLUDED.expires_at_turn,
            is_soft_deleted = false,
            updated_at = now();

        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Batch Commit (commit multiple nodes in one transaction)
-- ============================================================

CREATE OR REPLACE FUNCTION batch_commit(
    p_items JSONB,  -- [{"node_id": "...", "local_data": {...}, "output_data": {...}, "message": "..."}, ...]
    p_author_id TEXT DEFAULT NULL
) RETURNS TABLE (node_id TEXT, new_version INT) AS $$
DECLARE
    v_item JSONB;
    v_node_id TEXT;
    v_new_version INT;
BEGIN
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        v_node_id := v_item->>'node_id';

        -- Use existing commit_context function
        v_new_version := commit_context(
            v_node_id,
            v_item->'local_data',
            v_item->'output_data',
            NULL,  -- soft_deleted_keys
            v_item->>'message',
            p_author_id
        );

        node_id := v_node_id;
        new_version := v_new_version;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Batch Create Nodes
-- ============================================================

CREATE OR REPLACE FUNCTION batch_create_nodes(
    p_nodes JSONB  -- [{"id": "...", "parent_id": "...", "level": "L1", "name": "...", "metadata": {...}}, ...]
) RETURNS INT AS $$
DECLARE
    v_node JSONB;
    v_count INT := 0;
    v_parent_path LTREE;
    v_path LTREE;
BEGIN
    FOR v_node IN SELECT * FROM jsonb_array_elements(p_nodes)
    LOOP
        -- Calculate path
        IF v_node->>'parent_id' IS NOT NULL THEN
            SELECT path INTO v_parent_path FROM context_nodes WHERE id = v_node->>'parent_id';
            IF v_parent_path IS NULL THEN
                CONTINUE;  -- Skip if parent not found
            END IF;
            v_path := v_parent_path || (v_node->>'id')::ltree;
        ELSE
            v_path := (v_node->>'id')::ltree;
        END IF;

        INSERT INTO context_nodes (id, parent_id, level, path, name, metadata, current_version)
        VALUES (
            v_node->>'id',
            v_node->>'parent_id',
            COALESCE(v_node->>'level', 'L1'),
            v_path,
            v_node->>'name',
            COALESCE(v_node->'metadata', '{}'),
            0
        )
        ON CONFLICT (id) DO NOTHING;

        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Conflict Resolution (Roadmap Feature)
# ============================================================

CONFLICT_FUNCTIONS_SQL = """
-- ============================================================
-- Conflict Info Type
-- ============================================================

DO $$ BEGIN
    CREATE TYPE conflict_info AS (
        key TEXT,
        source_value JSONB,
        target_value JSONB,
        conflict_type TEXT  -- 'key_conflict', 'delete_conflict'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- ============================================================
-- Detect Conflicts Before Merge
-- ============================================================

CREATE OR REPLACE FUNCTION detect_merge_conflicts(
    p_source_id TEXT,
    p_target_id TEXT
) RETURNS SETOF conflict_info AS $$
DECLARE
    v_source_node context_nodes%ROWTYPE;
    v_target_node context_nodes%ROWTYPE;
    v_source_ver context_versions%ROWTYPE;
    v_target_ver context_versions%ROWTYPE;
    v_key TEXT;
    v_conflict conflict_info;
BEGIN
    SELECT * INTO v_source_node FROM context_nodes WHERE id = p_source_id;
    SELECT * INTO v_target_node FROM context_nodes WHERE id = p_target_id;

    IF v_source_node IS NULL OR v_target_node IS NULL THEN
        RETURN;
    END IF;

    SELECT * INTO v_source_ver FROM context_versions
        WHERE node_id = p_source_id AND version = v_source_node.current_version;
    SELECT * INTO v_target_ver FROM context_versions
        WHERE node_id = p_target_id AND version = v_target_node.current_version;

    -- Check output_data conflicts
    FOR v_key IN SELECT jsonb_object_keys(v_source_ver.output_data)
    LOOP
        IF v_target_ver.output_data ? v_key THEN
            IF v_source_ver.output_data->v_key IS DISTINCT FROM v_target_ver.output_data->v_key THEN
                v_conflict.key := v_key;
                v_conflict.source_value := v_source_ver.output_data->v_key;
                v_conflict.target_value := v_target_ver.output_data->v_key;
                v_conflict.conflict_type := 'key_conflict';
                RETURN NEXT v_conflict;
            END IF;
        END IF;
    END LOOP;

    -- Check soft delete conflicts
    IF v_source_ver.soft_deleted_keys IS NOT NULL THEN
        FOREACH v_key IN ARRAY v_source_ver.soft_deleted_keys
        LOOP
            IF v_target_ver.output_data ? v_key THEN
                v_conflict.key := v_key;
                v_conflict.source_value := NULL;
                v_conflict.target_value := v_target_ver.output_data->v_key;
                v_conflict.conflict_type := 'delete_conflict';
                RETURN NEXT v_conflict;
            END IF;
        END LOOP;
    END IF;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Merge with Conflict Resolution Strategy
-- ============================================================
-- Strategies:
--   'source_wins': Source overwrites target on conflict
--   'target_wins': Target keeps its value on conflict
--   'merge_deep': Deep merge objects (source keys added to target objects)
--   'manual': Use p_resolutions to specify per-key resolution

CREATE OR REPLACE FUNCTION merge_with_strategy(
    p_source_id TEXT,
    p_target_id TEXT,
    p_strategy TEXT DEFAULT 'source_wins',
    p_resolutions JSONB DEFAULT NULL,  -- {"key1": "source", "key2": "target", "key3": {...custom_value...}}
    p_message TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_source_node context_nodes%ROWTYPE;
    v_target_node context_nodes%ROWTYPE;
    v_source_ver context_versions%ROWTYPE;
    v_target_ver context_versions%ROWTYPE;
    v_merged_output JSONB;
    v_key TEXT;
    v_resolution TEXT;
    v_new_version INT;
BEGIN
    SELECT * INTO v_source_node FROM context_nodes WHERE id = p_source_id;
    SELECT * INTO v_target_node FROM context_nodes WHERE id = p_target_id;

    IF v_source_node IS NULL THEN
        RAISE EXCEPTION 'Source node not found: %', p_source_id;
    END IF;
    IF v_target_node IS NULL THEN
        RAISE EXCEPTION 'Target node not found: %', p_target_id;
    END IF;

    SELECT * INTO v_source_ver FROM context_versions
        WHERE node_id = p_source_id AND version = v_source_node.current_version;
    SELECT * INTO v_target_ver FROM context_versions
        WHERE node_id = p_target_id AND version = v_target_node.current_version;

    -- Start with target's output
    v_merged_output := COALESCE(v_target_ver.output_data, '{}');

    -- Merge source's output based on strategy
    FOR v_key IN SELECT jsonb_object_keys(v_source_ver.output_data)
    LOOP
        IF p_strategy = 'source_wins' THEN
            v_merged_output := v_merged_output || jsonb_build_object(v_key, v_source_ver.output_data->v_key);

        ELSIF p_strategy = 'target_wins' THEN
            IF NOT v_merged_output ? v_key THEN
                v_merged_output := v_merged_output || jsonb_build_object(v_key, v_source_ver.output_data->v_key);
            END IF;

        ELSIF p_strategy = 'merge_deep' THEN
            IF v_merged_output ? v_key
               AND jsonb_typeof(v_merged_output->v_key) = 'object'
               AND jsonb_typeof(v_source_ver.output_data->v_key) = 'object' THEN
                -- Deep merge objects
                v_merged_output := jsonb_set(
                    v_merged_output,
                    ARRAY[v_key],
                    v_merged_output->v_key || v_source_ver.output_data->v_key
                );
            ELSE
                v_merged_output := v_merged_output || jsonb_build_object(v_key, v_source_ver.output_data->v_key);
            END IF;

        ELSIF p_strategy = 'manual' AND p_resolutions IS NOT NULL THEN
            IF p_resolutions ? v_key THEN
                v_resolution := p_resolutions->>v_key;
                IF v_resolution = 'source' THEN
                    v_merged_output := v_merged_output || jsonb_build_object(v_key, v_source_ver.output_data->v_key);
                ELSIF v_resolution = 'target' THEN
                    NULL;  -- Keep target value (already in v_merged_output)
                ELSE
                    -- Custom value provided
                    v_merged_output := v_merged_output || jsonb_build_object(v_key, p_resolutions->v_key);
                END IF;
            ELSE
                -- No resolution specified, use source_wins as default
                v_merged_output := v_merged_output || jsonb_build_object(v_key, v_source_ver.output_data->v_key);
            END IF;
        END IF;
    END LOOP;

    -- Create new version with merged data
    v_new_version := commit_context(
        p_target_id,
        NULL,  -- local_data
        v_merged_output,
        NULL,  -- soft_deleted_keys
        COALESCE(p_message, 'Merged from ' || p_source_id || ' with strategy: ' || p_strategy),
        NULL
    );

    -- Record merge history
    INSERT INTO context_merges (
        source_node_id, source_version,
        target_node_id, target_version_before, target_version_after,
        merge_type, conflict_resolution, message
    ) VALUES (
        p_source_id, v_source_node.current_version,
        p_target_id, v_target_node.current_version, v_new_version,
        p_strategy,
        p_resolutions,
        p_message
    );

    RETURN v_new_version;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Auto Compression & Archiving (Roadmap Feature)
# ============================================================

COMPRESSION_FUNCTIONS_SQL = """
-- ============================================================
-- Archive Tables (created on first use)
-- ============================================================

CREATE TABLE IF NOT EXISTS context_nodes_archive (
    LIKE context_nodes INCLUDING ALL,
    archived_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS context_versions_archive (
    LIKE context_versions INCLUDING ALL,
    archived_at TIMESTAMPTZ DEFAULT now()
);


-- ============================================================
-- Compress Old Versions (keep every Nth version)
-- ============================================================
-- For long-lived contexts with many versions, compress by keeping only every Nth version

CREATE OR REPLACE FUNCTION compress_versions(
    p_node_id TEXT,
    p_keep_every INT DEFAULT 10,        -- Keep every 10th version
    p_keep_recent INT DEFAULT 5,        -- Always keep last 5 versions
    p_dry_run BOOLEAN DEFAULT TRUE      -- Preview only, don't delete
) RETURNS TABLE (
    version_num INT,
    created_at TIMESTAMPTZ,
    will_delete BOOLEAN
) AS $$
DECLARE
    v_node context_nodes%ROWTYPE;
    v_min_keep_version INT;
    v_deleted INT := 0;
BEGIN
    SELECT * INTO v_node FROM context_nodes WHERE id = p_node_id;
    IF v_node IS NULL THEN
        RAISE EXCEPTION 'Node not found: %', p_node_id;
    END IF;

    v_min_keep_version := GREATEST(1, v_node.current_version - p_keep_recent);

    RETURN QUERY
    SELECT
        v.version,
        v.created_at,
        (v.version < v_min_keep_version AND v.version % p_keep_every != 0) AS will_delete
    FROM context_versions v
    WHERE v.node_id = p_node_id
    ORDER BY v.version;

    IF NOT p_dry_run THEN
        DELETE FROM context_versions
        WHERE node_id = p_node_id
          AND version < v_min_keep_version
          AND version % p_keep_every != 0;
    END IF;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Archive Old Nodes (move to archive table)
-- ============================================================
-- Move old/archived nodes to archive tables to reduce main table size

CREATE OR REPLACE FUNCTION archive_old_nodes(
    p_older_than_days INT DEFAULT 90,
    p_status TEXT DEFAULT 'archived'
) RETURNS INT AS $$
DECLARE
    v_cutoff TIMESTAMPTZ;
    v_count INT := 0;
    v_node RECORD;
BEGIN
    v_cutoff := now() - (p_older_than_days || ' days')::INTERVAL;

    FOR v_node IN
        SELECT id FROM context_nodes
        WHERE status = p_status AND updated_at < v_cutoff
    LOOP
        -- Archive versions first
        INSERT INTO context_versions_archive
        SELECT *, now() FROM context_versions WHERE node_id = v_node.id;

        -- Archive node
        INSERT INTO context_nodes_archive
        SELECT *, now() FROM context_nodes WHERE id = v_node.id;

        -- Delete from main tables (cascades to versions, kv, branches)
        DELETE FROM context_nodes WHERE id = v_node.id;

        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Squash Versions (combine multiple versions into one)
-- ============================================================
-- Useful for cleaning up intermediate versions

CREATE OR REPLACE FUNCTION squash_versions(
    p_node_id TEXT,
    p_from_version INT,
    p_to_version INT,
    p_message TEXT DEFAULT 'Squashed versions'
) RETURNS INT AS $$
DECLARE
    v_node context_nodes%ROWTYPE;
    v_final_ver context_versions%ROWTYPE;
BEGIN
    SELECT * INTO v_node FROM context_nodes WHERE id = p_node_id;
    IF v_node IS NULL THEN
        RAISE EXCEPTION 'Node not found: %', p_node_id;
    END IF;

    IF p_to_version > v_node.current_version THEN
        RAISE EXCEPTION 'Cannot squash beyond current version %', v_node.current_version;
    END IF;

    IF p_from_version >= p_to_version THEN
        RAISE EXCEPTION 'from_version must be less than to_version';
    END IF;

    -- Get final state at p_to_version
    SELECT * INTO v_final_ver FROM context_versions
        WHERE node_id = p_node_id AND version = p_to_version;

    -- Delete versions in range (except to_version)
    DELETE FROM context_versions
    WHERE node_id = p_node_id
      AND version >= p_from_version
      AND version < p_to_version;

    -- Update the remaining version's message
    UPDATE context_versions
    SET message = p_message || ' (squashed v' || p_from_version || '-v' || p_to_version || ')'
    WHERE node_id = p_node_id AND version = p_to_version;

    RETURN p_to_version;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- Auto Maintenance Job (run periodically)
-- ============================================================
-- Combines cleanup, compression, and archiving

CREATE OR REPLACE FUNCTION run_maintenance(
    p_compress_keep_every INT DEFAULT 10,
    p_archive_older_than_days INT DEFAULT 90,
    p_current_turn INT DEFAULT NULL
) RETURNS TABLE (
    compressed_nodes INT,
    archived_nodes INT,
    expired_kv INT
) AS $$
DECLARE
    v_compressed INT := 0;
    v_archived INT;
    v_expired INT;
    v_node RECORD;
BEGIN
    -- Compress versions for nodes with > 50 versions
    FOR v_node IN
        SELECT node_id, COUNT(*) as ver_count
        FROM context_versions
        GROUP BY node_id
        HAVING COUNT(*) > 50
    LOOP
        PERFORM compress_versions(v_node.node_id, p_compress_keep_every, 5, FALSE);
        v_compressed := v_compressed + 1;
    END LOOP;

    -- Archive old nodes
    v_archived := archive_old_nodes(p_archive_older_than_days, 'archived');

    -- Cleanup expired KV
    v_expired := cleanup_expired(p_current_turn);

    compressed_nodes := v_compressed;
    archived_nodes := v_archived;
    expired_kv := v_expired;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Helper Functions
# ============================================================

def _apply_prefix(sql: str, prefix: str) -> str:
    """
    Apply table prefix to SQL by replacing 'context_' with the given prefix.

    This also updates function names to use the prefix.
    For example, if prefix is 'dxf_':
    - context_nodes -> dxf_nodes
    - create_context_node -> create_dxf_node
    - fork_context -> fork_dxf
    """
    if prefix == "context_":
        return sql

    # Replace table names
    result = sql.replace("context_nodes", f"{prefix}nodes")
    result = result.replace("context_versions", f"{prefix}versions")
    result = result.replace("context_branches", f"{prefix}branches")
    result = result.replace("context_merges", f"{prefix}merges")
    result = result.replace("context_tags", f"{prefix}tags")
    result = result.replace("context_kv", f"{prefix}kv")
    result = result.replace("context_snapshots", f"{prefix}snapshots")

    # Replace function names (be careful with order - longer matches first)
    result = result.replace("create_context_node", f"create_{prefix}node")
    result = result.replace("fork_context", f"fork_{prefix[:-1]}")  # Remove trailing _
    result = result.replace("fork_session", f"fork_{prefix}session")
    result = result.replace("commit_context", f"commit_{prefix[:-1]}")
    result = result.replace("get_context", f"get_{prefix[:-1]}")
    result = result.replace("merge_context", f"merge_{prefix[:-1]}")
    result = result.replace("diff_versions", f"{prefix}diff_versions")
    result = result.replace("checkout_version", f"{prefix}checkout_version")
    result = result.replace("get_version_history", f"{prefix}get_version_history")
    result = result.replace("get_inherited_output", f"{prefix}get_inherited_output")
    result = result.replace("get_children", f"{prefix}get_children")

    # KV functions
    result = result.replace("kv_set", f"{prefix}kv_set")
    result = result.replace("kv_get", f"{prefix}kv_get")
    result = result.replace("kv_get_all", f"{prefix}kv_get_all")
    result = result.replace("kv_soft_delete", f"{prefix}kv_soft_delete")
    result = result.replace("kv_expire_by_turn", f"{prefix}kv_expire_by_turn")
    result = result.replace("cleanup_expired", f"{prefix}cleanup_expired")

    # Snapshot functions
    result = result.replace("create_snapshot", f"{prefix}create_snapshot")
    result = result.replace("restore_snapshot", f"{prefix}restore_snapshot")
    result = result.replace("list_snapshots", f"{prefix}list_snapshots")
    result = result.replace("get_snapshot", f"{prefix}get_snapshot")
    result = result.replace("delete_snapshot", f"{prefix}delete_snapshot")

    # Batch functions
    result = result.replace("batch_kv_set", f"{prefix}batch_kv_set")
    result = result.replace("batch_commit", f"{prefix}batch_commit")
    result = result.replace("batch_create_nodes", f"{prefix}batch_create_nodes")

    # Conflict functions
    result = result.replace("detect_merge_conflicts", f"{prefix}detect_merge_conflicts")
    result = result.replace("merge_with_strategy", f"{prefix}merge_with_strategy")

    # Compression functions
    result = result.replace("compress_versions", f"{prefix}compress_versions")
    result = result.replace("archive_old_nodes", f"{prefix}archive_old_nodes")
    result = result.replace("squash_versions", f"{prefix}squash_versions")
    result = result.replace("run_maintenance", f"{prefix}run_maintenance")

    # Triggers
    result = result.replace("update_updated_at", f"{prefix}update_updated_at")
    result = result.replace("tr_context_", f"tr_{prefix}")

    return result


def get_functions_sql(prefix: str = "context_") -> str:
    """
    Get SQL for all functions.

    Args:
        prefix: Table/function prefix (default: "context_")

    Returns:
        SQL string with all functions using the specified prefix.
    """
    base_sql = "\n".join([
        NODE_FUNCTIONS_SQL,
        VERSION_FUNCTIONS_SQL,
        MERGE_FUNCTIONS_SQL,
        KV_FUNCTIONS_SQL,
        SNAPSHOT_FUNCTIONS_SQL,
        TRIGGERS_SQL,
        # Roadmap features
        BATCH_FUNCTIONS_SQL,
        CONFLICT_FUNCTIONS_SQL,
        COMPRESSION_FUNCTIONS_SQL,
    ])
    return _apply_prefix(base_sql, prefix)


def get_function_names(prefix: str = "context_") -> list[str]:
    """
    Get all function names with the specified prefix.

    Args:
        prefix: Function prefix (default: "context_")

    Returns:
        List of function names.
    """
    # Base function names (without prefix for simplicity)
    base_names = [
        # Node operations
        f"create_{prefix}node",
        f"fork_{prefix[:-1]}",  # fork_context -> fork_dxf
        f"fork_{prefix}session",
        f"{prefix}get_children",
        # Version operations
        f"commit_{prefix[:-1]}",
        f"get_{prefix[:-1]}",
        f"{prefix}get_inherited_output",
        f"{prefix}diff_versions",
        f"{prefix}checkout_version",
        f"{prefix}get_version_history",
        # Merge operations
        f"merge_{prefix[:-1]}",
        # KV operations (with dual-mode TTL)
        f"{prefix}kv_set",
        f"{prefix}kv_get",
        f"{prefix}kv_get_all",
        f"{prefix}kv_soft_delete",
        f"{prefix}kv_expire_by_turn",
        f"{prefix}cleanup_expired",
        # Snapshot operations
        f"{prefix}create_snapshot",
        f"{prefix}restore_snapshot",
        f"{prefix}list_snapshots",
        f"{prefix}get_snapshot",
        f"{prefix}delete_snapshot",
        # Triggers
        f"{prefix}update_updated_at",
        # Batch operations (Roadmap)
        f"{prefix}batch_kv_set",
        f"{prefix}batch_commit",
        f"{prefix}batch_create_nodes",
        # Conflict resolution (Roadmap)
        f"{prefix}detect_merge_conflicts",
        f"{prefix}merge_with_strategy",
        # Compression & archiving (Roadmap)
        f"{prefix}compress_versions",
        f"{prefix}archive_old_nodes",
        f"{prefix}squash_versions",
        f"{prefix}run_maintenance",
    ]

    return base_names
