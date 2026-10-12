"""审批闸门 × 外部插件：端到端判据（外部仓 CI 跑它）。

只用宿主公开面（`loom_core.PipelineOrchestrator` / `loom_core.scheduler.Scheduler`），
把"外部插件 + 人工闸门"的组合钉死：

  1. 跑 `sqlite-report-approved.yaml` → 任务必须停在 `awaiting_approval`（无人批不出数）；
  2. approve 放行 → 任务完成 → 产物真落盘且含表格；
  3. 再来一个任务 reject 驳回 → 任务 terminated（cancelled）→ **无产物**。

任何一条不过即非零退出。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# 本地（未安装）运行支持：把仓根加入搜索路径；安装态下这是 no-op。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 双名兼容（宿主 3.11.0 起 pipeline_core → loom_core；shim 保旧名到 4.x）
try:  # pragma: no cover - 分支取决于宿主版本
    from loom_core import PipelineOrchestrator, paths
    from loom_core.scheduler import Scheduler
except ModuleNotFoundError:  # 宿主 < 3.11.0
    from pipeline_core import PipelineOrchestrator, paths
    from pipeline_core.scheduler import Scheduler

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "examples" / "sqlite-report-approved.yaml"
OUT_APPROVED = ROOT / "output" / "sqlite-report-approved.md"
OUT_REJECTED = ROOT / "output" / "sqlite-report-rejected.md"


def wait_for(cond, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.2)
    sys.exit(f"超时等待：{what}")


def main() -> int:
    sample = ROOT / "sample.db"
    if not sample.exists():
        sys.exit("sample.db 不存在——先跑 python examples/make_sample.py")

    sched = Scheduler(pipeline_dir=str(PIPELINE.parent))
    plan = sched.parse_file(str(PIPELINE), verify_lock=False)

    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    # 输入文件用仓内固定样例：引擎要求首行是可提取的主题（≥4 字符）；
    # 纯取数管线（数据来自 db）给一行说明即可。
    input_file = ROOT / "examples" / "input.md"

    OUT_APPROVED.unlink(missing_ok=True)
    OUT_REJECTED.unlink(missing_ok=True)

    # 嵌入方须知：裸构造 `PipelineOrchestrator()` 的 agents_dir 默认是**相对
    # 当前 cwd** 的 "agents"，在宿主之外的目录里跑（本仓/CI 就是这样）会零注册；
    # 正确姿势是用宿主公开面解析出的绝对目录（CLI 入口内部也是这么做的）。
    orch = PipelineOrchestrator(agents_dir=str(paths.agents_dir()),
                                checkpoint_dir=str(output_dir / "ckpt"))
    orch.register_agents()
    try:
        # ── 1) 跑到闸门必须停住 ──
        # 与 CLI `-o` 同机制：把产物路径写进 plan.raw（引擎给落盘节点组装 target）
        plan.raw.setdefault("pipeline", {})["output"] = str(OUT_APPROVED)
        t1 = orch.run_plan(plan, input_file=str(input_file),
                           task_id="ext_approve", wait=False)
        wait_for(lambda: bool(t1.awaiting_approval) or
                 t1.status.value in ("done", "failed", "cancelled"),
                 60, "任务到达审批闸门")
        if not t1.awaiting_approval:
            sys.exit(f"任务未停在闸门（status={t1.status.value}）——"
                     "审批语义未生效？")
        if OUT_APPROVED.exists():
            sys.exit("任务还在待批，产物却已落盘——闸门没有拦住交付")
        pending = t1.awaiting_approval
        print(f"[gate] 已停在审批闸门: {pending.get('nodes')} / "
              f"{pending.get('messages')}")

        # ── 2) approve 放行 → 完成 + 产物落盘 ──
        ok, err = orch.approve(t1.id, note="口径已核对", by="external-ci")
        if not ok:
            sys.exit(f"approve 被拒: {err}")
        wait_for(lambda: t1.status.value in ("done", "failed", "cancelled"),
                 90, "放行后任务收尾")
        if t1.status.value != "done":
            sys.exit(f"放行后未完成: {t1.status.value} / {t1.error}")
        if not OUT_APPROVED.exists() or "订单快照（审批版）" not in OUT_APPROVED.read_text(encoding="utf-8"):
            sys.exit("放行后产物缺失或内容不对")
        print("[gate] approve 放行 → done，产物含表格 ✓")

        # ── 3) reject 驳回 → cancelled + 无产物 ──
        plan.raw["pipeline"]["output"] = str(OUT_REJECTED)
        t2 = orch.run_plan(plan, input_file=str(input_file),
                           task_id="ext_reject", wait=False)
        wait_for(lambda: bool(t2.awaiting_approval) or
                 t2.status.value in ("done", "failed", "cancelled"),
                 60, "第二任务到达审批闸门")
        if not t2.awaiting_approval:
            sys.exit("第二任务未停在闸门")
        ok, err = orch.reject(t2.id, reason="演示驳回", by="external-ci")
        if not ok:
            sys.exit(f"reject 被拒: {err}")
        wait_for(lambda: t2.status.value in ("done", "failed", "cancelled"),
                 60, "驳回后任务收尾")
        if t2.status.value != "cancelled":
            sys.exit(f"驳回后状态应为 cancelled，实际 {t2.status.value}")
        if "演示驳回" not in (t2.error or ""):
            sys.exit(f"驳回原因未进任务 error: {t2.error!r}")
        if OUT_REJECTED.exists():
            sys.exit("驳回后仍落了产物——驳回必须终止交付")
        print("[gate] reject 驳回 → cancelled，原因留痕且无产物 ✓")
    finally:
        orch.shutdown()

    print("\n审批闸门 × 外部插件：全部判据通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
