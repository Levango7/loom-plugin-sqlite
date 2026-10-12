"""插件的自检判据（外部仓 CI 跑它；本地 `python examples/self_check.py` 同款）。

不依赖 pytest：直接构造宿主消息调用 handle()，把"只读、单语句、诚实降级、
转义与截断"这些语义钉死。任何一条不过即非零退出。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

# 本地（未安装）运行支持：把仓根加入搜索路径；安装态下这是 no-op。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loom_core.base_agent import Message
from loom_plugin_sqlite.sqlite_query import SqliteQueryAgent

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{PASS if ok else FAIL}] {name}" + (f" —— {detail}" if detail else ""))


def run(db_path: str, query: str, **cfg) -> dict:
    agent = SqliteQueryAgent.__new__(SqliteQueryAgent)  # 不触发 BaseAgent 构造（无总线）
    agent.bus = None  # report/publish 对无总线有保护（`if self.bus`）
    msg = Message(topic="sqlite_query.input",
                  payload={"config": {"db_path": db_path, "query": query, **cfg}})
    return agent.handle(msg) or {}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)",
                         [(1, "alpha"), (2, "b|eta"), (3, "gamma" * 80)])
        conn.commit()
        conn.close()

        r = run(str(db), "SELECT id, name FROM t ORDER BY id")
        check("正常 SELECT：ok + 渲染表格", r.get("status") == "ok" and "| alpha |" in r.get("content", ""), r.get("error", ""))
        check("竖线转义：p|eta 渲染为 p\\|eta", "b\\|eta" in r.get("content", ""))
        check("长文本截断：出现省略号", "…" in r.get("content", ""))
        check("总数如实：total=3", r.get("total") == 3)

        r = run(str(db), "SELECT id FROM t", max_rows=2)
        check("max_rows 截断：truncated + 文案", r.get("truncated") is True
              and "已截断：共 3 行，本报告展示前 2 行" in r.get("content", ""))

        r = run(str(db), "SELECT id FROM t WHERE id = 999")
        check("空结果：ok（不是错误）+（0 行）", r.get("status") == "ok" and "（0 行）" in r.get("content", ""))

        r = run(str(db), "INSERT INTO t VALUES (9, 'x')")
        check("写操作被拒：INSERT → error", r.get("status") == "error", r.get("error", ""))
        r = run(str(db), "SELECT 1; SELECT 2")
        check("多语句被拒：分号 → error", r.get("status") == "error", r.get("error", ""))
        r = run(str(db), "DROP TABLE t")
        check("DDL 被拒：DROP → error", r.get("status") == "error")
        r = run(str(Path(td) / "nope.db"), "SELECT 1")
        check("库不存在：error（不静默）", r.get("status") == "error", r.get("error", ""))
        r = run(str(db), "")
        check("空 query 被拒", r.get("status") == "error")
        r = run(str(db), "SELECT id FROM t", max_rows="很多")
        check("max_rows 非法被拒", r.get("status") == "error")

        # 只读实证：写操作被拒后库里行数未变
        conn = sqlite3.connect(db)
        n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        conn.close()
        check("只读实证：库内容未被改动", n == 3)

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
