"""loom_plugin_sqlite —— Loom 外部插件：只读 SQLite 取数。

经 `loom.agents` entry_points 组被发现（值 = 模块路径），与宿主零耦合：
本包只依赖 Loom 的公开插件契约（`loom_core.base_agent`），不 import 宿主任何
内部模块。
"""
