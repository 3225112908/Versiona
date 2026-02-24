"""
Versiona Context Module - Dual-dimension Context System.

Features:
1. Horizontal (tree): Context tree, supports fork/merge
2. Vertical (version): Each Context has version history
3. Dual-mode TTL: Time expiration + Turn expiration

Usage Example:

    from versiona.context import ContextClient, ContextLevel

    # Create client
    client = await ContextClient.create("postgresql://user:pass@localhost/db")

    # Create Project Context (L0)
    await client.create_context("project_123", level=ContextLevel.PROJECT)

    # Fork Task Context (L1)
    await client.fork("project_123", "task_abc")

    # Use execution_context wrapper
    async with client.execution_context("sub_1", parent_id="task_abc") as ctx:
        await ctx.set_local("thinking", ["Analyzing requirements..."], ttl_turns=3, current_turn=0)
        await ctx.set_output("summary", "Task completed")
        # Auto finalize and merge on exit

    await client.close()
"""

from versiona.context.types import (
    ContextLevel,
    DataCategory,
    ContextNode,
    ContextVersion,
    ContextData,
    DiffResult,
    Branch,
    Tag,
    VersionaConfig,
)

__all__ = [
    # Types
    "ContextLevel",
    "DataCategory",
    "ContextNode",
    "ContextVersion",
    "ContextData",
    "DiffResult",
    "Branch",
    "Tag",
    # Config
    "VersionaConfig",
]
