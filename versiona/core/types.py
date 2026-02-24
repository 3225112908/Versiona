"""Versiona core types - Repository, Branch, Commit, Object."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================


class ObjectType(str, Enum):
    """Type of content-addressable object."""

    BLOB = "blob"  # Raw binary data
    TREE = "tree"  # Directory structure
    TABLE_SNAPSHOT = "table_snapshot"  # Snapshot of a table
    ROW = "row"  # Single row data


class TreeEntryMode(str, Enum):
    """Mode of a tree entry."""

    FILE = "file"
    DIR = "dir"
    TABLE = "table"
    ROW = "row"


class CompressionType(str, Enum):
    """Compression type for objects."""

    NONE = "none"
    ZSTD = "zstd"
    LZ4 = "lz4"


# ============================================================
# Core Models
# ============================================================


class Author(BaseModel):
    """Author information for commits."""

    name: str
    email: str | None = None
    id: UUID | None = None


class RepositorySettings(BaseModel):
    """Repository settings stored as JSONB."""

    auto_gc: bool = True
    max_object_size_inline: int = 65536  # 64KB, larger objects go to external storage
    compression: CompressionType = CompressionType.NONE


class Repository(BaseModel):
    """Repository model - Git-like repository for versioned data."""

    id: UUID
    name: str
    description: str | None = None
    default_branch: str = "main"
    settings: RepositorySettings = Field(default_factory=RepositorySettings)
    created_at: datetime
    updated_at: datetime

    class Config:
        frozen = True


class Branch(BaseModel):
    """Branch model - pointer to a commit."""

    id: UUID
    repo_id: UUID
    name: str
    head_commit_id: UUID | None = None
    is_default: bool = False
    created_at: datetime

    class Config:
        frozen = True


class Commit(BaseModel):
    """Commit model - snapshot of repository state."""

    id: UUID
    repo_id: UUID
    hash: bytes  # Content hash (SHA-256)
    tree_hash: bytes  # Root tree hash
    parent_hashes: list[bytes] = Field(default_factory=list)  # Support merge commits
    message: str | None = None
    author: Author | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    committed_at: datetime

    class Config:
        frozen = True


class Object(BaseModel):
    """Content-addressable object storage."""

    hash: bytes  # Primary key (SHA-256)
    type: ObjectType
    size: int
    data: bytes | None = None  # Inline data for small objects
    storage_ref: str | None = None  # External reference for large objects (S3/MinIO)
    compression: CompressionType = CompressionType.NONE
    created_at: datetime

    class Config:
        frozen = True


class TreeEntry(BaseModel):
    """Entry in a tree (directory)."""

    tree_hash: bytes
    name: str
    mode: TreeEntryMode
    object_hash: bytes
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        frozen = True


# ============================================================
# Operation Types
# ============================================================


class DiffEntry(BaseModel):
    """Single entry in a diff result."""

    path: str
    operation: str  # 'add', 'modify', 'delete'
    old_hash: bytes | None = None
    new_hash: bytes | None = None
    old_data: Any | None = None
    new_data: Any | None = None


class DiffResult(BaseModel):
    """Result of comparing two commits."""

    from_commit: bytes
    to_commit: bytes
    entries: list[DiffEntry] = Field(default_factory=list)


class MergeConflict(BaseModel):
    """Conflict detected during merge."""

    path: str
    base_data: Any | None = None  # Common ancestor
    ours_data: Any | None = None  # Current branch
    theirs_data: Any | None = None  # Branch being merged


class MergeResult(BaseModel):
    """Result of a merge operation."""

    success: bool
    commit_id: UUID | None = None
    conflicts: list[MergeConflict] = Field(default_factory=list)


# ============================================================
# Table Types (for versioned tables)
# ============================================================


class ColumnDefinition(BaseModel):
    """Column definition for versioned tables."""

    name: str
    type: str  # PostgreSQL type: 'text', 'integer', 'uuid', 'jsonb', etc.
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False


class TableSchema(BaseModel):
    """Schema definition for a versioned table."""

    name: str
    columns: list[ColumnDefinition]


class RowChange(BaseModel):
    """Change record for a row."""

    id: UUID
    row_id: UUID
    operation: str  # 'INSERT', 'UPDATE', 'DELETE'
    old_data: dict[str, Any] | None = None
    new_data: dict[str, Any] | None = None
    changed_at: datetime
    commit_id: UUID | None = None  # None = uncommitted
