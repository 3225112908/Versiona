"""
Versiona - Dual-dimension Context Version Control System.

Features:
1. Horizontal (tree): Context tree with fork/merge support
2. Vertical (version): Each Context has version history
3. Direct DB connection: Uses asyncpg, no HTTP API needed
4. Extensible: Support additional features via extensions (e.g., Graph)

Usage Example:

    from versiona import VersionaClient, ContextLevel

    # Create client
    client = await VersionaClient.create("postgresql://user:pass@localhost/db")

    # Initialize schema (first use)
    await client.init_schema()

    # Create Project Context (L0)
    await client.create_context("project_123", level=ContextLevel.PROJECT)

    # Fork a Task Context (L1)
    await client.fork("project_123", "task_abc")

    # Use execution_context wrapper
    async with client.execution_context("sub_1", parent_id="task_abc") as ctx:
        await ctx.set_local("thinking", ["Analyzing requirements..."])
        await ctx.set_output("summary", "Task completed")
        # Auto finalize and merge on exit

    await client.close()

Using Graph Extension:

    from versiona import VersionaClient
    from versiona.extensions.graph import GraphExtension, GraphConfig

    client = await VersionaClient.create(dsn)

    # Load extension during init
    await client.init_schema(extensions=["graph"])

    # Use Graph Extension
    graph = GraphExtension(client)
    await graph.add_symbol(
        context_id="project_123",
        symbol_type="function",
        symbol_key="utils.py::calculate",
        symbol_name="calculate",
        content="def calculate(x, y): ..."
    )
"""

# Types from context module
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

# Client
from versiona.client import (
    VersionaClient,
    ExecutionContext,
)

from versiona.db.schema import (
    get_schema_sql,
    get_table_names,
    get_function_names,
    # Extension support
    register_extension_schema,
    get_extension_schema,
    get_extension_functions,
    list_extensions,
    get_full_schema_with_extensions,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "VersionaClient",
    "VersionaConfig",
    # Types
    "ContextLevel",
    "DataCategory",
    "ContextNode",
    "ContextVersion",
    "ContextData",
    "DiffResult",
    "Branch",
    "Tag",
    # Context wrapper
    "ExecutionContext",
    # Schema
    "get_schema_sql",
    "get_table_names",
    "get_function_names",
    # Extension support
    "register_extension_schema",
    "get_extension_schema",
    "get_extension_functions",
    "list_extensions",
    "get_full_schema_with_extensions",
]


# ============================================================
# Auto-register built-in extensions
# ============================================================

def _register_builtin_extensions() -> None:
    """Register built-in extensions on import."""
    try:
        from versiona.extensions.graph.schema import get_graph_schema_sql
        from versiona.extensions.graph.functions import get_graph_functions_sql
        register_extension_schema("graph", get_graph_schema_sql, get_graph_functions_sql)
    except ImportError:
        pass  # Extension not available


_register_builtin_extensions()
