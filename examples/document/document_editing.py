"""
Document Editing and Version Control Example

Demonstrates:
1. Create document
2. Edit and version tracking
3. View history
4. Version comparison
5. Revert to old version
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
        # 1. Create Document
        # =========================================
        print("=== Create Document ===")

        doc_id = "doc_project_readme"

        await client.create_context(
            doc_id,
            level=ContextLevel.PROJECT,
            name="Project README",
            metadata={"type": "document", "format": "markdown"}
        )

        # Initial content
        await client.set_output(doc_id, "title", "My Awesome Project")
        await client.set_output(doc_id, "content", """# My Awesome Project

This is the initial version of the README.

## Features

- Feature 1
- Feature 2
""")
        await client.set_output(doc_id, "author", "Alice")
        await client.set_output(doc_id, "tags", ["python", "open-source"])

        await client.commit(doc_id, message="Initial draft", author_id="alice")
        print(f"✓ Created document: {doc_id}")

        # =========================================
        # 2. Edit Document
        # =========================================
        print("\n=== Edit Document ===")

        # First edit - Add installation instructions
        content_v2 = """# My Awesome Project

This is the initial version of the README.

## Features

- Feature 1
- Feature 2
- Feature 3 (NEW!)

## Installation

```bash
pip install my-awesome-project
```
"""
        await client.set_output(doc_id, "content", content_v2)
        await client.commit(doc_id, message="Add installation section", author_id="bob")
        print("✓ v2: Added installation instructions")

        # Second edit - Add usage example
        content_v3 = content_v2 + """
## Usage

```python
from my_awesome_project import awesome

awesome.do_something()
```
"""
        await client.set_output(doc_id, "content", content_v3)
        await client.commit(doc_id, message="Add usage example", author_id="alice")
        print("✓ v3: Added usage example")

        # Third edit - Update title
        await client.set_output(doc_id, "title", "My Super Awesome Project")
        await client.commit(doc_id, message="Update title", author_id="alice")
        print("✓ v4: Updated title")

        # =========================================
        # 3. View History
        # =========================================
        print("\n=== Version History ===")

        history = await client.get_history(doc_id)
        for h in history:
            author = h.get("author_id", "unknown")
            message = h.get("message", "")
            print(f"  v{h['version']}: {message} (by {author})")

        # =========================================
        # 4. Version Comparison
        # =========================================
        print("\n=== Version Comparison ===")

        # Compare v1 and v4
        diff = await client.diff(doc_id, 1, 4)

        print("v1 -> v4 changes:")
        if diff.modified:
            for key, change in diff.modified.items():
                old_val = str(change.get("old", ""))[:50]
                new_val = str(change.get("new", ""))[:50]
                print(f"  {key}:")
                print(f"    Old: {old_val}...")
                print(f"    New: {new_val}...")

        # =========================================
        # 5. View Specific Version
        # =========================================
        print("\n=== View Specific Version ===")

        # View v1
        v1 = await client.get(doc_id, version=1)
        print(f"v1 title: {v1.output_data.get('title')}")

        # View current version
        current = await client.get(doc_id)
        print(f"v{current.version} title: {current.output_data.get('title')}")

        # =========================================
        # 6. Revert to Old Version
        # =========================================
        print("\n=== Revert to Old Version ===")

        # Use checkout (creates new version)
        print("Checkout to v2...")
        await client.checkout(doc_id, 2)

        # View current state
        data = await client.get(doc_id)
        print(f"Current version: v{data.version}")
        print(f"Current title: {data.output_data.get('title')}")

        # View history again
        print("\nUpdated version history:")
        history = await client.get_history(doc_id, limit=5)
        for h in history:
            print(f"  v{h['version']}: {h.get('message', '')}")

        # =========================================
        # 7. Branch Operations
        # =========================================
        print("\n=== Branch Operations ===")

        # Create experiment branch
        branch = await client.create_branch(doc_id, "experiment")
        print(f"✓ Created branch: {branch.name}")

        # Switch to experiment branch
        await client.switch_branch(doc_id, "experiment")
        print("✓ Switched to experiment branch")

        # Edit in branch
        await client.set_output(doc_id, "title", "Experimental Title")
        await client.commit(doc_id, message="Experimental change")
        print("✓ Made experimental changes in branch")

        # Switch back to main branch
        await client.switch_branch(doc_id, "main")
        data = await client.get(doc_id)
        print(f"✓ Switched back to main, title: {data.output_data.get('title')}")

        # List all branches
        branches = await client.list_branches(doc_id)
        print(f"\nAll branches: {[b.name for b in branches]}")

        # =========================================
        # 8. Tag Release
        # =========================================
        print("\n=== Tag Release ===")

        # Create release tag
        tag = await client.create_tag(
            doc_id,
            "v1.0.0",
            message="First release"
        )
        print(f"✓ Created tag: {tag.name}")

        # List all tags
        tags = await client.list_tags(doc_id)
        print(f"All tags: {[(t.name, f'v{t.version}') for t in tags]}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
