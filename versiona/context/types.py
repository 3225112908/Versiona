"""
Versiona Context Types - Dual-dimension Context System Type Definitions.

Defines core data types for the Context system:
- ContextLevel: Context level (L0=Project, L1=Task, L2=Execution)
- DataCategory: Data category (local, output)
- ContextNode, ContextVersion, ContextData: Context related
- DiffResult, Branch, Tag, Snapshot: Version control related
- VersionaConfig: Configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ============================================================
# Enums
# ============================================================


class ContextLevel(str, Enum):
    """Context level."""
    PROJECT = "L0"     # Project level
    TASK = "L1"        # Task level
    EXECUTION = "L2"   # Execution level


class DataCategory(str, Enum):
    """Data category."""
    LOCAL = "local"       # Local data (not inherited)
    OUTPUT = "output"     # Output data (inheritable)


# ============================================================
# Context Types
# ============================================================


@dataclass
class ContextNode:
    """Context node."""
    id: str
    parent_id: str | None
    level: ContextLevel
    name: str | None
    status: str
    current_version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class ContextVersion:
    """Context version."""
    node_id: str
    version: int
    local_data: dict[str, Any]
    output_data: dict[str, Any]
    soft_deleted_keys: list[str]
    message: str | None
    author_id: str | None
    created_at: datetime


@dataclass
class ContextData:
    """Context data (including inherited data)."""
    node_id: str
    version: int
    level: ContextLevel
    local_data: dict[str, Any]
    output_data: dict[str, Any]
    inherited: dict[str, Any]
    soft_deleted_keys: list[str]


# ============================================================
# Version Control Types
# ============================================================


@dataclass
class DiffResult:
    """Diff result."""
    node_id: str
    from_version: int
    to_version: int
    added: dict[str, Any]
    removed: dict[str, Any]
    modified: dict[str, Any]


@dataclass
class Branch:
    """Branch information."""
    id: str
    node_id: str
    name: str
    head_version: int
    is_default: bool
    forked_from_node: str | None
    forked_from_version: int | None
    created_at: datetime


@dataclass
class Tag:
    """Tag information."""
    id: str
    node_id: str
    name: str
    version: int
    message: str | None
    created_at: datetime


@dataclass
class Snapshot:
    """Snapshot information."""
    id: str
    root_node_id: str
    name: str | None
    message: str | None
    snapshot_type: str
    node_versions: dict[str, int]
    metadata: dict[str, Any]
    author_id: str | None
    created_at: datetime


# ============================================================
# Config Types
# ============================================================


@dataclass
class VersionaConfig:
    """
    Versiona configuration.

    Contains:
    - Connection settings: DSN, connection pool size, timeout
    - Auto cleanup settings
    - Dual-mode TTL defaults:
      - Time TTL: For real-time information (weather, stock prices, API responses)
      - Turn TTL: For Agent loop process data (thinking, tool_results)
    """

    # Connection settings
    dsn: str = "postgresql://localhost/versiona"
    min_pool_size: int = 2
    max_pool_size: int = 10
    command_timeout: float = 60.0

    # Auto cleanup settings
    auto_cleanup: bool = True
    cleanup_interval_seconds: int = 300  # 5 minutes

    # Time TTL defaults (seconds) - for real-time information
    default_time_ttl: dict[str, int] = field(default_factory=lambda: {
        "weather": 1800,       # 30 minutes
        "stock_price": 60,     # 1 minute
        "api_response": 300,   # 5 minutes
        "search_results": 3600, # 1 hour
    })

    # Turn TTL defaults (turns) - for Agent loop process data
    default_turn_ttl: dict[str, int] = field(default_factory=lambda: {
        "thinking": 3,         # expires after 3 turns
        "tool_calls": 5,       # expires after 5 turns
        "tool_results": 5,     # expires after 5 turns
        "intermediate": 2,     # expires after 2 turns
        "reasoning": 3,        # expires after 3 turns
    })

    # Soft delete default keys (auto soft delete on finalize)
    auto_soft_delete_keys: set[str] = field(default_factory=lambda: {
        "thinking",
        "tool_calls",
        "tool_results",
        "reasoning",
        "intermediate",
        "debug",
    })
