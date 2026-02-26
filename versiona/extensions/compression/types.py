"""
Versiona Compression Extension - Type Definitions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class CompressionStatus(str, Enum):
    """Compression queue status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CompressionQueueItem:
    """Compression queue item"""
    id: UUID
    node_id: str
    total_size: int
    total_tokens: int | None
    priority: int
    status: CompressionStatus
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict"""
        return {
            "id": str(self.id),
            "node_id": self.node_id,
            "total_size": self.total_size,
            "total_tokens": self.total_tokens,
            "priority": self.priority,
            "status": self.status.value,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_row(cls, row: dict) -> CompressionQueueItem:
        """Create from database row"""
        return cls(
            id=row["id"],
            node_id=row["node_id"],
            total_size=row.get("total_size", 0),
            total_tokens=row.get("total_tokens"),
            priority=row.get("priority", 0),
            status=CompressionStatus(row.get("status", "pending")),
            error_message=row.get("error_message"),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
        )
