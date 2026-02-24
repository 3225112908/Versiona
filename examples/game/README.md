# Game Save and State Management

This example demonstrates how to use Versiona for game save management:

- **Game Saves**: Player progress version control
- **Auto-Save (Snapshots)**: Automatic saves before battles
- **Replay System**: Replay game history
- **Multiple Save Slots**: Use branches for multiple saves

## Files

| File | Description |
|------|-------------|
| `game_save.py` | Game save system |

## Quick Start

```bash
# Install dependencies
pip install versiona asyncpg

# Set environment variable
export DATABASE_URL=postgresql://localhost:5432/versiona

# Run example
python game_save.py
```

## Core Concepts

### Save Structure

```python
# Game state
await client.set_output(save_id, "player", {
    "name": "Hero",
    "level": 15,
    "hp": 100,
    "mp": 50,
    "exp": 12500,
    "gold": 5000
})

await client.set_output(save_id, "inventory", [
    {"id": "sword_01", "name": "Hero's Sword", "equipped": True},
    {"id": "potion_hp", "name": "HP Potion", "count": 10}
])

await client.set_output(save_id, "position", {
    "map": "castle_town",
    "x": 150,
    "y": 200
})
```

### Auto-Save (Snapshot)

```python
# Auto-save before boss battle
snapshot_id = await client.create_snapshot(
    save_id,
    name="before_boss_battle",
    snapshot_type="auto",
    message="Auto-save: Entering Boss Battle"
)

# Restore after defeat
await client.restore_snapshot(snapshot_id)
```

### Multiple Save Slots (Branches)

```python
# Create new save slot
await client.create_branch(player_id, "save_slot_2")

# Switch save slot
await client.switch_branch(player_id, "save_slot_2")
```
