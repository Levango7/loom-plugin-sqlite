# loom-plugin-sqlite

**Loom（`nexusloom`）的外部插件**：`sqlite_query` —— 只读查询本地 SQLite 库，把结果渲染成 Markdown 表格，供工作流落盘成报告。

这是「生态轴」的第一个**真正第三方包**：仓库独立、代码独立、发布独立——Loom 本体**零改动**即可发现、注册并执行它。也是外部作者写自己的插件时的活体参照。

## 它解决什么

Loom 出厂件的取数面覆盖 HTTP API（`http_request`）与本地文档（`ingest`/`knowledge_base`），但**本地数据库**没有取数件。`sqlite_query` 补上这一格：报表、对账、库存/订单快照这类"库里有数、要出可读报告"的活，配一条两节点管线就能跑，并可叠加 Loom 的审批闸门（出数前待批）与锁文件（口径防漂移）。

## 安装

```bash
# 从 GitHub 安装（本机无梯子时走 gh-proxy 镜像也可）：
pip install "git+https://github.com/Levango7/loom-plugin-sqlite.git"
pip install "https://gh-proxy.com/https://github.com/Levango7/loom-plugin-sqlite/archive/refs/heads/main.tar.gz"

# 或（发布后）：
pip install loom-plugin-sqlite
```

依赖宿主 `nexusloom>=3.10.0`（`loom.agents` 组从 3.10.0 起为正式契约；更早版本用旧组名 `doc_pipeline.agents`）。

## 用法

装好即可见：

```bash
loom plugin list        # 应出现 sqlite_query，来源标记 [entry_point:sqlite_query]
```

最小管线（仓库内 `examples/sqlite-report.yaml`，可直接跑）：

```yaml
agents:
  - name: sqlite_query
    version: "1.0"
    dependencies: []
    config:
      db_path: /path/to/app.db     # 只读打开（mode=ro + authorizer 双保险）
      query: "SELECT id, name, price FROM products ORDER BY price DESC"
      title: "产品价格快照"
      max_rows: 50                 # 超出如实标注"已截断：共 N 行"
  - name: safe_writer
    version: "2.0"
    dependencies: ["sqlite_query"]
    config: {output_dir: output}
```

出数前要人批（`examples/sqlite-report-approved.yaml` 演示"取数 → 待批 → 交付"）：

```yaml
  - name: release_gate
    approval:
      message: "确认数据口径后放行出具"
    dependencies: ["sqlite_query"]
```

待批时任务停在 `paused`，`POST /tasks/<id>/approve|reject` 放行或驳回（详见 Loom 主仓 README「审批闸门」一节）。

## 可靠性语义（与 Loom 的失败哲学一致）

- **只读双保险**：`file:...?mode=ro` + SQLite authorizer 拒绝一切非读操作；
- 只认单条 `SELECT`/`WITH`（不是 SQL 控制台）；多语句 / 语法错 / 库打不开 → `status: error` + 具体原因，不静默降级；
- 空结果集不是错误：如实渲染"（0 行）"；
- 截断如实：`max_rows` 超出时用 `SELECT COUNT(*)` 包查询取真实总数并标注，COUNT 失败则降级说明，不猜数；
- 本文件不碰宿主加载器的 AST 黑名单（`open`/`eval`/`subprocess` 等），因此**不声明** `SANDBOX_TRUSTED`——那个声明只属于随产品发布的内置件；插件按"不可信代码"受检。

## 契约（外部作者照抄即可）

- entry point：组 `loom.agents`，值 = 模块路径（`包.模块`）；
- 模块级 `AGENT_NAME`（注册名，管线里写它）+ `AGENT_VERSION` + 可选 `AGENT_DESC`/`INPUT_TOPICS`/`OUTPUT_TOPICS`；
- **产物契约**：`PRODUCES = {"content": "last", ...}` 声明哪些键提升给下游（落盘/质检节点按 `CONSUMES=["content"]` 取正文）；不声明的键只能经 `dependencies_results` 访问；
- 一个 `loom_core.base_agent.BaseAgent` 子类，实现 `handle(msg) -> dict`；
- 只依赖宿主公开面（如 `base_agent`），不要 import 宿主内部模块。

### 过渡期提示：宿主 import 改名（3.11.0 起）

宿主引擎的 import 根名已从 `pipeline_core` 改为 `loom_core`（旧名以兼容 shim 保留，identity 保真，到 4.x）。**同时支持新旧宿主的插件**照这个写：

```python
try:  # 宿主 >= 3.11.0
    from loom_core.base_agent import BaseAgent, Message
except ModuleNotFoundError:  # 宿主 3.10.x
    from pipeline_core.base_agent import BaseAgent, Message
```

本插件的 CI 就是双宿主版本矩阵（3.10.0 与 3.11.0 各跑一遍全链），可直接抄。

## License

MIT
