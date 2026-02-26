"""
Longterm Memory Extension - Type Definitions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class MemoryType(str, Enum):
    """記憶類型"""
    PREFERENCE = "preference"   # 用戶偏好
    FACT = "fact"               # 學到的事實
    PATTERN = "pattern"         # 行為模式
    CORRECTION = "correction"   # LLM 被糾正的錯誤


class MemoryScope(str, Enum):
    """記憶範圍"""
    GLOBAL = "global"           # 全域（跨用戶、跨專案）
    PROJECT = "project"         # 專案級（跨用戶）
    USER = "user"               # 用戶級（跨專案）
    PROJECT_USER = "project_user"  # 專案 + 用戶


@dataclass
class Memory:
    """記憶物件"""
    id: UUID
    project_id: UUID | None
    user_id: UUID | None
    memory_type: MemoryType
    key: str
    content: dict[str, Any]
    source_session_id: str | None
    source_description: str | None
    importance: float
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def scope(self) -> MemoryScope:
        """計算記憶範圍"""
        if self.project_id and self.user_id:
            return MemoryScope.PROJECT_USER
        elif self.project_id:
            return MemoryScope.PROJECT
        elif self.user_id:
            return MemoryScope.USER
        else:
            return MemoryScope.GLOBAL

    def to_dict(self) -> dict[str, Any]:
        """轉換為 dict"""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id) if self.project_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "memory_type": self.memory_type.value,
            "key": self.key,
            "content": self.content,
            "source_session_id": self.source_session_id,
            "source_description": self.source_description,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "scope": self.scope.value,
        }

    @classmethod
    def from_row(cls, row: dict) -> Memory:
        """從資料庫 row 建立"""
        return cls(
            id=row["id"],
            project_id=row.get("project_id"),
            user_id=row.get("user_id"),
            memory_type=MemoryType(row["memory_type"]),
            key=row["key"],
            content=row["content"] if isinstance(row["content"], dict) else {},
            source_session_id=row.get("source_session_id"),
            source_description=row.get("source_description"),
            importance=row.get("importance", 1.0),
            access_count=row.get("access_count", 0),
            last_accessed_at=row.get("last_accessed_at"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
