"""生成演示用 sample.db（orders 表）。

刻意包含三类"报表会碰到的脏数据"，让渲染路径的边界行为可被亲眼看到：
  - 备注里带竖线 `|`（markdown 表格转义）；
  - 超长备注（单元格截断 + `…`）；
  - 中文客户名（宽度/编码路径）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "sample.db"

ROWS = [
    ("SO-1001", "杭州云帆科技", 12800.00, "paid", "首批交付验收完成"),
    ("SO-1002", "上海迈迅信息", 9600.50, "paid", "含硬件维保 | 三年期"),
    ("SO-1003", "深州恒芯电子", 7500.00, "pending", "合同条款复核中"),
    ("SO-1004", "北京光合数据", 4300.75, "paid", "增补 License | 已开票"),
    ("SO-1005", "成都星联网络", 2100.00, "refunded", "客户缩容，按比例退"),
    ("SO-1006", "武汉智塔软件", 18800.00, "pending",
     "超长备注用于验证单元格截断行为：" + "验收材料与附件清单" * 12),
    ("SO-1007", "西安凌峰智能", 560.00, "paid", "样品单"),
    ("SO-1008", "苏州澄明仪器", 3320.00, "paid", None),
]


def main() -> None:
    DB.unlink(missing_ok=True)
    conn = sqlite3.connect(DB)
    try:
        conn.execute("""
            CREATE TABLE orders (
                order_no TEXT PRIMARY KEY,
                customer TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                note TEXT
            )""")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", ROWS)
        conn.commit()
    finally:
        conn.close()
    print(f"sample.db 已生成: {DB}（orders {len(ROWS)} 行）")


if __name__ == "__main__":
    main()
