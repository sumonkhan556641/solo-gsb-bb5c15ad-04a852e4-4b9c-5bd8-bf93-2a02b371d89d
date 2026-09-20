# 乐谱安全翻页规划 API

按顺序提交**谱面系统高度**、系统之间的**边界休止秒数**、**页面可用高度**与
**最低安全休止秒数**，服务用动态规划给出完整分页方案：

- 每页由连续的若干系统组成，**总高度不得超过页面可用高度**；
- **只能在休止达到最低安全休止的边界翻页**（第一页前、最后一页后无需休止）；
- 优化目标按优先级依次为：
  1. **最大化最短翻页休止**（让最紧张的那次翻页也尽可能从容）；
  2. **最小化各页留白平方和** Σ(页面可用高度 − 本页已用高度)²；
  3. **减少页数**；
- 无解时指出**首个无法容纳或无法安全断开的区间**（区间编号、高度、
  溢出系统、区间内已有的达标边界），**不保存任何半成品分页**。

技术栈：Python 3.11 + FastAPI + SQLite（标准库 `sqlite3`，无外部数据库）。

## 单条命令启动

需要 Docker（含 Compose 插件）：

```bash
docker compose up --build -d
```

依赖安装与 SQLite 建库都在容器启动时自动完成，无需手动初始化。

服务地址（8000 端口）：

- API 根地址：<http://localhost:8000>
- 健康检查：<http://localhost:8000/health>
- 交互式文档（Swagger UI）：<http://localhost:8000/docs>
- OpenAPI Schema：<http://localhost:8000/openapi.json>

停止：`docker compose down`（数据保留在命名卷 `sheet-data` 中；
如需一并删除数据：`docker compose down -v`）。

## 必要配置

全部通过 Compose 的环境变量 / 端口映射配置，均有默认值，开箱即用：

| 配置 | 位置 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 端口 | `docker-compose.yml` 的 `ports` | `8000:8000` | 宿主机端口:容器端口，改左侧即可换宿主端口 |
| `SHEET_DB_PATH` | `docker-compose.yml` 的 `environment` | `/data/sheet.db` | SQLite 数据库文件（容器内路径），启动时自动建表 |
| 数据持久化 | `docker-compose.yml` 的 `volumes` | 命名卷 `sheet-data` → `/data` | 删除容器不丢数据 |

本地不使用 Docker 直接运行（可选）：

```bash
python3 -m pip install -r requirements.txt
SHEET_DB_PATH=./sheet.db python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### `POST /plans` — 提交并规划分页

请求体：

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `name` | string | 可空，≤200 字 | 乐谱名称 |
| `system_heights` | number[] | 非空，元素 > 0 | 按顺序排列的各系统高度 |
| `boundary_rests` | number[] | 元素 ≥ 0，长度 = 系统数 − 1 | 相邻系统之间的休止秒数 |
| `page_height` | number | > 0 | 页面可用高度（与系统高度同单位） |
| `min_safe_rest` | number | ≥ 0 | 允许翻页所需的最低安全休止秒数 |

可行示例：

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "练习曲 Op.1",
    "system_heights": [9, 8, 7, 1, 4, 9],
    "boundary_rests": [2, 4, 6, 3, 5],
    "page_height": 19,
    "min_safe_rest": 2
  }'
```

```json
{
  "id": 1,
  "name": "练习曲 Op.1",
  "feasible": true,
  "page_count": 3,
  "min_turn_rest": 4.0,
  "whitespace_square_sum": 153.0,
  "pages": [
    {"page_no": 1, "start_system": 1, "end_system": 2, "used_height": 17.0, "whitespace": 2.0},
    {"page_no": 2, "start_system": 3, "end_system": 5, "used_height": 12.0, "whitespace": 7.0},
    {"page_no": 3, "start_system": 6, "end_system": 6, "used_height": 9.0, "whitespace": 10.0}
  ],
  "infeasible": null,
  "created_at": "2026-09-20T00:00:00.000Z"
}
```

无解读：不存在合规分页时 HTTP 状态码仍为 `201`（请求本身合法、结论已存档），
`feasible` 为 `false`，`pages` 为空，并在 `infeasible` 中给出首个问题区间：

```bash
curl -s -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "system_heights": [6, 6, 6],
    "boundary_rests": [1, 4],
    "page_height": 10,
    "min_safe_rest": 3
  }'
```

```json
{
  "feasible": false,
  "pages": [],
  "infeasible": {
    "reason": "no_safe_boundary",
    "message": "首个无法安全断开的区间为系统 1-1（高度 6.0）：继续纳入系统 2 将超高，且该区间内没有达到最低安全休止的翻页边界",
    "interval_start": 1,
    "interval_end": 1,
    "interval_height": 6.0,
    "safe_boundaries_after_start": [],
    "overflow_system": 2
  }
}
```

- `reason`：`no_safe_boundary`（区间超高且区间内无达标翻页边界）或
  `system_too_tall`（单个系统自身高度就超过页面，任何页面都放不下）；
- `safe_boundaries_after_start`：该区间起点之后已达到最低安全休止的边界
  （数字 b 表示“系统 b 之后”），用于核对是否有被高度排除的候选断点。

不可行记录只保存输入与诊断，**不写入任何分页**，不存在半成品方案。

### `GET /plans/{id}` — 查询单条方案

返回与 `POST /plans` 相同的完整结构（含分页明细或不可行诊断）。
不存在返回 `404`。

### `GET /plans?limit=50&offset=0` — 方案列表

按创建时间倒序返回摘要（`id / name / feasible / page_count / min_turn_rest / created_at`），
含 `total` 计数。

### `GET /health`

返回 `{"status": "ok"}`，供容器健康检查与探活使用。

## 算法说明（摘要）

1. **可行性判定（贪心）**：从每页起点尽量多纳入系统，在仍然不超高的
   范围内取最后一个休止达标的边界切分；找不到即定位到首个失败区间。
   “取最晚可达边界”由交换论证保证：任何可行切分都可右移到该边界而不
   影响后续可分性。
2. **最大化最短翻页休止**：候选阈值取所有达标休止值（离散、降序），
   可行性对阈值单调，二分找到仍可行的最高阈值 `t*`。
3. **留白与页数（动态规划）**：仅允许休止 ≥ `t*` 的边界翻页，按系统
   起点从后向前 DP，每页代价为 `(可用高度 − 已用高度)²`，比较键
   `(留白平方和, 页数)` 可加且保字典序最优；最后由父指针还原分页。

## 项目结构

```
app/
  main.py       # FastAPI 路由、启动建库、序列化
  planner.py    # 动态规划 / 二分阈值 / 不可行区间定位
  schemas.py    # 请求、响应模型与输入校验
  database.py   # SQLite 建库与事务化读写
Dockerfile
docker-compose.yml
requirements.txt
```
