"""Versiona core protocols - interfaces for version control operations."""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol
from uuid import UUID

from versiona.core.types import (
    Branch,
    Commit,
    DiffResult,
    MergeResult,
    Object,
    ObjectType,
    Repository,
    RowChange,
    TableSchema,
)


class ObjectStoreProtocol(Protocol):
    """
    Content-addressable object storage protocol.

    Objects are stored by their content hash (SHA-256).
    Automatic deduplication is achieved through content addressing.
    """

    async def put(self, data: bytes, type: ObjectType) -> bytes:
        """
        Store an object and return its hash.

        Args:
            data: Raw bytes to store
            type: Type of object

        Returns:
            SHA-256 hash of the content
        """
        ...

    async def get(self, hash: bytes) -> Object | None:
        """
        Retrieve an object by its hash.

        Args:
            hash: SHA-256 hash of the object

        Returns:
            Object if found, None otherwise
        """
        ...

    async def exists(self, hash: bytes) -> bool:
        """Check if an object exists."""
        ...

    async def delete(self, hash: bytes) -> bool:
        """
        Delete an object (for GC).

        Returns:
            True if deleted, False if not found
        """
        ...


class RepositoryProtocol(Protocol):
    """
    Repository management protocol.

    A repository contains branches, commits, and versioned tables.
    """

    # Repository CRUD
    async def create(self, name: str, description: str | None = None) -> Repository:
        """Create a new repository."""
        ...

    async def get(self, name: str) -> Repository | None:
        """Get repository by name."""
        ...

    async def get_by_id(self, id: UUID) -> Repository | None:
        """Get repository by ID."""
        ...

    async def list(self) -> list[Repository]:
        """List all repositories."""
        ...

    async def delete(self, name: str) -> bool:
        """Delete a repository and all its data."""
        ...

    # Branch operations
    async def create_branch(
        self,
        repo: str | UUID,
        name: str,
        from_branch: str | None = None,
        from_commit: bytes | None = None,
    ) -> Branch:
        """
        Create a new branch.

        Args:
            repo: Repository name or ID
            name: Branch name
            from_branch: Create from this branch's HEAD (default: default branch)
            from_commit: Create from this specific commit
        """
        ...

    async def get_branch(self, repo: str | UUID, name: str) -> Branch | None:
        """Get a branch by name."""
        ...

    async def list_branches(self, repo: str | UUID) -> list[Branch]:
        """List all branches in a repository."""
        ...

    async def delete_branch(self, repo: str | UUID, name: str) -> bool:
        """Delete a branch."""
        ...


