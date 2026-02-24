"""
Versiona Graph Extension - Symbol indexing and relationship graph.

This extension provides:
1. Symbol Index: Index and search symbols (functions, files, entities, etc.)
2. Symbol Edges: Track relationships between symbols (contains, references, etc.)
3. Context Views: Generate optimized context for LLMs
4. LLM Feedback: (Optional) Allow LLM to suggest corrections

Usage:

    from versiona import VersionaClient
    from versiona.extensions.graph import GraphExtension

    client = await VersionaClient.create(dsn)
    graph = GraphExtension(client)

    # Initialize schema
    await graph.init_schema()

    # Add symbols
    await graph.add_symbol(
        context_id="project_123",
        symbol_type="function",
        symbol_key="utils/helper.py::calculate",
        symbol_name="calculate",
        content="def calculate(x, y): ..."
    )

    # Search
    results = await graph.search("project_123", "calculate")

    # Traverse graph
    related = await graph.get_related(symbol_id, depth=2)

    # Generate context view
    view = await graph.generate_view("project_123", view_type="summary")
"""

from versiona.extensions.graph.types import (
    Symbol,
    SymbolType,
    SymbolTypeConfig,
    Edge,
    EdgeType,
    EdgeTypeConfig,
    SearchResult,
    TraversalResult,
    ContextView,
    Feedback,
    FeedbackType,
    FeedbackStatus,
    GraphConfig,
)
from versiona.extensions.graph.client import GraphExtension
from versiona.extensions.graph.schema import (
    get_graph_schema_sql,
    get_graph_table_names,
)
from versiona.extensions.graph.functions import (
    get_graph_functions_sql,
    get_graph_function_names,
)

__all__ = [
    # Client
    "GraphExtension",
    # Config
    "GraphConfig",
    # Types - Symbol
    "Symbol",
    "SymbolType",
    "SymbolTypeConfig",
    # Types - Edge
    "Edge",
    "EdgeType",
    "EdgeTypeConfig",
    # Types - Results
    "SearchResult",
    "TraversalResult",
    "ContextView",
    # Types - Feedback (optional)
    "Feedback",
    "FeedbackType",
    "FeedbackStatus",
    # Schema helpers
    "get_graph_schema_sql",
    "get_graph_table_names",
    "get_graph_functions_sql",
    "get_graph_function_names",
]
