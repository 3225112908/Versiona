"""
Versiona Graph Extension - SQL Functions.

This module contains PL/pgSQL functions for the Graph extension.
Functions are designed to be executed in the database for performance.
"""

from __future__ import annotations


# ============================================================
# Core Functions SQL
# ============================================================

GRAPH_FUNCTIONS_SQL = """
-- ============================================================
-- Versiona Graph Extension - Core Functions
-- Prefix: vg_ (versiona graph)
-- ============================================================

-- -----------------------------------------------------
-- Symbol CRUD Functions
-- -----------------------------------------------------

-- Upsert a symbol
CREATE OR REPLACE FUNCTION vg_upsert_symbol(
    p_context_id TEXT,
    p_symbol_type TEXT,
    p_symbol_key TEXT,
    p_symbol_name TEXT DEFAULT NULL,
    p_content TEXT DEFAULT NULL,
    p_properties JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
    v_content_hash TEXT;
BEGIN
    -- Calculate content hash
    v_content_hash := encode(sha256(COALESCE(p_content, '')::bytea), 'hex');

    INSERT INTO vg_symbol_index (
        context_id, symbol_type, symbol_key, symbol_name,
        content, content_hash, properties
    ) VALUES (
        p_context_id, p_symbol_type, p_symbol_key, p_symbol_name,
        p_content, v_content_hash, p_properties
    )
    ON CONFLICT (context_id, symbol_type, symbol_key) DO UPDATE SET
        symbol_name = COALESCE(EXCLUDED.symbol_name, vg_symbol_index.symbol_name),
        content = COALESCE(EXCLUDED.content, vg_symbol_index.content),
        content_hash = EXCLUDED.content_hash,
        properties = vg_symbol_index.properties || EXCLUDED.properties,
        modification_count = vg_symbol_index.modification_count + 1,
        last_modified_at = now(),
        updated_at = now()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;


-- Bulk upsert symbols
CREATE OR REPLACE FUNCTION vg_bulk_upsert_symbols(
    p_symbols JSONB
    -- Format: [{"context_id": "...", "symbol_type": "...", "symbol_key": "...", ...}, ...]
) RETURNS INT AS $$
DECLARE
    v_count INT := 0;
    v_symbol JSONB;
BEGIN
    FOR v_symbol IN SELECT * FROM jsonb_array_elements(p_symbols)
    LOOP
        PERFORM vg_upsert_symbol(
            v_symbol->>'context_id',
            v_symbol->>'symbol_type',
            v_symbol->>'symbol_key',
            v_symbol->>'symbol_name',
            v_symbol->>'content',
            COALESCE(v_symbol->'properties', '{}')
        );
        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Record symbol access (for smart ranking)
CREATE OR REPLACE FUNCTION vg_touch_symbol(
    p_symbol_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE vg_symbol_index SET
        access_count = access_count + 1,
        last_accessed_at = now()
    WHERE id = p_symbol_id;
END;
$$ LANGUAGE plpgsql;


-- Batch touch symbols
CREATE OR REPLACE FUNCTION vg_touch_symbols(
    p_symbol_ids UUID[]
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    UPDATE vg_symbol_index SET
        access_count = access_count + 1,
        last_accessed_at = now()
    WHERE id = ANY(p_symbol_ids);

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Delete symbols by context
CREATE OR REPLACE FUNCTION vg_delete_symbols_by_context(
    p_context_id TEXT,
    p_symbol_type TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    IF p_symbol_type IS NOT NULL THEN
        DELETE FROM vg_symbol_index
        WHERE context_id = p_context_id AND symbol_type = p_symbol_type;
    ELSE
        DELETE FROM vg_symbol_index
        WHERE context_id = p_context_id;
    END IF;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Edge CRUD Functions
-- -----------------------------------------------------

-- Add or update an edge
CREATE OR REPLACE FUNCTION vg_add_edge(
    p_source_id UUID,
    p_target_id UUID,
    p_edge_type TEXT,
    p_weight FLOAT DEFAULT 1.0,
    p_created_by TEXT DEFAULT 'auto',
    p_confidence FLOAT DEFAULT 1.0,
    p_metadata JSONB DEFAULT '{}'
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO vg_symbol_edges (
        source_id, target_id, edge_type, weight, created_by, confidence, metadata
    ) VALUES (
        p_source_id, p_target_id, p_edge_type, p_weight, p_created_by, p_confidence, p_metadata
    )
    ON CONFLICT (source_id, target_id, edge_type) DO UPDATE SET
        weight = EXCLUDED.weight,
        confidence = EXCLUDED.confidence,
        metadata = vg_symbol_edges.metadata || EXCLUDED.metadata
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;


-- Add edge by symbol keys
CREATE OR REPLACE FUNCTION vg_add_edge_by_key(
    p_context_id TEXT,
    p_source_type TEXT,
    p_source_key TEXT,
    p_target_type TEXT,
    p_target_key TEXT,
    p_edge_type TEXT,
    p_weight FLOAT DEFAULT 1.0,
    p_created_by TEXT DEFAULT 'auto'
) RETURNS UUID AS $$
DECLARE
    v_source_id UUID;
    v_target_id UUID;
BEGIN
    SELECT id INTO v_source_id FROM vg_symbol_index
    WHERE context_id = p_context_id AND symbol_type = p_source_type AND symbol_key = p_source_key;

    SELECT id INTO v_target_id FROM vg_symbol_index
    WHERE context_id = p_context_id AND symbol_type = p_target_type AND symbol_key = p_target_key;

    IF v_source_id IS NULL OR v_target_id IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN vg_add_edge(v_source_id, v_target_id, p_edge_type, p_weight, p_created_by);
END;
$$ LANGUAGE plpgsql;


-- Increment edge weight (for co-access/co-modify tracking)
CREATE OR REPLACE FUNCTION vg_increment_edge_weight(
    p_source_id UUID,
    p_target_id UUID,
    p_edge_type TEXT,
    p_increment FLOAT DEFAULT 0.1
) RETURNS FLOAT AS $$
DECLARE
    v_new_weight FLOAT;
BEGIN
    UPDATE vg_symbol_edges SET
        weight = weight + p_increment
    WHERE source_id = p_source_id
      AND target_id = p_target_id
      AND edge_type = p_edge_type
    RETURNING weight INTO v_new_weight;

    RETURN v_new_weight;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Search Functions
-- -----------------------------------------------------

-- Search symbols
CREATE OR REPLACE FUNCTION vg_search_symbols(
    p_context_id TEXT,
    p_query TEXT DEFAULT NULL,
    p_symbol_types TEXT[] DEFAULT NULL,
    p_limit INT DEFAULT 50,
    p_order_by TEXT DEFAULT 'relevance'  -- 'relevance', 'recent', 'frequent', 'modified'
) RETURNS TABLE (
    id UUID,
    symbol_type TEXT,
    symbol_key TEXT,
    symbol_name TEXT,
    content TEXT,
    relevance_score FLOAT,
    properties JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.symbol_type,
        s.symbol_key,
        s.symbol_name,
        s.content,
        CASE
            WHEN p_query IS NULL THEN 1.0
            ELSE GREATEST(
                COALESCE(similarity(s.symbol_name, p_query), 0),
                COALESCE(similarity(s.symbol_key, p_query), 0),
                COALESCE(similarity(s.content, p_query), 0) * 0.5
            )
        END::FLOAT as relevance_score,
        s.properties
    FROM vg_symbol_index s
    WHERE s.context_id = p_context_id
      AND (p_symbol_types IS NULL OR s.symbol_type = ANY(p_symbol_types))
      AND (p_query IS NULL OR
           s.symbol_name ILIKE '%' || p_query || '%' OR
           s.symbol_key ILIKE '%' || p_query || '%' OR
           s.content ILIKE '%' || p_query || '%')
    ORDER BY
        CASE p_order_by
            WHEN 'recent' THEN EXTRACT(EPOCH FROM s.last_accessed_at)
            WHEN 'frequent' THEN s.access_count::FLOAT
            WHEN 'modified' THEN EXTRACT(EPOCH FROM s.last_modified_at)
            ELSE CASE
                WHEN p_query IS NULL THEN 1.0
                ELSE GREATEST(
                    COALESCE(similarity(s.symbol_name, p_query), 0),
                    COALESCE(similarity(s.symbol_key, p_query), 0)
                )
            END
        END DESC NULLS LAST
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;


-- Search by properties (for spatial queries, etc.)
CREATE OR REPLACE FUNCTION vg_search_by_properties(
    p_context_id TEXT,
    p_filter JSONB,
    p_symbol_types TEXT[] DEFAULT NULL,
    p_limit INT DEFAULT 50
) RETURNS TABLE (
    id UUID,
    symbol_type TEXT,
    symbol_key TEXT,
    symbol_name TEXT,
    content TEXT,
    properties JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.symbol_type,
        s.symbol_key,
        s.symbol_name,
        s.content,
        s.properties
    FROM vg_symbol_index s
    WHERE s.context_id = p_context_id
      AND (p_symbol_types IS NULL OR s.symbol_type = ANY(p_symbol_types))
      AND s.properties @> p_filter
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Graph Traversal Functions
-- -----------------------------------------------------

-- Traverse the symbol graph
CREATE OR REPLACE FUNCTION vg_traverse_graph(
    p_start_id UUID,
    p_depth INT DEFAULT 2,
    p_edge_types TEXT[] DEFAULT NULL,
    p_direction TEXT DEFAULT 'both'  -- 'outgoing', 'incoming', 'both'
) RETURNS TABLE (
    symbol_id UUID,
    distance INT,
    path_ids UUID[],
    path_types TEXT[]
) AS $$
WITH RECURSIVE traversal AS (
    -- Starting point
    SELECT
        p_start_id as symbol_id,
        0 as distance,
        ARRAY[p_start_id] as path_ids,
        ARRAY[]::TEXT[] as path_types

    UNION

    -- Traverse edges
    SELECT
        CASE
            WHEN p_direction = 'outgoing' THEN e.target_id
            WHEN p_direction = 'incoming' THEN e.source_id
            ELSE CASE WHEN e.source_id = t.symbol_id THEN e.target_id ELSE e.source_id END
        END,
        t.distance + 1,
        t.path_ids || CASE
            WHEN p_direction = 'outgoing' THEN e.target_id
            WHEN p_direction = 'incoming' THEN e.source_id
            ELSE CASE WHEN e.source_id = t.symbol_id THEN e.target_id ELSE e.source_id END
        END,
        t.path_types || e.edge_type
    FROM traversal t
    JOIN vg_symbol_edges e ON
        CASE p_direction
            WHEN 'outgoing' THEN e.source_id = t.symbol_id
            WHEN 'incoming' THEN e.target_id = t.symbol_id
            ELSE e.source_id = t.symbol_id OR e.target_id = t.symbol_id
        END
    WHERE t.distance < p_depth
      AND (p_edge_types IS NULL OR e.edge_type = ANY(p_edge_types))
      AND NOT (CASE
            WHEN p_direction = 'outgoing' THEN e.target_id
            WHEN p_direction = 'incoming' THEN e.source_id
            ELSE CASE WHEN e.source_id = t.symbol_id THEN e.target_id ELSE e.source_id END
        END = ANY(t.path_ids))  -- Avoid cycles
)
SELECT * FROM traversal WHERE distance > 0;
$$ LANGUAGE sql;


-- Get neighbors (direct connections only)
CREATE OR REPLACE FUNCTION vg_get_neighbors(
    p_symbol_id UUID,
    p_edge_types TEXT[] DEFAULT NULL,
    p_direction TEXT DEFAULT 'both'
) RETURNS TABLE (
    neighbor_id UUID,
    edge_type TEXT,
    weight FLOAT,
    direction TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        CASE WHEN e.source_id = p_symbol_id THEN e.target_id ELSE e.source_id END as neighbor_id,
        e.edge_type,
        e.weight,
        CASE WHEN e.source_id = p_symbol_id THEN 'outgoing' ELSE 'incoming' END as direction
    FROM vg_symbol_edges e
    WHERE (
        (p_direction IN ('outgoing', 'both') AND e.source_id = p_symbol_id) OR
        (p_direction IN ('incoming', 'both') AND e.target_id = p_symbol_id)
    )
    AND (p_edge_types IS NULL OR e.edge_type = ANY(p_edge_types))
    ORDER BY e.weight DESC;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Context View Functions
-- -----------------------------------------------------

-- Generate summary view
CREATE OR REPLACE FUNCTION vg_generate_summary_view(
    p_context_id TEXT,
    p_token_budget INT DEFAULT 10000
) RETURNS TEXT AS $$
DECLARE
    v_result TEXT := '';
    v_type RECORD;
    v_sample RECORD;
    v_tokens INT := 0;
BEGIN
    v_result := '## Symbol Summary' || E'\n\n';

    -- Count by type
    FOR v_type IN
        SELECT symbol_type, COUNT(*) as cnt
        FROM vg_symbol_index
        WHERE context_id = p_context_id
        GROUP BY symbol_type
        ORDER BY cnt DESC
    LOOP
        v_result := v_result || '- ' || v_type.symbol_type || ': ' || v_type.cnt || E'\n';
        v_tokens := v_tokens + 10;

        IF v_tokens >= p_token_budget THEN
            v_result := v_result || E'\n... (truncated)';
            RETURN v_result;
        END IF;
    END LOOP;

    -- Top accessed symbols
    v_result := v_result || E'\n## Recently Accessed\n\n';

    FOR v_sample IN
        SELECT symbol_name, symbol_type, access_count
        FROM vg_symbol_index
        WHERE context_id = p_context_id AND access_count > 0
        ORDER BY last_accessed_at DESC NULLS LAST
        LIMIT 10
    LOOP
        v_result := v_result || '- ' || COALESCE(v_sample.symbol_name, '(unnamed)')
                   || ' (' || v_sample.symbol_type || ')' || E'\n';
        v_tokens := v_tokens + 15;

        IF v_tokens >= p_token_budget THEN
            RETURN v_result;
        END IF;
    END LOOP;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;


-- Generate focused view (around a specific symbol)
CREATE OR REPLACE FUNCTION vg_generate_focused_view(
    p_context_id TEXT,
    p_focus_symbol_id UUID,
    p_depth INT DEFAULT 1,
    p_token_budget INT DEFAULT 50000
) RETURNS TEXT AS $$
DECLARE
    v_result TEXT := '';
    v_focus RECORD;
    v_related RECORD;
    v_tokens INT := 0;
BEGIN
    -- Get focus symbol
    SELECT * INTO v_focus FROM vg_symbol_index WHERE id = p_focus_symbol_id;
    IF v_focus IS NULL THEN
        RETURN 'Symbol not found';
    END IF;

    -- Focus content
    v_result := '## Focus: ' || COALESCE(v_focus.symbol_name, v_focus.symbol_key) || E'\n\n';
    v_result := v_result || 'Type: ' || v_focus.symbol_type || E'\n';
    v_result := v_result || 'Key: ' || v_focus.symbol_key || E'\n\n';

    IF v_focus.content IS NOT NULL THEN
        v_result := v_result || '```' || E'\n' || LEFT(v_focus.content, 2000) || E'\n```\n\n';
    END IF;

    v_tokens := length(v_result) / 4;

    -- Related symbols
    v_result := v_result || '## Related Symbols' || E'\n\n';

    FOR v_related IN
        SELECT s.*, t.distance, t.path_types
        FROM vg_traverse_graph(p_focus_symbol_id, p_depth) t
        JOIN vg_symbol_index s ON s.id = t.symbol_id
        ORDER BY t.distance, s.access_count DESC
        LIMIT 20
    LOOP
        v_result := v_result || '- [' || array_to_string(v_related.path_types, ' -> ') || '] ';
        v_result := v_result || COALESCE(v_related.symbol_name, v_related.symbol_key);
        v_result := v_result || ' (' || v_related.symbol_type || ')' || E'\n';

        v_tokens := v_tokens + 20;
        IF v_tokens >= p_token_budget THEN
            v_result := v_result || E'\n... (truncated)';
            EXIT;
        END IF;
    END LOOP;

    -- Mark access
    PERFORM vg_touch_symbol(p_focus_symbol_id);

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Maintenance Functions
-- -----------------------------------------------------

-- Cleanup expired views
CREATE OR REPLACE FUNCTION vg_cleanup_expired_views() RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    DELETE FROM vg_context_views WHERE expires_at < now();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Cleanup orphan symbols (no edges, never accessed)
CREATE OR REPLACE FUNCTION vg_cleanup_orphan_symbols(
    p_context_id TEXT,
    p_min_age_hours INT DEFAULT 24
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    DELETE FROM vg_symbol_index s
    WHERE s.context_id = p_context_id
      AND s.created_at < now() - (p_min_age_hours || ' hours')::INTERVAL
      AND s.access_count = 0
      AND NOT EXISTS (
          SELECT 1 FROM vg_symbol_edges e
          WHERE e.source_id = s.id OR e.target_id = s.id
      );

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Get statistics
CREATE OR REPLACE FUNCTION vg_get_stats(
    p_context_id TEXT
) RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'total_symbols', (SELECT COUNT(*) FROM vg_symbol_index WHERE context_id = p_context_id),
        'total_edges', (
            SELECT COUNT(*) FROM vg_symbol_edges e
            JOIN vg_symbol_index s ON e.source_id = s.id
            WHERE s.context_id = p_context_id
        ),
        'symbols_by_type', (
            SELECT jsonb_object_agg(symbol_type, cnt)
            FROM (
                SELECT symbol_type, COUNT(*) as cnt
                FROM vg_symbol_index
                WHERE context_id = p_context_id
                GROUP BY symbol_type
            ) t
        ),
        'edges_by_type', (
            SELECT jsonb_object_agg(edge_type, cnt)
            FROM (
                SELECT e.edge_type, COUNT(*) as cnt
                FROM vg_symbol_edges e
                JOIN vg_symbol_index s ON e.source_id = s.id
                WHERE s.context_id = p_context_id
                GROUP BY e.edge_type
            ) t
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------
-- Similar Context Search (AI-Native Feature)
-- -----------------------------------------------------

-- Find similar contexts based on symbol overlap
CREATE OR REPLACE FUNCTION vg_find_similar_contexts(
    p_context_id TEXT,
    p_min_similarity FLOAT DEFAULT 0.3,
    p_limit INT DEFAULT 10
) RETURNS TABLE (
    context_id TEXT,
    similarity_score FLOAT,
    common_symbols INT,
    common_symbol_types TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    WITH source_symbols AS (
        SELECT symbol_type, symbol_key, content_hash
        FROM vg_symbol_index
        WHERE context_id = p_context_id
    ),
    source_count AS (
        SELECT COUNT(*)::FLOAT as cnt FROM source_symbols
    ),
    matches AS (
        SELECT
            t.context_id,
            COUNT(*) as common_count,
            array_agg(DISTINCT t.symbol_type) as types
        FROM vg_symbol_index t
        JOIN source_symbols s ON
            t.symbol_key = s.symbol_key AND
            t.symbol_type = s.symbol_type
        WHERE t.context_id != p_context_id
        GROUP BY t.context_id
    )
    SELECT
        m.context_id,
        (m.common_count / GREATEST(sc.cnt, 1))::FLOAT as similarity_score,
        m.common_count::INT as common_symbols,
        m.types as common_symbol_types
    FROM matches m
    CROSS JOIN source_count sc
    WHERE (m.common_count / GREATEST(sc.cnt, 1)) >= p_min_similarity
    ORDER BY similarity_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;


-- Find similar symbols by content hash (exact match) or name (fuzzy)
CREATE OR REPLACE FUNCTION vg_find_similar_symbols(
    p_symbol_id UUID,
    p_search_mode TEXT DEFAULT 'hybrid',  -- 'exact', 'fuzzy', 'hybrid'
    p_limit INT DEFAULT 20
) RETURNS TABLE (
    id UUID,
    context_id TEXT,
    symbol_type TEXT,
    symbol_key TEXT,
    symbol_name TEXT,
    similarity_score FLOAT,
    match_type TEXT
) AS $$
DECLARE
    v_source vg_symbol_index%ROWTYPE;
BEGIN
    SELECT * INTO v_source FROM vg_symbol_index WHERE vg_symbol_index.id = p_symbol_id;
    IF v_source IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    WITH exact_matches AS (
        SELECT
            s.id, s.context_id, s.symbol_type, s.symbol_key, s.symbol_name,
            1.0::FLOAT as score,
            'exact'::TEXT as mtype
        FROM vg_symbol_index s
        WHERE s.id != p_symbol_id
          AND s.content_hash = v_source.content_hash
          AND s.content_hash IS NOT NULL
          AND (p_search_mode IN ('exact', 'hybrid'))
    ),
    fuzzy_matches AS (
        SELECT
            s.id, s.context_id, s.symbol_type, s.symbol_key, s.symbol_name,
            GREATEST(
                similarity(s.symbol_name, v_source.symbol_name),
                similarity(s.symbol_key, v_source.symbol_key)
            )::FLOAT as score,
            'fuzzy'::TEXT as mtype
        FROM vg_symbol_index s
        WHERE s.id != p_symbol_id
          AND s.symbol_type = v_source.symbol_type
          AND (p_search_mode IN ('fuzzy', 'hybrid'))
          AND (
              s.symbol_name % v_source.symbol_name OR
              s.symbol_key % v_source.symbol_key
          )
    ),
    all_matches AS (
        SELECT * FROM exact_matches
        UNION ALL
        SELECT * FROM fuzzy_matches
    )
    SELECT DISTINCT ON (am.id)
        am.id, am.context_id, am.symbol_type, am.symbol_key, am.symbol_name,
        am.score, am.mtype
    FROM all_matches am
    ORDER BY am.id, am.score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;


-- Find contexts with similar structure (by edge patterns)
CREATE OR REPLACE FUNCTION vg_find_contexts_by_structure(
    p_context_id TEXT,
    p_min_similarity FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10
) RETURNS TABLE (
    context_id TEXT,
    structural_similarity FLOAT,
    edge_pattern_matches INT
) AS $$
BEGIN
    RETURN QUERY
    WITH source_patterns AS (
        -- Get edge type distribution for source context
        SELECT
            e.edge_type,
            COUNT(*) as cnt
        FROM vg_symbol_edges e
        JOIN vg_symbol_index s ON e.source_id = s.id
        WHERE s.context_id = p_context_id
        GROUP BY e.edge_type
    ),
    source_total AS (
        SELECT COALESCE(SUM(cnt), 1)::FLOAT as total FROM source_patterns
    ),
    target_patterns AS (
        -- Get edge type distribution for all other contexts
        SELECT
            s.context_id,
            e.edge_type,
            COUNT(*) as cnt
        FROM vg_symbol_edges e
        JOIN vg_symbol_index s ON e.source_id = s.id
        WHERE s.context_id != p_context_id
        GROUP BY s.context_id, e.edge_type
    ),
    pattern_comparison AS (
        SELECT
            tp.context_id,
            SUM(LEAST(sp.cnt, tp.cnt)) as matched,
            SUM(tp.cnt) as total_target
        FROM target_patterns tp
        JOIN source_patterns sp ON tp.edge_type = sp.edge_type
        GROUP BY tp.context_id
    )
    SELECT
        pc.context_id,
        (pc.matched / GREATEST(st.total, pc.total_target))::FLOAT as structural_similarity,
        pc.matched::INT as edge_pattern_matches
    FROM pattern_comparison pc
    CROSS JOIN source_total st
    WHERE (pc.matched / GREATEST(st.total, pc.total_target)) >= p_min_similarity
    ORDER BY structural_similarity DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Feedback Functions SQL (Optional)
# ============================================================

GRAPH_FEEDBACK_FUNCTIONS_SQL = """
-- ============================================================
-- Versiona Graph Extension - Feedback Functions (Optional)
-- ============================================================

