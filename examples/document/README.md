# Document Version Control

This example demonstrates how to use Versiona for document version management:

- **Document Editing**: Content modification and version tracking
- **Branch Collaboration**: Multi-person collaboration workflow
- **Undo/Redo**: Undo and redo functionality
- **History Comparison**: View document changes

## Files

| File | Description |
|------|-------------|
| `document_editing.py` | Basic document editing and version control |

## Quick Start

```bash
# Install dependencies
pip install versiona asyncpg

# Set environment variable
export DATABASE_URL=postgresql://localhost:5432/versiona

# Run example
python document_editing.py
```

## Core Concepts

### Version Creation

```python
# Create version after modifying content
await client.set_output(doc_id, "content", "New content")
await client.commit(doc_id, message="Update content")

# View history
history = await client.get_history(doc_id)
```

### Branch Collaboration

```python
# Create editing branch
await client.create_branch(doc_id, "edit-intro")

# Switch to branch
await client.switch_branch(doc_id, "edit-intro")

# Edit and commit
await client.set_output(doc_id, "content", "Modifications on branch")
await client.commit(doc_id, "Edit introduction")

# Merge after review
await client.switch_branch(doc_id, "main")
```

### Undo/Redo

```python
# Use checkout to implement Undo
current_version = 5
await client.checkout(doc_id, current_version - 1)  # Undo

# Use checkout to implement Redo
await client.checkout(doc_id, current_version)  # Redo
```
