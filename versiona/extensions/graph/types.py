"""
Versiona Graph Extension - Type definitions.

This module defines all types used by the Graph extension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


# ============================================================
# Enums
# ============================================================


class SymbolType(str, Enum):
    """
    Built-in symbol types.

    Users can register custom types via GraphExtension.register_symbol_type().
    """

    # Generic
    GENERIC = "generic"

    # Code-related
    FILE = "file"
    FUNCTION = "function"
    CLASS = "class"
    VARIABLE = "variable"
    MODULE = "module"

    # CAD-related
    LAYER = "layer"
    BLOCK = "block"
    ENTITY = "entity"
    STYLE = "style"


class EdgeType(str, Enum):
    """
    Built-in edge types.

    Users can register custom types via GraphExtension.register_edge_type().
    """

    # Structural
    CONTAINS = "contains"           # Parent contains child
    REFERENCES = "references"       # A references B
    DEPENDS_ON = "depends_on"       # A depends on B

    # Semantic
    RELATED_TO = "related_to"       # Generic relation (undirected)
    SIMILAR_TO = "similar_to"       # Similarity (undirected)
    DERIVED_FROM = "derived_from"   # A is derived from B

    # Behavioral
    CO_MODIFIED = "co_modified"     # Often modified together
    CO_ACCESSED = "co_accessed"     # Often accessed together

    # Custom
    CUSTOM = "custom"               # User-defined


class FeedbackType(str, Enum):
    """Types of LLM feedback."""

    MISSING_EDGE = "missing_edge"       # Should have an edge but doesn't
    WRONG_EDGE = "wrong_edge"           # Edge exists but is incorrect
    MISSING_SYMBOL = "missing_symbol"   # Symbol should exist but doesn't
    WRONG_CONTENT = "wrong_content"     # Symbol content is incorrect
    SUGGESTION = "suggestion"           # General suggestion


class FeedbackStatus(str, Enum):
    """Status of feedback processing."""

    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ============================================================
# Data Classes
# ============================================================


@dataclass
class SymbolTypeConfig:
    """Configuration for a symbol type."""

    name: str
    description: str | None = None
    default_ttl_seconds: int | None = None
    auto_index: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeTypeConfig:
    """Configuration for an edge type."""

    name: str
    description: str | None = None
    is_directional: bool = True
    auto_create: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Symbol:
    """
    A symbol in the index.

    Symbols represent searchable items like functions, files, entities, etc.
    """

    id: UUID
    context_id: str
    symbol_type: str
    symbol_key: str
    symbol_name: str | None
    content: str | None
    content_hash: str | None
    properties: dict[str, Any]
    access_count: int
    modification_count: int
    last_accessed_at: datetime | None
    last_modified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class Edge:
    """
    An edge connecting two symbols.

    Edges represent relationships like "contains", "references", etc.
    """

    id: UUID
    source_id: UUID
    target_id: UUID
    edge_type: str
    weight: float
    created_by: str
    confidence: float
    metadata: dict[str, Any]
    created_at: datetime


@dataclass
class SearchResult:
    """Result from a symbol search."""

    symbol: Symbol
    relevance_score: float


@dataclass
class TraversalResult:
    """Result from a graph traversal."""

    symbol_id: UUID
    distance: int
    path_ids: list[UUID]
    path_types: list[str]


@dataclass
class ContextView:
    """A generated context view for LLM consumption."""

    id: UUID
    context_id: str
    view_name: str
    view_content: str
    token_estimate: int | None
    included_symbols: list[UUID]
    generation_params: dict[str, Any]
    cache_key: str | None
    expires_at: datetime | None
    created_at: datetime


@dataclass
class Feedback:
    """LLM feedback for graph corrections."""

    id: UUID
    context_id: str
    symbol_id: UUID | None
    edge_id: UUID | None
    feedback_type: FeedbackType
    feedback_content: dict[str, Any]
    status: FeedbackStatus
    processed_at: datetime | None
    created_at: datetime


# ============================================================
# Configuration
# ============================================================


@dataclass
class GraphConfig:
    """
    Configuration for GraphExtension.

    Attributes:
        enable_feedback: Enable LLM feedback module (default: False)
        auto_create_contains: Auto-create 'contains' edges from key hierarchy
        default_view_cache_ttl: Default TTL for cached views (seconds)
        default_search_limit: Default limit for search results
        trigram_similarity_threshold: Minimum similarity for trigram search
    """

    enable_feedback: bool = False
    auto_create_contains: bool = True
    default_view_cache_ttl: int = 300
    default_search_limit: int = 50
    trigram_similarity_threshold: float = 0.3

    # TTL defaults for different symbol types
    symbol_ttl_defaults: dict[str, int] = field(default_factory=lambda: {
        "thinking": 3600,       # 1 hour
        "tool_calls": 86400,    # 1 day
        "intermediate": 3600,   # 1 hour
    })