-- Submit feedback
CREATE OR REPLACE FUNCTION vg_submit_feedback(
    p_context_id TEXT,
    p_feedback_type TEXT,
    p_feedback_content JSONB,
    p_symbol_id UUID DEFAULT NULL,
    p_edge_id UUID DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO vg_llm_feedback (
        context_id, symbol_id, edge_id, feedback_type, feedback_content
    ) VALUES (
        p_context_id, p_symbol_id, p_edge_id, p_feedback_type, p_feedback_content
    ) RETURNING id INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;


-- Process pending feedback
CREATE OR REPLACE FUNCTION vg_process_pending_feedback(
    p_context_id TEXT DEFAULT NULL,
    p_auto_apply_threshold FLOAT DEFAULT 0.8
) RETURNS INT AS $$
DECLARE
    v_count INT := 0;
    v_feedback RECORD;
    v_content JSONB;
BEGIN
    FOR v_feedback IN
        SELECT * FROM vg_llm_feedback
        WHERE status = 'pending'
          AND (p_context_id IS NULL OR context_id = p_context_id)
        ORDER BY created_at
    LOOP
        v_content := v_feedback.feedback_content;

        CASE v_feedback.feedback_type
            WHEN 'missing_edge' THEN
                -- Auto-create missing edge if confidence is high
                IF (v_content->>'confidence')::FLOAT >= p_auto_apply_threshold THEN
                    PERFORM vg_add_edge_by_key(
                        v_feedback.context_id,
                        v_content->>'source_type',
                        v_content->>'source_key',
                        v_content->>'target_type',
                        v_content->>'target_key',
                        v_content->>'edge_type',
                        1.0,
                        'llm'
                    );

                    UPDATE vg_llm_feedback SET status = 'applied', processed_at = now()
                    WHERE id = v_feedback.id;
                    v_count := v_count + 1;
                END IF;

            WHEN 'co_modified' THEN
                -- Increment edge weight
                IF v_feedback.edge_id IS NOT NULL THEN
                    UPDATE vg_symbol_edges SET
                        weight = weight + 0.1
                    WHERE id = v_feedback.edge_id;

                    UPDATE vg_llm_feedback SET status = 'applied', processed_at = now()
                    WHERE id = v_feedback.id;
                    v_count := v_count + 1;
                END IF;

            ELSE
                -- Other types require manual processing
                NULL;
        END CASE;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- Get pending feedback count
CREATE OR REPLACE FUNCTION vg_get_pending_feedback_count(
    p_context_id TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM vg_llm_feedback
    WHERE status = 'pending'
      AND (p_context_id IS NULL OR context_id = p_context_id);

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
"""


# ============================================================
# Helper Functions
# ============================================================

def get_graph_functions_sql(include_feedback: bool = False) -> str:
    """
    Get the complete Graph extension functions SQL.

    Args:
        include_feedback: Include LLM feedback functions (default: False)

    Returns:
        SQL string to create all functions
    """
    sql = GRAPH_FUNCTIONS_SQL
    if include_feedback:
        sql += "\n" + GRAPH_FEEDBACK_FUNCTIONS_SQL
    return sql


def get_graph_function_names(include_feedback: bool = False) -> list[str]:
    """Get all function names for the Graph extension."""
    functions = [
        # Symbol CRUD
        "vg_upsert_symbol",
        "vg_bulk_upsert_symbols",
        "vg_touch_symbol",
        "vg_touch_symbols",
        "vg_delete_symbols_by_context",
        # Edge CRUD
        "vg_add_edge",
        "vg_add_edge_by_key",
        "vg_increment_edge_weight",
        # Search
        "vg_search_symbols",
        "vg_search_by_properties",
        # Traversal
        "vg_traverse_graph",
        "vg_get_neighbors",
        # Views
        "vg_generate_summary_view",
        "vg_generate_focused_view",
        # Maintenance
        "vg_cleanup_expired_views",
        "vg_cleanup_orphan_symbols",
        "vg_get_stats",
        # Similar context search (AI-Native Feature)
        "vg_find_similar_contexts",
        "vg_find_similar_symbols",
        "vg_find_contexts_by_structure",
    ]
    if include_feedback:
        functions.extend([
            "vg_submit_feedback",
            "vg_process_pending_feedback",
            "vg_get_pending_feedback_count",
        ])
    return functions
