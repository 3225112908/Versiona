"""
Tool Calls and Data Cleanup Example

Demonstrates:
1. Tool call recording
2. Soft Delete vs Hard Delete
3. TTL auto-expiration
4. expire_by_turn turn-based cleanup
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

        ctx_id = f"agent_tool_demo_{timestamp}"
        await client.create_context(ctx_id, level=ContextLevel.PROJECT)
        print(f"✓ Created Context: {ctx_id}\n")

        # =========================================
        # 1. Tool Call Recording
        # =========================================
        print("=== Tool Call Recording ===")

        # Record thinking (expires after 3 turns)
        await client.set_local(
            ctx_id, "thinking",
            ["Analyzing user requirements", "Deciding to use search tool"],
            ttl_turns=3, current_turn=1
        )

        # Record tool calls
        await client.set_local(ctx_id, "tool_calls", [
            {"name": "web_search", "query": "Python best practices", "turn": 1}
        ])

        # Record tool results (expires after 5 turns)
        await client.set_local(
            ctx_id, "tool_results",
            [{"tool": "web_search", "results": ["result1", "result2", "result3"]}],
            ttl_turns=5, current_turn=1
        )

        await client.commit(ctx_id, message="Turn 1: Search executed")
        print("  Turn 1: Recorded thinking, tool_calls, tool_results")

        # =========================================
        # 2. Soft Delete - Mark as deleted but traceable
        # =========================================
        print("\n=== Soft Delete ===")

        # Assume we want to clean up some intermediate results
        await client.set_local(ctx_id, "intermediate_analysis", "This is intermediate analysis result")

        # Soft delete - mark as deleted
        await client.soft_delete(ctx_id, "intermediate_analysis")
        print("  ✓ Soft deleted 'intermediate_analysis'")

        # Try to read (should return None)
        value = await client.get_value(ctx_id, "intermediate_analysis")
        print(f"  Read result: {value}")  # None

        # But can still be traced in history after commit
        await client.commit(ctx_id, message="Soft deleted intermediate")

        # =========================================
        # 3. Hard Delete - Permanent deletion
        # =========================================
        print("\n=== Hard Delete ===")

        # Set sensitive data
        await client.set_local(ctx_id, "api_key", "sk-secret-xxx")
        await client.set_local(ctx_id, "password", "user_password_123")

        # Hard delete - permanently deleted, cannot be recovered
        await client.hard_delete(ctx_id, "api_key")
        await client.hard_delete(ctx_id, "password")
        print("  ✓ Hard deleted sensitive data")

        # =========================================
        # 4. TTL Auto-expiration
        # =========================================
        print("\n=== TTL Auto-expiration ===")

        # Time TTL (expires after 1 second, for demo only)
        await client.set(ctx_id, "short_lived", "This will expire soon", ttl_seconds=1)
        print("  Set short_lived (ttl: 1s)")

        value = await client.get_value(ctx_id, "short_lived")
        print(f"  Immediate read: {value}")

        await asyncio.sleep(1.5)

        value = await client.get_value(ctx_id, "short_lived")
        print(f"  Read after 1.5s: {value}")  # None

        # =========================================
        # 5. expire_by_turn Turn-based Cleanup
        # =========================================
        print("\n=== Turn-based Cleanup ===")

        # Set data with different TTLs
        await client.set(ctx_id, "data_ttl_2", "Expires after 2 turns", ttl_turns=2, current_turn=1)
        await client.set(ctx_id, "data_ttl_5", "Expires after 5 turns", ttl_turns=5, current_turn=1)

        print("  Turn 1: Set data_ttl_2 (expires turn 3) and data_ttl_5 (expires turn 6)")

        # Simulate Agent loop
        for turn in [2, 3, 4]:
            # Clean up expired data at the start of each turn
            expired_count = await client.expire_by_turn(ctx_id, turn)

            ttl2 = await client.get_value(ctx_id, "data_ttl_2", current_turn=turn)
            ttl5 = await client.get_value(ctx_id, "data_ttl_5", current_turn=turn)

            print(f"  Turn {turn}: data_ttl_2={ttl2 is not None}, data_ttl_5={ttl5 is not None}, expired={expired_count}")

        # =========================================
        # 6. Complete Agent Loop Example
        # =========================================
        print("\n=== Complete Agent Loop ===")

        loop_ctx = f"agent_loop_demo_{timestamp}"
        await client.create_context(loop_ctx, level=ContextLevel.PROJECT)

        max_turns = 5
        for turn in range(1, max_turns + 1):
            # Clean up expired data at the start of each turn
            await client.expire_by_turn(loop_ctx, turn)

            # Record thinking (TTL: 3 turns)
            await client.set_local(
                loop_ctx,
                f"thinking_turn_{turn}",
                f"Thinking process for turn {turn}",
                ttl_turns=3,
                current_turn=turn
            )

            # Assume task completed on turn 3
            if turn == 3:
                await client.set_output(loop_ctx, "summary", "Task completed!")
                await client.commit(loop_ctx, message=f"Turn {turn}: Task completed")
                print(f"  Turn {turn}: ✓ Task completed")
                break
            else:
                await client.commit(loop_ctx, message=f"Turn {turn}: In progress")
                print(f"  Turn {turn}: In progress...")

        # View final state
        data = await client.get(loop_ctx)
        print(f"\nFinal version: v{data.version}")
        print(f"Output: {data.output_data}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
