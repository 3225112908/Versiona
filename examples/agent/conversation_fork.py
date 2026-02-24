"""
Conversation Fork (Fork Session) Example

Demonstrates:
1. Record conversation history
2. Fork from any turn
3. Explore different paths in parallel
4. Independence between branches
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
        # 1. Create Original Conversation
        # =========================================
        print("=== Original Conversation ===")

        session_id = f"conversation_{timestamp}"
        await client.create_context(
            session_id,
            level=ContextLevel.PROJECT,
            name="Original Conversation",
            metadata={"type": "chat", "user_id": "user_123"}
        )

        # Turn 1
        await client.set(session_id, "turn_1_user", "Help me write a sorting function", current_turn=1)
        await client.set(session_id, "turn_1_assistant", "Sure, what sorting algorithm would you like? Quick sort, merge sort, or bubble sort?", current_turn=1)
        await client.commit(session_id, "Turn 1")
        print("Turn 1: User requests sorting function")

        # Turn 2
        await client.set(session_id, "turn_2_user", "Quick sort", current_turn=2)
        await client.set(
            session_id, "turn_2_assistant",
            """Sure, here's the quick sort implementation:

```python
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
```""",
            current_turn=2
        )
        await client.commit(session_id, "Turn 2")
        print("Turn 2: Provided quick sort")

        # Turn 3
        await client.set(session_id, "turn_3_user", "Can you make it in-place?", current_turn=3)
        await client.set(
            session_id, "turn_3_assistant",
            """Of course! Here's the in-place quick sort:

```python
def quicksort_inplace(arr, low=0, high=None):
    if high is None:
        high = len(arr) - 1
    if low < high:
        pi = partition(arr, low, high)
        quicksort_inplace(arr, low, pi - 1)
        quicksort_inplace(arr, pi + 1, high)
```""",
            current_turn=3
        )
        await client.commit(session_id, "Turn 3")
        print("Turn 3: In-place quick sort")

        # Turn 4
        await client.set(session_id, "turn_4_user", "Add type annotations", current_turn=4)
        await client.commit(session_id, "Turn 4")
        print("Turn 4: Request to add type annotations")

        # =========================================
        # 2. Branch from Turn 2 (Explore Merge Sort)
        # =========================================
        print("\n=== Branch from Turn 2 ===")

        branch_merge = await client.fork_session(
            session_id,
            f"conversation_{timestamp}_merge",
            fork_at_turn=2,
            name="Explore Merge Sort"
        )
        print(f"Created branch: {branch_merge}")

        # Verify branch contains Turn 1, 2
        turn1 = await client.get_value(branch_merge, "turn_1_user")
        turn2 = await client.get_value(branch_merge, "turn_2_user")
        turn3 = await client.get_value(branch_merge, "turn_3_user")

        print(f"  Turn 1 exists: {turn1 is not None}")  # True
        print(f"  Turn 2 exists: {turn2 is not None}")  # True
        print(f"  Turn 3 exists: {turn3 is not None}")  # False (truncated)

        # Explore merge sort in branch
        await client.set(branch_merge, "turn_3_user", "Let's use merge sort instead", current_turn=3)
        await client.set(
            branch_merge, "turn_3_assistant",
            """Sure, here's merge sort:

```python
def mergesort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left = mergesort(arr[:mid])
    right = mergesort(arr[mid:])
    return merge(left, right)
```""",
            current_turn=3
        )
        await client.commit(branch_merge, "Turn 3: Merge sort")
        print("  Turn 3': Explored merge sort")

        # =========================================
        # 3. Branch from Turn 1 (Completely Different Direction)
        # =========================================
        print("\n=== Branch from Turn 1 ===")

        branch_bubble = await client.fork_session(
            session_id,
            f"conversation_{timestamp}_bubble",
            fork_at_turn=1,
            name="Explore Bubble Sort"
        )
        print(f"Created branch: {branch_bubble}")

        # Completely different conversation
        await client.set(branch_bubble, "turn_2_user", "Bubble sort", current_turn=2)
        await client.set(
            branch_bubble, "turn_2_assistant",
            """Sure, here's bubble sort:

```python
def bubblesort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n-i-1):
            if arr[j] > arr[j+1]:
                arr[j], arr[j+1] = arr[j+1], arr[j]
    return arr
```""",
            current_turn=2
        )
        await client.commit(branch_bubble, "Turn 2: Bubble sort")
        print("  Turn 2': Explored bubble sort")

        # =========================================
        # 4. Compare Three Branches
        # =========================================
        print("\n=== Branch Comparison ===")

        sessions = [
            (session_id, "Original Conversation"),
            (branch_merge, "Merge Sort Branch"),
            (branch_bubble, "Bubble Sort Branch")
        ]

        for sid, name in sessions:
            history = await client.get_history(sid)
            node = await client.get_node(sid)

            print(f"\n{name} ({sid}):")
            print(f"  Version count: {len(history)}")
            print(f"  Current version: v{node.current_version}")

            # List conversation content
            all_kv = await client.get_all(sid)
            turns = sorted([kv["key"] for kv in all_kv if kv["key"].startswith("turn_")])
            print(f"  Conversation turns: {', '.join(turns)}")

        # =========================================
        # 5. Independence Verification
        # =========================================
        print("\n=== Independence Verification ===")

        # Add to original conversation
        await client.set(session_id, "turn_5_user", "Thanks!", current_turn=5)
        await client.commit(session_id, "Turn 5")
        print("Original conversation added Turn 5")

        # Branch should not be affected
        turn5_in_branch = await client.get_value(branch_merge, "turn_5_user")
        print(f"Turn 5 in merge sort branch: {turn5_in_branch}")  # None

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
