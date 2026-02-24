"""
Basic Agent Execution Flow Example

Demonstrates:
1. Create Project Context
2. Fork Task
3. Execute SubAgent (using ExecutionContext)
4. Local vs Output data
5. Finalize and Merge
"""

import asyncio
import os
from datetime import datetime
from versiona import VersionaClient, ContextLevel

# Read database connection from environment variable, defaults to local dev environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/versiona")


async def main():
    # Connect to database
    client = await VersionaClient.create(DATABASE_URL)

    try:
        # Initialize schema (first time use)
        await client.init_schema()

        # Use timestamp to ensure unique ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # =========================================
        # 1. Coordinator Creates Project Context
        # =========================================
        project_id = f"project_todo_app_{timestamp}"

        await client.create_context(
            project_id,
            level=ContextLevel.PROJECT,
            name="Todo App Development Project",
            metadata={"type": "development", "priority": "high"}
        )

        # Set project context (these will be inherited by SubAgent)
        await client.set_output(project_id, "user_request", "Develop a Todo API")
        await client.set_output(project_id, "architecture", {
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "cache": "Redis"
        })
        await client.set_output(project_id, "requirements", [
            "CRUD operations",
            "User authentication",
            "Category feature"
        ])

        await client.commit(project_id, message="Project initialized")
        print(f"✓ Created project: {project_id}")

        # =========================================
        # 2. Fork Task
        # =========================================
        task_id = f"task_backend_dev_{timestamp}"
        await client.fork(project_id, task_id, level=ContextLevel.TASK)
        print(f"✓ Fork Task: {task_id}")

        # =========================================
        # 3. SubAgent 1: API Development
        # =========================================
        print("\n--- SubAgent 1: API Development ---")

        async with client.execution_context(
            "subagent_api",
            parent_id=task_id,
            auto_finalize=True,  # Auto finalize on exit
            auto_merge=True      # Auto merge to parent on exit
        ) as ctx:
            # Read inherited data
            data = await ctx.get_for_llm()
            arch = data.get("architecture", {})
            print(f"  Inherited architecture: {arch}")

            # Set Local data (intermediate process, not inherited)
            await ctx.set_local("thinking", [
                f"Using {arch.get('backend', 'FastAPI')} framework",
                "Design RESTful API endpoints",
                "Implement CRUD operations"
            ])

            await ctx.set_local("tool_calls", [
                {"name": "write_file", "path": "api/routes.py", "status": "success"},
                {"name": "write_file", "path": "api/models.py", "status": "success"},
            ])

            # Set Output data (final output, will be inherited)
            await ctx.set_output("api_spec", {
                "endpoints": [
                    "GET /todos",
                    "POST /todos",
                    "PUT /todos/{id}",
                    "DELETE /todos/{id}"
                ],
                "models": ["Todo", "User", "Category"]
            })

            await ctx.set_output("files_created", [
                "api/routes.py",
                "api/models.py",
                "api/schemas.py"
            ])

            print("  ✓ Completed API development")
            # Auto finalize (soft delete local) + merge on exit

        # =========================================
        # 4. SubAgent 2: Test Development
        # =========================================
        print("\n--- SubAgent 2: Test Development ---")

        async with client.execution_context(
            "subagent_test",
            parent_id=task_id
        ) as ctx:
            # Read data after SubAgent 1 merge
            data = await ctx.get_for_llm()
            api_spec = data.get("api_spec", {})
            print(f"  Read API Spec: {len(api_spec.get('endpoints', []))} endpoints")

            # Execution process
            await ctx.set_local("reasoning", [
                f"Need to test {len(api_spec.get('endpoints', []))} endpoints",
                "Using pytest framework",
                "Include unit tests and integration tests"
            ])

            # Output
            await ctx.set_output("test_coverage", 85)
            await ctx.set_output("test_files", [
                "tests/test_routes.py",
                "tests/test_models.py"
            ])

            print("  ✓ Completed test development")

        # =========================================
        # 5. Merge Back to Project
        # =========================================
        await client.merge(task_id, project_id, message="Backend development completed")
        print(f"\n✓ Merge {task_id} -> {project_id}")

        # =========================================
        # 6. View Final Result
        # =========================================
        print("\n=== Final Result ===")
        result = await client.get(project_id)

        print(f"Version: {result.version}")
        print("Output data:")
        for key, value in result.output_data.items():
            if isinstance(value, list) and len(value) > 3:
                print(f"  {key}: [{value[0]}, ..., {value[-1]}] ({len(value)} items)")
            else:
                print(f"  {key}: {value}")

        # =========================================
        # 7. View Version History
        # =========================================
        print("\n=== Version History ===")
        history = await client.get_history(project_id)
        for h in history[:5]:
            print(f"  v{h['version']}: {h['message']} ({h['created_at'][:19]})")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
