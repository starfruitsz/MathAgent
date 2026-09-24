"""A/B：首批专架次预置（seed）开/关对真实调度结果的影响。

用法：
    python scripts/diag/q2_seed_ab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.q2_transport_schedule.solver as S  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs, schedule_score  # noqa: E402
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    Q2Weights,
    clear_caches,
    construct,
    local_search,
)

W = Q2Weights()

HEAD = ("配置", "架次", "能耗", "完工h", "准时率", "首批违规", "期望违规", "score")


def main() -> int:
    boxes, ut, fleet, bi, tf, dl, bdf = load_inputs()
    leg = load_cached()
    bid = {b.box_id: b for b in boxes}
    frozen = {b.service_id for b in boxes
              if b.is_first_batch and (b.first_batch_deadline_s or 1e18) <= 3600.0}

    print(f"{HEAD[0]:<24}{HEAD[1]:>5}{HEAD[2]:>8}{HEAD[3]:>8}"
          f"{HEAD[4]:>8}{HEAD[5]:>9}{HEAD[6]:>9}{HEAD[7]:>9}")
    print("-" * 82)

    for seed in (False, True):
        for code in ("C", "B"):
            if code not in ut or not fleet.get(code):
                continue
            only = {code: ut[code]}
            of = {code: fleet[code]}
            ob = {code: bi.get(code, 0)}
            otf = {code: tf.get(code, 1800.0)}
            clear_caches()
            S.DEFAULT_WEIGHTS = W
            try:
                c = construct(boxes, only, leg, dl, max_group=3,
                              seed_first_batch=seed)
                c = local_search(c, only, leg, bid, dl, weights=W,
                                 resources=(len(of[code]), ob[code], otf[code]),
                                 frozen_areas=(frozen if seed else None))
                plans = [x.plan for x in c if x.plan.stops]
                sch = schedule_dispatch(plans, only, leg, bid,
                                        build_pools(of, ob, otf))
                sc, d = schedule_score(sch, bid, dl, W)
            except Exception as exc:  # noqa: BLE001
                print(f"  seed={seed} {code}: ❌ {type(exc).__name__}: {str(exc)[:50]}")
                continue
            label = f"seed={seed} {code}型"
            print(f"{label:<24}{d['n_sorties']:>5}{d['energy_kwh']:>8.2f}"
                  f"{d['makespan_h']:>8.2f}{d['on_time_rate']:>8.1%}"
                  f"{d['n_late_first_batch']:>9}{d['n_late_boxes']:>9}{sc:>9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
