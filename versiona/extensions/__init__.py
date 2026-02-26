"""
Versiona Extensions - Optional plugins for extended functionality.

Available extensions:
- graph: Symbol indexing and graph-based context engine
- longterm_memory: Cross-session persistent memory storage
- compression: Automatic context compression with queue
- agent_state: State-driven agent execution tracking

Usage:
    # Longterm Memory
    from versiona.extensions.longterm_memory import (
        get_longterm_memory_schema_sql,
        LongtermMemoryClient,
        Memory,
        MemoryType,
    )

    # Compression
    from versiona.extensions.compression import (
        get_compression_schema_sql,
        CompressionQueueClient,
        CompressionStatus,
    )

    # Agent State (State-Driven Architecture)
    from versiona.extensions.agent_state import (
        get_agent_state_schema_sql,
        AgentStateClient,
        AgentState,
        HandlerStatus,
    )
"""

__all__: list[str] = []