class VersionControlProtocol(Protocol):
    """
    Git-like version control operations.

    This is the main interface for commit, checkout, merge, diff operations.
    """

    # Commit operations
    async def commit(
        self,
        repo: str | UUID,
        branch: str,
        message: str | None = None,
        author: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Commit:
        """
        Commit all staged changes on a branch.

        Args:
            repo: Repository name or ID
            branch: Branch name
            message: Commit message
            author: Author information
            metadata: Additional metadata

        Returns:
            The created commit
        """
        ...

    async def get_commit(self, repo: str | UUID, hash: bytes) -> Commit | None:
        """Get a commit by its hash."""
        ...

    async def log(
        self,
        repo: str | UUID,
        branch: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Commit]:
        """
        Get commit history.

        Args:
            repo: Repository name or ID
            branch: Branch name (default: default branch)
            limit: Maximum number of commits to return
            offset: Skip this many commits
        """
        ...

    # Checkout
    async def checkout(
        self,
        repo: str | UUID,
        target: str | bytes,
    ) -> Commit:
        """
        Checkout a branch or commit.

        Args:
            repo: Repository name or ID
            target: Branch name or commit hash

        Returns:
            The commit that is now checked out
        """
        ...

    # Diff
    async def diff(
        self,
        repo: str | UUID,
        from_ref: str | bytes,
        to_ref: str | bytes,
    ) -> DiffResult:
        """
        Compare two refs (branches or commits).

        Args:
            repo: Repository name or ID
            from_ref: Source branch name or commit hash
            to_ref: Target branch name or commit hash
        """
        ...

    # Merge
    async def merge(
        self,
        repo: str | UUID,
        source_branch: str,
        target_branch: str,
        message: str | None = None,
        author: dict[str, Any] | None = None,
    ) -> MergeResult:
        """
        Merge source branch into target branch.

        Args:
            repo: Repository name or ID
            source_branch: Branch to merge from
            target_branch: Branch to merge into
            message: Merge commit message
            author: Author information
        """
        ...

    # Revert
    async def revert(
        self,
        repo: str | UUID,
        branch: str,
        commit_hash: bytes,
        message: str | None = None,
    ) -> Commit:
        """
        Revert a commit by creating a new commit that undoes its changes.

        Args:
            repo: Repository name or ID
            branch: Branch name
            commit_hash: Commit to revert
            message: Revert commit message
        """
        ...


class VersionedTableProtocol(Protocol):
    """
    Protocol for versioned table operations.

    Tables can be created within a repository and their changes
    are tracked through commits.
    """

    # Table management
    async def create_table(
        self,
        repo: str | UUID,
        schema: TableSchema,
    ) -> str:
        """
        Create a versioned table.

        Args:
            repo: Repository name or ID
            schema: Table schema definition

        Returns:
            Full table name (v_repo_{repo_id}_{table_name})
        """
        ...

    async def drop_table(
        self,
        repo: str | UUID,
        table_name: str,
    ) -> bool:
        """Drop a versioned table."""
        ...

    async def list_tables(self, repo: str | UUID) -> list[str]:
        """List all versioned tables in a repository."""
        ...

    # Row operations (working on current branch)
    async def insert(
        self,
        repo: str | UUID,
        table: str,
        data: dict[str, Any],
        branch: str | None = None,
    ) -> UUID:
        """
        Insert a row into a versioned table.

        Args:
            repo: Repository name or ID
            table: Table name
            data: Row data
            branch: Branch to insert on (default: checked out branch)

        Returns:
            Row ID
        """
        ...

    async def update(
        self,
        repo: str | UUID,
        table: str,
        row_id: UUID,
        data: dict[str, Any],
        branch: str | None = None,
    ) -> bool:
        """Update a row in a versioned table."""
        ...

    async def delete(
        self,
        repo: str | UUID,
        table: str,
        row_id: UUID,
        branch: str | None = None,
    ) -> bool:
        """Delete a row from a versioned table."""
        ...

    async def get(
        self,
        repo: str | UUID,
        table: str,
        row_id: UUID,
        branch: str | None = None,
        as_of: bytes | None = None,
    ) -> dict[str, Any] | None:
        """
        Get a row by ID.

        Args:
            repo: Repository name or ID
            table: Table name
            row_id: Row ID
            branch: Branch to query (default: checked out branch)
            as_of: Get data as of this commit hash (time travel)
        """
        ...

    async def query(
        self,
        repo: str | UUID,
        table: str,
        filters: dict[str, Any] | None = None,
        branch: str | None = None,
        as_of: bytes | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Query rows from a versioned table.

        Args:
            repo: Repository name or ID
            table: Table name
            filters: Filter conditions (simple equality for now)
            branch: Branch to query
            as_of: Query as of this commit hash (time travel)
            limit: Maximum rows to return
            offset: Skip this many rows
        """
        ...

    async def history(
        self,
        repo: str | UUID,
        table: str,
        row_id: UUID,
    ) -> list[RowChange]:
        """Get change history for a specific row."""
        ...

    async def uncommitted_changes(
        self,
        repo: str | UUID,
        branch: str | None = None,
    ) -> list[RowChange]:
        """Get all uncommitted changes on a branch."""
        ...


class SearchProtocol(Protocol):
    """
    Search protocol (optional plugin).

    Provides full-text search and fuzzy search capabilities.
    """

    async def search(
        self,
        repo: str | UUID,
        query: str,
        tables: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Search across versioned tables.

        Args:
            repo: Repository name or ID
            query: Search query
            tables: Tables to search (default: all)
            limit: Maximum results
        """
        ...

    async def index(
        self,
        repo: str | UUID,
        table: str,
        columns: list[str],
    ) -> bool:
        """Create search index on specified columns."""
        ...


class LifecycleProtocol(Protocol):
    """
    Lifecycle management protocol (optional plugin).

    Handles TTL, GC, archival, and other lifecycle operations.
    """

    async def set_ttl(
        self,
        repo: str | UUID,
        record_type: str,
        ttl_seconds: int | None,
        on_expire: str = "soft_delete",  # 'soft_delete', 'hard_delete', 'archive'
    ) -> bool:
        """Set TTL policy for a record type."""
        ...

    async def run_gc(
        self,
        repo: str | UUID,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Run garbage collection.

        Returns:
            Statistics about what was (or would be) cleaned
        """
        ...

    async def archive(
        self,
        repo: str | UUID,
        before: bytes,  # Commit hash - archive everything before this
    ) -> dict[str, Any]:
        """Archive old commits and their data."""
        ...
