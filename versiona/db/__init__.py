"""
Versiona database module - PostgreSQL integration.

File structure:
- tables.py: Table definitions (context_nodes, context_versions, context_kv, etc.)
- functions.py: SQL function definitions (create_context_node, kv_set, etc.)
- schema.py: Entry point, aggregates tables and functions + Extension Registry
"""

from versiona.db.schema import (
    # Core schema
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

from versiona.db.tables import get_tables_sql
from versiona.db.functions import get_functions_sql

__all__ = [
    # Core
    "get_schema_sql",
    "get_tables_sql",
    "get_functions_sql",
    "get_table_names",
    "get_function_names",
    # Extensions
    "register_extension_schema",
    "get_extension_schema",
    "get_extension_functions",
    "list_extensions",
    "get_full_schema_with_extensions",
]
