"""
Game Save System Example

Demonstrates:
1. Game state saving
2. Auto-save (snapshots)
3. Multiple save slots (branches)
4. Save rollback
5. Game history replay
"""

import asyncio
import os
from versiona import VersionaClient, ContextLevel

# Read database connection from environment variable, defaults to local dev environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/versiona")


async def main():
    client = await VersionaClient.create(DATABASE_URL)

    try:
        await client.init_schema()

        # =========================================
        # 1. Create Player Save
        # =========================================
        print("=== Create Player Save ===")

        player_id = "player_hero_001"

        await client.create_context(
            player_id,
            level=ContextLevel.PROJECT,
            name="Hero Save",
            metadata={"game": "Versiona Quest", "player_name": "Hero"}
        )

        # Initial state
        await client.set_output(player_id, "player", {
            "name": "Hero",
            "class": "Warrior",
            "level": 1,
            "hp": 100,
            "max_hp": 100,
            "mp": 30,
            "max_mp": 30,
            "exp": 0,
            "gold": 100
        })

        await client.set_output(player_id, "stats", {
            "str": 10,
            "def": 8,
            "agi": 6,
            "int": 4
        })

        await client.set_output(player_id, "inventory", [
            {"id": "sword_wooden", "name": "Wooden Sword", "type": "weapon", "equipped": True},
            {"id": "potion_hp", "name": "HP Potion", "type": "consumable", "count": 3}
        ])

        await client.set_output(player_id, "position", {
            "map": "starting_village",
            "x": 100,
            "y": 100
        })

        await client.set_output(player_id, "quests", {
            "main_quest": {"id": "mq_001", "name": "First Steps", "status": "active"}
        })

        await client.commit(player_id, message="Game started")
        print("✓ Created new save")

        # =========================================
        # 2. Game Progress
        # =========================================
        print("\n=== Game Progress ===")

        # Complete tutorial
        await client.set_output(player_id, "quests", {
            "main_quest": {"id": "mq_001", "name": "First Steps", "status": "completed"},
            "mq_002": {"id": "mq_002", "name": "Journey to the Capital", "status": "active"}
        })
        await client.commit(player_id, message="Completed tutorial quest")
        print("✓ Completed tutorial quest")

        # Gain experience from battle
        player = {"name": "Hero", "class": "Warrior", "level": 3, "hp": 85, "max_hp": 120,
                  "mp": 35, "max_mp": 40, "exp": 450, "gold": 350}
        await client.set_output(player_id, "player", player)
        await client.set_output(player_id, "stats", {"str": 12, "def": 10, "agi": 7, "int": 5})
        await client.commit(player_id, message="Level up to Lv.3")
        print("✓ Level up to Lv.3")

        # Get new equipment
        inventory = [
            {"id": "sword_iron", "name": "Iron Sword", "type": "weapon", "equipped": True},
            {"id": "armor_leather", "name": "Leather Armor", "type": "armor", "equipped": True},
            {"id": "potion_hp", "name": "HP Potion", "type": "consumable", "count": 10}
        ]
        await client.set_output(player_id, "inventory", inventory)
        await client.commit(player_id, message="Obtained Iron Sword and Leather Armor")
        print("✓ Got new equipment")

        # =========================================
        # 3. Auto-save (Before Boss Battle)
        # =========================================
        print("\n=== Auto-save ===")

        # Move to Boss room
        await client.set_output(player_id, "position", {
            "map": "dark_cave",
            "x": 500,
            "y": 500
        })
        await client.commit(player_id, message="Entered Dark Cave")

        # Create auto-save
        auto_save = await client.create_snapshot(
            player_id,
            name="auto_save_boss",
            snapshot_type="auto",
            message="Auto-save: Before Boss battle"
        )
        print(f"✓ Auto-save: {auto_save[:16]}...")

        # =========================================
        # 4. Boss Battle Failed
        # =========================================
        print("\n=== Boss Battle ===")

        # Injured in battle
        player["hp"] = 0
        await client.set_output(player_id, "player", player)
        await client.commit(player_id, message="Defeated by Boss")
        print("✗ Defeated by Boss!")

        # Check current status
        current = await client.get(player_id)
        print(f"Current HP: {current.output_data['player']['hp']}")

        # =========================================
        # 5. Restore Auto-save
        # =========================================
        print("\n=== Restore Save ===")

        restored = await client.restore_snapshot(auto_save)
        print(f"✓ Restored {restored} nodes")

        # Check restored status
        after_restore = await client.get(player_id)
        print(f"HP after restore: {after_restore.output_data['player']['hp']}")
        print(f"Position: {after_restore.output_data['position']}")

        # =========================================
        # 6. Multiple Save Slots (Branches)
        # =========================================
        print("\n=== Multiple Save Slots ===")

        # Create new save slot
        slot2 = await client.create_branch(player_id, "save_slot_2")
        print(f"✓ Created save slot 2: {slot2.name}")

        # Switch to new save slot
        await client.switch_branch(player_id, "save_slot_2")
        print("✓ Switched to save slot 2")

        # Make different choices in new save slot
        await client.set_output(player_id, "player", {
            **player, "class": "Mage", "hp": 70, "max_hp": 80, "mp": 100, "max_mp": 100
        })
        await client.set_output(player_id, "stats", {"str": 5, "def": 4, "agi": 6, "int": 15})
        await client.commit(player_id, message="Changed class to Mage")
        print("✓ Changed to Mage in save slot 2")

        # Switch back to main save
        await client.switch_branch(player_id, "main")
        main_save = await client.get(player_id)
        print(f"✓ Switched back to main save, class: {main_save.output_data['player']['class']}")

        # List all save slots
        branches = await client.list_branches(player_id)
        print(f"\nSave slot list: {[b.name for b in branches]}")

        # =========================================
        # 7. Game History
        # =========================================
        print("\n=== Game History ===")

        history = await client.get_history(player_id, limit=10)
        print("Recent save points:")
        for h in history:
            print(f"  v{h['version']}: {h.get('message', 'N/A')}")

        # =========================================
        # 8. Milestone Tags
        # =========================================
        print("\n=== Milestone Tags ===")

        await client.create_tag(player_id, "chapter_1_complete", message="Chapter 1 completed")
        await client.create_tag(player_id, "first_boss_defeated", message="First Boss defeated")

        tags = await client.list_tags(player_id)
        print("Milestones:")
        for tag in tags:
            print(f"  - {tag.name}: v{tag.version}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
