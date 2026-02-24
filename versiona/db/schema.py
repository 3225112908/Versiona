"""
Versiona PostgreSQL Schema - Dual-dimension Context System.

Core Design:
1. Horizontal (tree): context_nodes table, parent_id forms tree structure
2. Vertical (version): context_versions table, each node has multiple versions
3. Git features: branches, commits, diffs
4. Dual-mode TTL: time expiration + turn expiration

Schema Design Principles:
- Use ltree for efficient tree queries
- Use JSONB for flexible data structures
- Use SQL Functions to encapsulate complex logic
- Support time TTL (real-time info) and turn TTL (Agent loop process data)

File Structure:
- tables.py: Table definitions
- functions.py: SQL function definitions
- schema.py: Entry point, aggregates tables and functions
"""

from __future__ import annotations

from typing import Callable, Any

from versiona.db.tables import get_tables_sql, get_table_names
from versiona.db.functions import get_functions_sql, get_function_names


# ============================================================
# Core Schema
# ============================================================

def get_schema_sql() -> str:
    """
    Get complete schema SQL (tables + functions).

    Returns:
        SQL string to create all tables and functions
    """
    return get_tables_sql() + "\n" + get_functions_sql()


# Re-export for backward compatibility
__all__ = [
    "get_schema_sql",
    "get_tables_sql",
    "get_functions_sql",
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
# Extension Registry
# ============================================================

# Registry for extension schemas
_EXTENSION_SCHEMAS: dict[str, Callable[..., str]] = {}
_EXTENSION_FUNCTIONS: dict[str, Callable[..., str]] = {}


def register_extension_schema(
    name: str,
    schema_fn: Callable[..., str],
    functions_fn: Callable[..., str] | None = None,
) -> None:
    """
    Register an extension's schema generator.

    Args:
        name: Extension name (e.g., "graph")
        schema_fn: Function that returns schema SQL
        functions_fn: Optional function that returns SQL functions

    Usage:
        from versiona.extensions.graph.schema import get_graph_schema_sql
        from versiona.extensions.graph.functions import get_graph_functions_sql

        register_extension_schema("graph", get_graph_schema_sql, get_graph_functions_sql)
    """
    _EXTENSION_SCHEMAS[name] = schema_fn
    if functions_fn:
        _EXTENSION_FUNCTIONS[name] = functions_fn


def get_extension_schema(name: str, **kwargs: Any) -> str:
    """
    Get an extension's schema SQL.

    Args:
        name: Extension name
        **kwargs: Arguments to pass to the schema function

    Returns:
        SQL string for creating extension tables
    """
    if name not in _EXTENSION_SCHEMAS:
        raise ValueError(f"Extension not registered: {name}")
    return _EXTENSION_SCHEMAS[name](**kwargs)


def get_extension_functions(name: str, **kwargs: Any) -> str:
    """
    Get an extension's SQL functions.

    Args:
        name: Extension name
        **kwargs: Arguments to pass to the functions function

    Returns:
        SQL string for creating extension functions
    """
    if name not in _EXTENSION_FUNCTIONS:
        return ""
    return _EXTENSION_FUNCTIONS[name](**kwargs)


def list_extensions() -> list[str]:
    """List all registered extensions."""
    return list(_EXTENSION_SCHEMAS.keys())


def get_full_schema_with_extensions(
    extensions: list[str] | None = None,
    extension_options: dict[str, dict[str, Any]] | None = None,
) -> str:
    """
    Get complete schema SQL including specified extensions.

    Args:
        extensions: List of extension names to include (None = core only)
        extension_options: Options to pass to each extension's schema generator
            e.g., {"graph": {"include_feedback": True}}

    Returns:
        Complete SQL string
    """
    sql_parts = [get_schema_sql()]
    extension_options = extension_options or {}

    if extensions:
        for ext_name in extensions:
            opts = extension_options.get(ext_name, {})

            # Add schema
            if ext_name in _EXTENSION_SCHEMAS:
                sql_parts.append(f"\n-- Extension: {ext_name}")
                sql_parts.append(get_extension_schema(ext_name, **opts))

            # Add functions
            if ext_name in _EXTENSION_FUNCTIONS:
                sql_parts.append(get_extension_functions(ext_name, **opts))

    return "\n".join(sql_parts)
