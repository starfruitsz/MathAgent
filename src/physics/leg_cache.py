"""航段预计算与缓存（★ ADR-003：Q1–Q4 的共同依赖）。

为什么必须缓存
--------------
航段几何需要沿 DEM 采样最高点（每段约 100–300 次双线性插值）。
Q1 要 3 机型 × 15 服务区、Q2/Q3 还要跨服务区组合，重复计算会成为主要瓶颈。
这里把 `(i, j) → (d, h⁺, h⁻, H_cruise, t)` **只算一次**并落盘。

缓存键与完整性
--------------
缓存内容包含 `provider_id`（DEM 文件路径 + 大小）与采样步长；
读取时校验这两个字段，不一致则视为失效并重算 —— 避免"用了旧 DEM 的缓存"。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.common.config import DATA_PROCESSED, DEM_RESOLUTION_M, REPO_ROOT
from src.geo.crs import make_local_plane
from src.geo.dem import ElevationProvider
from src.geo.leg import Node, leg_geometry

CACHE_PATH = DATA_PROCESSED / "leg_cache.parquet"

BASE_COLUMNS = [
    "from_id",
    "to_id",
    "distance_m",
    "climb_m",
    "descent_m",
    "cruise_alt_m",
    "op_from_m",
    "op_to_m",
    "max_ground_elev_m",
]


def provider_id(provider: ElevationProvider, sample_step_m: float) -> str:
    """高程提供者的指纹：用于缓存失效判定。"""
    raw = f"{getattr(provider, 'path', 'analytic')}|{sample_step_m}"
    if hasattr(provider, "path"):
        p = Path(str(provider.path))  # type: ignore[attr-defined]
        try:
            raw += f"|{p.stat().st_size}"
        except OSError:
            pass
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class LegCache:
    """航段几何的查表封装。"""

    df: pd.DataFrame
    provider_fingerprint: str
    sample_step_m: float

    def get(self, from_id: str, to_id: str) -> dict[str, float]:
        """取单个航段的几何量。"""
        row = self.df[(self.df["from_id"] == from_id) & (self.df["to_id"] == to_id)]
        if row.empty:
            raise KeyError(f"缓存中没有航段 {from_id} → {to_id}")
        r = row.iloc[0]
        return {
            "distance_m": float(r["distance_m"]),
            "climb_m": float(r["climb_m"]),
            "descent_m": float(r["descent_m"]),
            "cruise_alt_m": float(r["cruise_alt_m"]),
            "op_from_m": float(r["op_from_m"]),
            "op_to_m": float(r["op_to_m"]),
            "max_ground_elev_m": float(r["max_ground_elev_m"]),
        }

    def distance(self, from_id: str, to_id: str) -> float:
        return float(self.get(from_id, to_id)["distance_m"])

    @property
    def n_legs(self) -> int:
        return len(self.df)


def _build_all_legs(
    provider: ElevationProvider,
    nodes: list[Node],
    sample_step_m: float,
) -> pd.DataFrame:
    """计算全部**有序**节点对的航段几何。

    ★ 必须算有序对：a→b 与 b→a 的爬升/下降高度互换，
      因此时间与能耗不同（见 docs/MODEL_NOTES.md）。
    """
    positions = [(n.lon, n.lat) for n in nodes]
    plane = make_local_plane(points=positions)

    rows: list[dict] = []
    for a in nodes:
        for b in nodes:
            if a.id == b.id:
                continue
            g = leg_geometry(
                provider, a, b, plane=plane, sample_step_m=sample_step_m
            )
            rows.append(
                {
                    "from_id": g.from_id,
                    "to_id": g.to_id,
                    "distance_m": g.distance_m,
                    "climb_m": g.climb_m,
                    "descent_m": g.descent_m,
                    "cruise_alt_m": g.cruise_alt_m,
                    "op_from_m": g.op_from_m,
                    "op_to_m": g.op_to_m,
                    "max_ground_elev_m": g.max_ground_elev_m,
                }
            )
    return pd.DataFrame(rows)


def build_or_load(
    provider: ElevationProvider,
    nodes: list[Node],
    sample_step_m: float = DEM_RESOLUTION_M,
    path: Path = CACHE_PATH,
    force: bool = False,
) -> LegCache:
    """构建或读取航段缓存。

    缓存校验：`provider_fingerprint` 与 `sample_step_m` 必须一致，否则重算。
    """
    fp = provider_id(provider, sample_step_m)

    if path.exists() and not force:
        try:
            df = pd.read_parquet(path)
            meta_ok = (
                "provider_fingerprint" in df.attrs
                and df.attrs["provider_fingerprint"] == fp
                and df.attrs.get("sample_step_m") == sample_step_m
            )
            if meta_ok:
                return LegCache(df.drop(columns=["provider_fingerprint"], errors="ignore"),
                                fp, sample_step_m)
        except Exception:  # noqa: BLE001
            pass  # 缓存损坏 → 重算

    df = _build_all_legs(provider, nodes, sample_step_m)
    out = df.copy()
    out.attrs["provider_fingerprint"] = fp
    out.attrs["sample_step_m"] = sample_step_m
    path.parent.mkdir(parents=True, exist_ok=True)
    # parquet 不保留 attrs，用额外列承载指纹
    out["provider_fingerprint"] = fp
    out["sample_step_m"] = sample_step_m
    out.to_parquet(path, index=False)
    return LegCache(out, fp, sample_step_m)


def load_cached(path: Path = CACHE_PATH) -> LegCache:
    """只读取已存在的缓存（不存在则报错）。"""
    if not path.exists():
        raise FileNotFoundError(
            f"航段缓存不存在：{path}\n请先运行 python -m src.physics.leg_cache"
        )
    df = pd.read_parquet(path)
    fp = str(df["provider_fingerprint"].iloc[0])
    step = float(df["sample_step_m"].iloc[0])
    return LegCache(df, fp, step)


def main() -> int:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    from src.geo.dem import RasterElevationProvider
    from src.q0_data.build_processed import load_nodes as _load_nodes

    dem = (
        REPO_ROOT
        / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
        / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
    )
    print("=" * 70)
    print("航段预计算（leg_cache）")
    print("=" * 70)

    ndf = _load_nodes()
    nodes = [
        Node(str(r["id"]), float(r["lon"]), float(r["lat"]), str(r["kind"]),
             float(r["ground_elev_m"]))
        for _, r in ndf.iterrows()
    ]
    prov = RasterElevationProvider(dem)
    import time

    t0 = time.perf_counter()
    cache = build_or_load(prov, nodes, force=True)
    dt = time.perf_counter() - t0

    print(f"节点 {len(nodes)} 个 → 有序航段 {cache.n_legs} 条（{len(nodes)}×{len(nodes)-1}）")
    print(f"采样步长 {cache.sample_step_m:.0f} m；指纹 {cache.provider_fingerprint}")
    print(f"耗时 {dt:.1f} s")
    print(f"缓存写入 {CACHE_PATH.relative_to(REPO_ROOT)}")
    print()
    d = cache.df
    print("距离统计 (m): min %.0f / 中位 %.0f / max %.0f" % (
        d["distance_m"].min(), d["distance_m"].median(), d["distance_m"].max()))
    print("巡航海拔统计 (m): min %.0f / max %.0f" % (
        d["cruise_alt_m"].min(), d["cruise_alt_m"].max()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
