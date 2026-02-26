"""
Versiona Compression Extension

Automatic context compression when size exceeds threshold.

Features:
- Compression queue with priority
- Token counting support (optional column in KV table)
- Database trigger for automatic queue insertion
- Background worker support

Usage:
    from versiona.extensions.compression import (
        get_compression_schema_sql,
        CompressionQueueClient,
        CompressionStatus,
    )

    # Get schema SQL (includes trigger)
    sql = get_compression_schema_sql(
        kv_table="agent_kv",
        size_threshold=100000,  # 100KB
    )

    # Create client
    client = CompressionQueueClient(db_pool)

    # Get pending items
    pending = await client.get_pending(limit=10)

    # Mark as processing
    await client.mark_processing(item_id)

    # Complete compression
    await client.complete(item_id)
"""

from .schema import (
    get_compression_schema_sql,
    get_compression_table_names,
    get_token_column_sql,
)
from .types import CompressionQueueItem, CompressionStatus
from .client import CompressionQueueClient

__all__ = [
    # Schema
    "get_compression_schema_sql",
    "get_compression_table_names",
    "get_token_column_sql",
    # Types
    "CompressionQueueItem",
    "CompressionStatus",
    # Client
    "CompressionQueueClient",
]
