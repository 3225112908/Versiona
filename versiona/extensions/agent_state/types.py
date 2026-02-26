"""
Versiona Agent State Extension - Types

State-driven agent execution state tracking.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class HandlerStatus(str, Enum):
    """Handler 狀態"""
    IDLE = "idle"                    # 閒置，等待輸入
    PENDING = "pending"              # 等待處理（剛被 handover）
    EXECUTING = "executing"          # 執行中
    WAITING_USER = "waiting_user"    # 等待用戶回應
    COMPLETED = "completed"          # 完成
    ERROR = "error"                  # 錯誤


class AgentState(BaseModel):
    """Agent State - State-driven 執行狀態"""
    id: UUID | None = None

    # 關聯到 Versiona context
    session_id: str  # = Versiona node_id

    # Handler 資訊（誰在處理）
    current_handler: str  # "cad_system", "quote_system", "idle"
    handler_status: HandlerStatus = HandlerStatus.IDLE

    # 當前任務（fork 的 subagent）
    current_task: str | None = None  # "planning", "explore", "editor", "analysis"
    current_fork_id: str | None = None  # 正在執行的 fork 的 node_id

    # Handover 資訊（跨 System）
    previous_handler: str | None = None
    handover_reason: str | None = None
    handover_at: datetime | None = None

    # Handler 歷史
    handler_history: list[dict] = Field(default_factory=list)
    # [{"handler": "cad_system", "status": "completed", "at": "..."}]

    # 時間戳
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "AgentState":
        """從資料庫 row 建立"""
        return cls(
            id=row.get("id"),
            session_id=row["session_id"],
            current_handler=row["current_handler"],
            handler_status=HandlerStatus(row.get("handler_status", "idle")),
            current_task=row.get("current_task"),
            current_fork_id=row.get("current_fork_id"),
            previous_handler=row.get("previous_handler"),
            handover_reason=row.get("handover_reason"),
            handover_at=row.get("handover_at"),
            handler_history=row.get("handler_history", []),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def to_dict(self) -> dict:
        """轉換為 dict"""
        return {
            "id": str(self.id) if self.id else None,
            "session_id": self.session_id,
            "current_handler": self.current_handler,
            "handler_status": self.handler_status.value,
            "current_task": self.current_task,
            "current_fork_id": self.current_fork_id,
            "previous_handler": self.previous_handler,
            "handover_reason": self.handover_reason,
            "handover_at": self.handover_at.isoformat() if self.handover_at else None,
            "handler_history": self.handler_history,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HandoverRecord(BaseModel):
    """Handover 記錄"""
    handler: str
    status: str
    at: datetime
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "handler": self.handler,
            "status": self.status,
            "at": self.at.isoformat(),
            "reason": self.reason,
        }
