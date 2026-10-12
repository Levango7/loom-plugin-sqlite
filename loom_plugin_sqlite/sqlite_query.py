"""sqlite_query —— Loom 外部插件：只读 SQLite 取数 Agent。

契约与内置 `agents/*.py` 同构（模块级 AGENT_NAME + BaseAgent 子类），经
`loom.agents` entry_points 组被发现；本文件刻意保持"干净"——不碰加载器
AST 黑名单里的任何调用（`open`/`eval`/`subprocess` 等），因此**不需要**
（也不应该）声明 `SANDBOX_TRUSTED`——那个声明只留给随产品发布的内置件。

取数边界（诚实语义，与 Loom 的失败哲学一致）：
  - 只读：连接用 `file:...?mode=ro` URI，另加 authorizer 拒绝一切非读操作
    （双保险；违规直接 error，不静默降级）；
  - 只认 SELECT / WITH 开头的单语句（去掉尾分号后还有 `;` 即拒）——
    插件不是 SQL 控制台；
  - 库不存在 / SQL 语法错 / 非查询语句 → `status: error` + 具体原因；
  - 空结果集不是错误：渲染"（0 行）"如实交付；
  - 超过 max_rows 时**如实标注**"已截断：共 N 行，展示前 M 行"（N 用
    `SELECT COUNT(*)` 包查询取得；COUNT 失败则退化为"展示前 M 行"，不猜数）。
"""
from __future__ import annotations

import sqlite3

# 宿主 import 名在 3.11.0 起由 `pipeline_core` 更名为 `loom_core`（旧名以兼容
# shim 保留到 4.x）。外部插件在过渡期的正确姿势 = 双名兼容：
#   - 新宿主（>=3.11.0）：走 loom_core（正式面）；
#   - 更早宿主（3.10.x）：走 pipeline_core。
# 两处 `base_agent` 在改名前后是**同一套公开契约**（shim 保 identity）。
try:  # pragma: no cover - 分支取决于宿主版本
    from loom_core.base_agent import AgentStatus, BaseAgent, Message
except ModuleNotFoundError:  # 宿主 < 3.11.0
    from pipeline_core.base_agent import AgentStatus, BaseAgent, Message

AGENT_NAME = "sqlite_query"
AGENT_VERSION = "0.1.0"
AGENT_DESC = "只读查询本地 SQLite 库并把结果渲染成 Markdown 表格（外部插件）"
AGENT_AUTHOR = "Levango7"
AGENT_PRIORITY = 50
INPUT_TOPICS = ["sqlite_query.input"]
OUTPUT_TOPICS = ["sqlite_query.done"]

#: 产物契约（宿主按此把 handle() 返回的关键键提升进下游载荷）：
#: content 是渲染好的 Markdown 正文——落盘/质检那批节点按 CONSUMES=["content"] 取它。
PRODUCES: dict = {"content": "last", "rows": "last", "total": "last",
                  "columns": "last", "truncated": "last"}
CONSUMES: list = []

#: 渲染进产物的一格最多多少字符（超长文本截断，避免表格失控）
_CELL_MAX = 120
#: 默认最多取多少行（超过在产物里如实注明截断）
_DEFAULT_MAX_ROWS = 200


def _readonly_authorizer(action, arg1, arg2, dbname, source):  # noqa: ANN001
    """SQLite authorizer：只放行读操作（mode=ro 之外的第二道）。"""
    ok = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    return sqlite3.SQLITE_OK if action in ok else sqlite3.SQLITE_DENY


def _is_single_select(query: str) -> bool:
    """只允许"一条 SELECT/WITH 语句"：去掉尾分号后不得再出现分号。"""
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        return False
    if ";" in stripped:
        return False
    head = stripped.split(None, 1)[0].upper()
    return head in ("SELECT", "WITH")


def _cell(value) -> str:  # noqa: ANN001
    if value is None:
        return ""
    # markdown 表格转义：先处理反斜杠本身，再转义竖线；换行折成空格
    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if len(text) > _CELL_MAX:
        text = text[:_CELL_MAX] + "…"
    return text


def _render_markdown(title: str, columns: list, rows: list, total: int | None) -> str:
    lines: list[str] = []
    if title:
        lines += [f"# {title}", ""]
    lines.append("| " + " | ".join(_cell(c) for c in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    shown = len(rows)
    lines.append("")
    if total == 0:
        lines.append("（0 行）")
    elif total is None:
        lines.append(f"（展示前 {shown} 行；总数未取到）")
    elif shown < total:
        lines.append(f"（已截断：共 {total} 行，本报告展示前 {shown} 行）")
    else:
        lines.append(f"（共 {total} 行）")
    return "\n".join(lines)


class SqliteQueryAgent(BaseAgent):
    """执行只读查询并把结果渲染为 Markdown 表格，写进下游可读的 content。"""

    def handle(self, msg: Message) -> dict | None:
        payload = msg.payload or {}
        config = payload.get("config") or {}
        db_path = str(config.get("db_path", "") or "").strip()
        query = str(config.get("query", "") or "").strip()
        title = str(config.get("title", "") or "").strip()
        try:
            max_rows = int(config.get("max_rows", _DEFAULT_MAX_ROWS))
        except (TypeError, ValueError):
            return {"status": "error", "error": f"max_rows 非法: {config.get('max_rows')!r}"}
        if max_rows < 1:
            return {"status": "error", "error": f"max_rows 必须 ≥1，实际: {max_rows}"}
        if not db_path:
            return {"status": "error", "error": "缺少 config.db_path"}
        if not _is_single_select(query):
            return {"status": "error",
                    "error": "config.query 必须是单条 SELECT/WITH 语句（只读取数）"}

        self.report(AgentStatus.RUNNING, f"只读查询 {db_path}")
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error as e:
            return {"status": "error", "error": f"数据库打不开（只读）: {e}"}
        try:
            conn.set_authorizer(_readonly_authorizer)
            total: int | None
            try:
                total = int(conn.execute(
                    f"SELECT COUNT(*) FROM ({query})").fetchone()[0])
            except sqlite3.Error:
                total = None  # COUNT 包查询失败不阻断取数（文案如实降级）
            cur = conn.execute(query)
            columns = [d[0] for d in (cur.description or [])]
            rows = [list(r) for r in cur.fetchmany(max_rows)]
        except sqlite3.Error as e:
            return {"status": "error", "error": f"SQL 执行失败: {e}"}
        finally:
            conn.close()

        md = _render_markdown(title, columns, rows, total)
        result = {
            "status": "ok",
            "content": md,
            "rows": len(rows),
            "total": total,
            "columns": columns,
            "truncated": bool(total is not None and len(rows) < total),
        }
        self.publish("sqlite_query.done",
                     {"task_id": payload.get("task_id", ""), "rows": len(rows),
                      "total": total, "columns": columns})
        return result
