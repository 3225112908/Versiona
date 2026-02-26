"""
Versiona Longterm Memory Extension

跨 session 的長期記憶存儲。

Features:
- Project/User scoped memories
- Memory types: preference, fact, pattern, correction
- Access tracking and importance scoring
- Automatic relevance loading

Usage:
    from versiona.extensions.longterm_memory import (
        LongtermMemoryClient,
        Memory,
        MemoryType,
        get_longterm_memory_schema_sql,
    )

    # Get schema SQL
    sql = get_longterm_memory_schema_sql()

    # Create client
    client = LongtermMemoryClient(db_pool)

    # Store memory
    await client.store(
        memory_type=MemoryType.PREFERENCE,
        key="line_color",
        content={"preference": "red for electrical"},
        project_id=project_id,
        user_id=user_id,
    )

    # Recall memories
    memories = await client.recall(
        project_id=project_id,
        user_id=user_id,
        limit=50,
    )
"""

from .schema import get_longterm_memory_schema_sql, get_longterm_memory_table_names
from .types import Memory, MemoryType
from .client import LongtermMemoryClient

__all__ = [
    # Schema
    "get_longterm_memory_schema_sql",
    "get_longterm_memory_table_names",
    # Types
    "Memory",
    "MemoryType",
    # Client
    "LongtermMemoryClient",
]
