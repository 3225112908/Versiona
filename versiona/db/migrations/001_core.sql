-- ============================================================
-- Versiona Migration 001: Core Schema
-- Git-like Version Control for PostgreSQL
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- Repository
-- ============================================================
CREATE TABLE IF NOT EXISTS v_repositories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    default_branch TEXT DEFAULT 'main',
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repositories_name ON v_repositories(name);

-- ============================================================
-- Commit (create before branches for FK)
-- ============================================================
CREATE TABLE IF NOT EXISTS v_commits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES v_repositories(id) ON DELETE CASCADE,
    hash BYTEA UNIQUE NOT NULL,
    tree_hash BYTEA NOT NULL,
    parent_hashes BYTEA[],
    message TEXT,
    author JSONB,
    metadata JSONB,
    committed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_commits_repo ON v_commits(repo_id, committed_at DESC);
CREATE INDEX IF NOT EXISTS idx_commits_hash ON v_commits(hash);

-- ============================================================
-- Branch
-- ============================================================
CREATE TABLE IF NOT EXISTS v_branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES v_repositories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    head_commit_id UUID REFERENCES v_commits(id) ON DELETE SET NULL,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(repo_id, name)
);

CREATE INDEX IF NOT EXISTS idx_branches_repo ON v_branches(repo_id);

-- ============================================================
-- Object Store (Content-Addressable)
-- ============================================================
CREATE TABLE IF NOT EXISTS v_objects (
    hash BYTEA PRIMARY KEY,
    type TEXT NOT NULL,
    size BIGINT NOT NULL,
    data BYTEA,
    storage_ref TEXT,
    compression TEXT DEFAULT 'none',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_objects_type ON v_objects(type);

-- ============================================================
-- Tree Entries
-- ============================================================
CREATE TABLE IF NOT EXISTS v_tree_entries (
    tree_hash BYTEA NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    object_hash BYTEA NOT NULL,
    metadata JSONB,
    PRIMARY KEY (tree_hash, name)
);

CREATE INDEX IF NOT EXISTS idx_tree_entries_object ON v_tree_entries(object_hash);

-- ============================================================
-- Versioned Tables Registry
-- ============================================================
CREATE TABLE IF NOT EXISTS v_tables_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES v_repositories(id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    full_table_name TEXT NOT NULL,
    schema_def JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(repo_id, table_name)
);

-- ============================================================
-- Working Tree (Uncommitted Changes)
-- ============================================================
CREATE TABLE IF NOT EXISTS v_working_tree (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID NOT NULL REFERENCES v_repositories(id) ON DELETE CASCADE,
    branch_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_id UUID NOT NULL,
    operation TEXT NOT NULL,
    old_data JSONB,
    new_data JSONB,
    changed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(repo_id, branch_name, table_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_working_tree_repo_branch
    ON v_working_tree(repo_id, branch_name);

-- ============================================================
-- Checkout State
-- ============================================================
CREATE TABLE IF NOT EXISTS v_checkout_state (
    repo_id UUID PRIMARY KEY REFERENCES v_repositories(id) ON DELETE CASCADE,
    branch_name TEXT NOT NULL,
    commit_id UUID REFERENCES v_commits(id),
    is_detached BOOLEAN DEFAULT false,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Migration Tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS v_migrations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO v_migrations (name) VALUES ('001_core')
ON CONFLICT (name) DO NOTHING;
