"""
System Snapshot and Restore Example

Demonstrates:
1. Create system snapshots
2. Make changes
3. Restore from snapshot
4. Snapshot management
"""

import asyncio
import os
from datetime import datetime
from versiona import VersionaClient, ContextLevel

# Read database connection from environment variable, defaults to local dev environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/versiona")


async def main():
    client = await VersionaClient.create(DATABASE_URL)

    try:
        await client.init_schema()

        # Use timestamp to ensure unique ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # =========================================
        # 1. Build Agent System (Multi-node)
        # =========================================
        print("=== Build Agent System ===")

        # Project
        project_id = f"project_snapshot_demo_{timestamp}"
        await client.create_context(project_id, level=ContextLevel.PROJECT, name="Snapshot Demo Project")
        await client.set_output(project_id, "config", {"env": "production", "version": "1.0"})
        await client.commit(project_id, "Initial config")
        print(f"✓ Created Project: {project_id}")

        # Task A
        task_a = await client.fork(project_id, f"task_a_{timestamp}", level=ContextLevel.TASK)
        await client.set_output(task_a, "status", "completed")
        await client.set_output(task_a, "result", {"score": 95})
        await client.commit(task_a, "Task A completed")
        print(f"✓ Created Task A: {task_a}")

        # Task B
        task_b = await client.fork(project_id, f"task_b_{timestamp}", level=ContextLevel.TASK)
        await client.set_output(task_b, "status", "completed")
        await client.set_output(task_b, "result", {"score": 88})
        await client.commit(task_b, "Task B completed")
        print(f"✓ Created Task B: {task_b}")

        # SubAgent
        sub_agent = await client.fork(task_a, f"sub_agent_1_{timestamp}", level=ContextLevel.EXECUTION)
        await client.set_output(sub_agent, "analysis", "Deep analysis result")
        await client.commit(sub_agent, "SubAgent analysis")
        print(f"✓ Created SubAgent: {sub_agent}")

        # =========================================
        # 2. Create Snapshot
        # =========================================
        print("\n=== Create Snapshot ===")

        snapshot_id = await client.create_snapshot(
            project_id,
            name="before_experiment",
            message="Stable state before experiment"
        )
        print(f"✓ Created snapshot: {snapshot_id}")

        # View snapshot details
        snapshot = await client.get_snapshot(snapshot_id)
        print(f"  Snapshot name: {snapshot['name']}")
        print(f"  Node count: {len(snapshot['node_versions'])}")
        print("  Node versions:")
        for node_id, version in snapshot['node_versions'].items():
            print(f"    {node_id}: v{version}")

        # =========================================
        # 3. Make Risky Changes
        # =========================================
        print("\n=== Make Changes ===")

        # Modify Project config
        await client.set_output(project_id, "config", {"env": "experimental", "version": "2.0-beta"})
        await client.commit(project_id, "Switch to experimental")
        print("✓ Modified Project config -> experimental")

        # Modify Task A result
        await client.set_output(task_a, "result", {"score": 0, "error": "Experiment failed"})
        await client.commit(task_a, "Experiment failed")
        print("✓ Modified Task A result -> failed")

        # Delete SubAgent data
        await client.soft_delete(sub_agent, "analysis")
        await client.commit(sub_agent, "Clear analysis")
        print("✓ Deleted SubAgent analysis")

        # View current state
        print("\n--- State After Changes ---")
        project_data = await client.get(project_id)
        task_a_data = await client.get(task_a)
        sub_data = await client.get(sub_agent)

        print(f"Project config: {project_data.output_data.get('config')}")
        print(f"Task A result: {task_a_data.output_data.get('result')}")
        print(f"SubAgent analysis: {sub_data.output_data.get('analysis')}")

        # =========================================
        # 4. Restore Snapshot
        # =========================================
        print("\n=== Restore Snapshot ===")

        restored_count = await client.restore_snapshot(snapshot_id)
        print(f"✓ Restored {restored_count} nodes")

        # View state after restore
        print("\n--- State After Restore ---")
        project_data = await client.get(project_id)
        task_a_data = await client.get(task_a)
        sub_data = await client.get(sub_agent)

        print(f"Project config: {project_data.output_data.get('config')}")
        print(f"Task A result: {task_a_data.output_data.get('result')}")
        print(f"SubAgent analysis: {sub_data.output_data.get('analysis')}")

        # =========================================
        # 5. Snapshot Management
        # =========================================
        print("\n=== Snapshot Management ===")

        # Create more snapshots
        await client.set_output(project_id, "status", "phase_1")
        await client.commit(project_id, "Phase 1")
        snap_1 = await client.create_snapshot(project_id, name="phase_1_complete")

        await client.set_output(project_id, "status", "phase_2")
        await client.commit(project_id, "Phase 2")
        snap_2 = await client.create_snapshot(project_id, name="phase_2_complete")

        # List all snapshots
        snapshots = await client.list_snapshots(project_id)
        print(f"Snapshot list ({len(snapshots)} total):")
        for s in snapshots:
            print(f"  - {s['name']} (ID: {s['id'][:8]}..., Created: {s['created_at'][:19]})")

        # Delete snapshot
        await client.delete_snapshot(snap_2)
        print("\n✓ Deleted snapshot: phase_2_complete")

        # List again
        snapshots = await client.list_snapshots(project_id)
        print(f"Remaining snapshots: {[s['name'] for s in snapshots]}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
