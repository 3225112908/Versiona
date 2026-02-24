"""
Order Tracking and Audit Example

Demonstrates:
1. Order lifecycle management
2. Status change tracking
3. Audit logging
4. Version comparison
5. Data rollback
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

        # =========================================
        # 1. Create Order
        # =========================================
        print("=== Create Order ===")

        order_id = f"order_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        await client.create_context(
            order_id,
            level=ContextLevel.PROJECT,
            name=f"Order {order_id}",
            metadata={
                "type": "order",
                "customer_id": "cust_001",
                "created_by": "system"
            }
        )

        # Initial order data
        await client.set_output(order_id, "status", "pending")
        await client.set_output(order_id, "items", [
            {"product": "iPhone 15 Pro", "qty": 1, "price": 999.00},
            {"product": "AirPods Pro", "qty": 2, "price": 249.00}
        ])
        await client.set_output(order_id, "total", 1497.00)
        await client.set_output(order_id, "shipping_address", {
            "name": "John Doe",
            "address": "123 Main Street, New York, NY 10001",
            "phone": "555-123-4567"
        })

        await client.commit(order_id, message="Order created", author_id="system")
        print(f"✓ Created order: {order_id}")

        # =========================================
        # 2. Order Status Updates
        # =========================================
        print("\n=== Order Status Updates ===")

        # Payment
        await client.set_output(order_id, "status", "paid")
        await client.set_output(order_id, "payment", {
            "method": "credit_card",
            "amount": 1497.00,
            "paid_at": datetime.now().isoformat()
        })
        await client.commit(order_id, message="Payment completed", author_id="payment_system")
        print("✓ Status: pending -> paid")

        # Shipped
        await client.set_output(order_id, "status", "shipped")
        await client.set_output(order_id, "shipping", {
            "carrier": "FedEx",
            "tracking_number": "FX123456789",
            "shipped_at": datetime.now().isoformat()
        })
        await client.commit(order_id, message="Shipped", author_id="warehouse_001")
        print("✓ Status: paid -> shipped")

        # In transit
        await client.set_output(order_id, "status", "in_transit")
        await client.set_output(order_id, "shipping.location", "Distribution Center")
        await client.commit(order_id, message="In transit", author_id="logistics")
        print("✓ Status: shipped -> in_transit")

        # Delivered
        await client.set_output(order_id, "status", "delivered")
        await client.set_output(order_id, "shipping.delivered_at", datetime.now().isoformat())
        await client.commit(order_id, message="Delivered", author_id="delivery_001")
        print("✓ Status: in_transit -> delivered")

        # =========================================
        # 3. View Audit Log
        # =========================================
        print("\n=== Audit Log ===")

        history = await client.get_history(order_id)
        print(f"Total {len(history)} versions:\n")

        for h in history:
            created = h["created_at"][:19] if h.get("created_at") else "N/A"
            author = h.get("author_id") or "unknown"
            message = h.get("message") or "No message"
            print(f"  v{h['version']:2d} | {created} | {author:15s} | {message}")

        # =========================================
        # 4. Version Comparison (Diff)
        # =========================================
        print("\n=== Version Comparison ===")

        # Compare initial version and final version
        diff = await client.diff(order_id, 1, len(history))

        print(f"v1 -> v{len(history)} changes:")

        if diff.added:
            print("\nAdded fields:")
            for key, value in diff.added.items():
                print(f"  + {key}: {value}")

        if diff.modified:
            print("\nModified fields:")
            for key, change in diff.modified.items():
                print(f"  ~ {key}:")
                print(f"    Old: {change.get('old')}")
                print(f"    New: {change.get('new')}")

        # =========================================
        # 5. View Specific Version
        # =========================================
        print("\n=== View Specific Version ===")

        # View status before payment (v1)
        v1_data = await client.get(order_id, version=1)
        print(f"v1 (before payment) status: {v1_data.output_data.get('status')}")

        # View status after shipping (v3)
        v3_data = await client.get(order_id, version=3)
        print(f"v3 (after shipping) status: {v3_data.output_data.get('status')}")

        # Current status
        current = await client.get(order_id)
        print(f"Current status: {current.output_data.get('status')}")

        # =========================================
        # 6. Data Rollback Example
        # =========================================
        print("\n=== Data Rollback ===")

        # Assume shipping error discovered, need to rollback to payment completed state
        print("Scenario: Shipping address error discovered, need to rollback to payment completed state")

        # Use revert (creates new version)
        new_version = await client.revert(
            order_id,
            version=2,  # Rollback to v2 (payment completed)
            message="Rollback: Shipping address error, needs reprocessing"
        )

        print(f"✓ Rollback completed, new version: v{new_version}")

        # View status after rollback
        reverted = await client.get(order_id)
        print(f"Status after rollback: {reverted.output_data.get('status')}")

        # View history again
        print("\nVersion history after rollback:")
        history = await client.get_history(order_id, limit=3)
        for h in history:
            print(f"  v{h['version']}: {h.get('message', 'N/A')}")

        # =========================================
        # 7. Tag Management
        # =========================================
        print("\n=== Tag Management ===")

        # Tag important versions
        await client.create_tag(order_id, "payment_complete", version=2, message="Payment completed milestone")
        await client.create_tag(order_id, "shipped", version=3, message="Shipped milestone")

        tags = await client.list_tags(order_id)
        print("Tag list:")
        for tag in tags:
            print(f"  - {tag.name}: v{tag.version} ({tag.message})")

        # Quick jump to tag
        await client.checkout_tag(order_id, "payment_complete")
        data = await client.get(order_id)
        print(f"\nSwitched to 'payment_complete' tag, status: {data.output_data.get('status')}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
