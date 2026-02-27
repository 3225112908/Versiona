# Versiona 重構提案：支援「Node 直接存內容」模式

## 背景

目前 Versiona 架構：
- `{prefix}nodes`: 樹狀結構，不存內容
- `{prefix}kv`: Key-Value 快速讀寫（當前狀態）
- `{prefix}versions`: 版本歷史（commit 時創建）

這在 Agent 場景（多個 key-value）是合理的，但在 DXF/CAD 場景：
- 每個 entity 只有一個 `content`（YAML 格式的幾何資料）
- 渲染時需要讀取大量 entity 的 content
- 使用 KV 表會導致 JOIN 操作，效能不佳

## 提案：新增 `content` 模式

### 方案 A：在 VersionaConfig 新增 `node_content_mode`

```python
@dataclass
class VersionaConfig:
    # ... existing fields ...

    # Node content mode
    # - "kv": Use KV table for content (default, suitable for Agent)
    # - "inline": Store content directly in nodes table (suitable for DXF/CAD)
    node_content_mode: str = "kv"

    # When inline mode, these columns are added to nodes table
    inline_content_columns: dict[str, str] = field(default_factory=lambda: {
        "content": "TEXT",
    })
```

### 方案 B：使用 custom_node_columns（已支援）

目前 Versiona 已支援 `custom_node_columns`，DXF 可以這樣配置：

```python
config = VersionaConfig(
    table_prefix="dxf_",
    custom_node_columns={
        "content": "TEXT",
        "min_x": "DOUBLE PRECISION",
        "min_y": "DOUBLE PRECISION",
        "max_x": "DOUBLE PRECISION",
        "max_y": "DOUBLE PRECISION",
        "color_override": "INTEGER",
    },
)
```

**但缺少的是**：
1. Client 需要有方法直接更新 node 的 content（不經過 kv）
2. Client 需要有方法直接讀取 node 的 content（不經過 kv）

## 建議的修改

### 1. client.py - 新增直接操作 node 內容的方法

```python
async def update_node_content(
    self,
    context_id: str,
    content: str | None = None,
    **custom_columns: Any,
) -> bool:
    """
    直接更新 node 的自訂欄位（不創建版本）。

    適用場景：
    - DXF entity 內容更新
    - 任何需要直接存在 node 上的資料

    Args:
        context_id: Node ID
        content: Content to update
        **custom_columns: Other custom columns to update

    Returns:
        Whether update was successful
    """
    columns = []
    values = []
    idx = 2

    if content is not None:
        columns.append(f"content = ${idx}")
        values.append(content)
        idx += 1

    for col, val in custom_columns.items():
        columns.append(f"{col} = ${idx}")
        values.append(val)
        idx += 1

    if not columns:
        return False

    async with self.pool.acquire() as conn:
        result = await conn.execute(f"""
            UPDATE {self.config.nodes_table}
            SET {", ".join(columns)}, updated_at = NOW()
            WHERE id = $1
        """, context_id, *values)

    return "UPDATE 1" in result


async def get_node_content(
    self,
    context_id: str,
    columns: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    直接讀取 node 的自訂欄位。

    Args:
        context_id: Node ID
        columns: Columns to fetch (default: all custom columns)

    Returns:
        Dict of column values
    """
    cols = columns or list(self.config.custom_node_columns.keys())
    if not cols:
        return None

    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            SELECT {", ".join(cols)}
            FROM {self.config.nodes_table}
            WHERE id = $1
        """, context_id)

    return dict(row) if row else None
```

### 2. tables.py - 確保 custom_node_columns 正確處理

目前已支援，無需修改。

### 3. 新增批量操作方法

```python
async def update_nodes_content_batch(
    self,
    updates: list[dict[str, Any]],
) -> int:
    """
    批量更新多個 node 的內容。

    Args:
        updates: [{"id": str, "content": str, ...}, ...]

    Returns:
        Number of updated nodes
    """
    if not updates:
        return 0

    async with self.pool.acquire() as conn:
        async with conn.transaction():
            updated = 0
            for u in updates:
                node_id = u.pop("id")
                columns = []
                values = [node_id]
                idx = 2

                for col, val in u.items():
                    columns.append(f"{col} = ${idx}")
                    values.append(val)
                    idx += 1

                if columns:
                    result = await conn.execute(f"""
                        UPDATE {self.config.nodes_table}
                        SET {", ".join(columns)}, updated_at = NOW()
                        WHERE id = $1
                    """, *values)
                    if "UPDATE 1" in result:
                        updated += 1

    return updated
```

## 影響評估

### 不影響現有功能
- 這些是新增方法，不修改現有 API
- 使用 custom_node_columns 的專案已經可以存資料，只是沒有方便的 client 方法

### 效能提升
- DXF 場景渲染時只需查 nodes 表，不需 JOIN kv 表
- 批量操作使用事務，效能更好

## 遷移指南

### DXF 專案

1. 配置 Versiona 使用 custom_node_columns：
```python
config = VersionaConfig(
    table_prefix="dxf_",
    custom_node_columns={
        "content": "TEXT",
        "min_x": "DOUBLE PRECISION",
        # ...
    },
)
```

2. 使用新方法：
```python
# 更新單一 node
await client.update_node_content(entity_id, content=yaml_content, min_x=0, max_x=100)

# 批量更新
await client.update_nodes_content_batch([
    {"id": id1, "content": content1},
    {"id": id2, "content": content2},
])

# 讀取
data = await client.get_node_content(entity_id, ["content", "min_x", "max_x"])
```
