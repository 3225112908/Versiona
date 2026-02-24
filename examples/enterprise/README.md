# Enterprise Data Version Control

This example demonstrates how to use Versiona for enterprise-level data auditing:

- **Order Tracking**: Complete order status change history
- **Audit Logs**: Who changed what and when
- **Data Rollback**: Revert to any historical version
- **Branch Approval**: Branch review workflow for modifications

## Files

| File | Description |
|------|-------------|
| `order_tracking.py` | Order status tracking and audit |

## Quick Start

```bash
# Install dependencies
pip install versiona asyncpg

# Set environment variable
export DATABASE_URL=postgresql://localhost:5432/versiona

# Run example
python order_tracking.py
```

## Core Concepts

### Audit Trail

```python
# Record author for every modification
await client.commit(
    order_id,
    message="Status update: pending -> paid",
    author_id="user_123"
)

# View complete history
history = await client.get_history(order_id)
for h in history:
    print(f"v{h['version']}: {h['message']} by {h['author_id']} at {h['created_at']}")
```

### Diff Comparison

```python
# Compare any two versions
diff = await client.diff(order_id, 1, 5)

print("Added:", diff.added)
print("Removed:", diff.removed)
print("Modified:", diff.modified)
```

### Branch Approval

```python
# Create modification proposal branch
await client.create_branch(order_id, "price_adjustment")
await client.switch_branch(order_id, "price_adjustment")

# Modify on branch
await client.set_output(order_id, "total", 999.00)
await client.commit(order_id, "Adjust price")

# Merge to main after approval
await client.switch_branch(order_id, "main")
# ... merge logic
```
