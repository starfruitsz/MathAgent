"""全局配置与常量 —— D 题。

规范（OPS_SPEC_D题 第 7.1 节 / ADR-005）：
    - 所有超参、路径、常量集中在本文件与 configs/*.yaml
    - 代码里禁止硬编码魔法数字
    - 所有随机过程必须使用 SEED
    - ★ 内部一律使用 SI 单位；单位换算集中在此处定义
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- 路径

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_INTERIM = REPO_ROOT / "data" / "interim"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
OUTPUTS = REPO_ROOT / "outputs"
DOCS = REPO_ROOT / "docs"
CONFIGS = REPO_ROOT / "configs"

# 竞赛附件根目录（题目所述两个子目录）
ATTACH_BASE_PARAMS = DATA_RAW / "无人机应急物资运输基础数据"
ATTACH_GEOSPATIAL = DATA_RAW / "镇龙乡地理空间数据"


def outputs_dir(question: str) -> Path:
    """返回某问的输出目录并自动创建，例如 outputs_dir('q2') -> outputs/q2。"""
    p = OUTPUTS / question
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 随机性

SEED = 42
"""全局随机种子。任何随机过程都必须使用它，保证结果可复现。"""


# ---------------------------------------------------------------- 场景规模（题目正文给定）

N_SERVICE_AREAS = 15
"""服务区数量，编号 S1..S15。"""

N_BOXES = 80
"""货箱数量（**不可拆分**）。"""

N_UAV_TYPES = 3
"""运输无人机机型数。"""

N_UAV_PHYSICAL = 8
"""运输无人机实体架数。"""

DEM_RESOLUTION_M = 30.0
"""DEM 分辨率（米）。"""

DISPATCH_CENTER_ID = "O01"
"""临时调度中心标识。"""

GATEWAY_ID = "G01"
"""固定网关标识（设于 O01）。"""


# ---------------------------------------------------------------- 附录 2：航段与作业高度

CRUISE_CLEARANCE_M = 50.0
"""巡航海拔 = 航段经过 DEM 像元的最高地面高程 + 该高度（米）。"""

SERVICE_AREA_OP_HEIGHT_M = 30.0
"""服务区作业高度 = 地面海拔 + 30 m。"""

DOWNWARD_ENERGY_EFFICIENCY = 0.0
"""下降能耗效率取 0 → **不单独计算下降附加能耗**（题目明确）。"""

PAYLOAD_RANGE_EXPONENT = 1.5
"""载荷-航程关系的指数：L_g(q) = L_g0 − (L_g0−L_gF)·(q/Q_g)^(3/2)。"""


# ---------------------------------------------------------------- 附录 2：两阶段充电模型

CHG_FAST_SOC_BOUNDARY = 0.90
"""快速/慢速阶段分界 SOC。"""

CHG_FAST_FRACTION = 0.65
"""0% → 90% 占等效完全充电时间的比例。"""

CHG_SLOW_FRACTION = 0.35
"""90% → 100% 占等效完全充电时间的比例。"""

SOC_INITIAL = 1.0
"""所有能源资源初始 SOC = 100%。"""

SOC_TOL = 1e-6
"""SOC 比较容差。"""


# ---------------------------------------------------------------- 附录 3：通信链路

FSPL_CONSTANT = 32.45
"""FSPL 常数项：L = 32.45 + 20log10(f_MHz) + 20log10(D_km)。"""

M_TO_KM = 1000.0
"""★ 单位换算：内部距离单位是 m，代入 FSPL 前必须除以该值。"""

OBSTRUCTION_ADDITIONAL_LOSS_DB = None
"""地形遮挡附加损耗 L_obs，**取值见通信链路参数.xlsx**，由 P0 阶段回填。"""


# ---------------------------------------------------------------- 数值容差

PAYLOAD_ROOT_TOL = 1e-6
"""最大安全载荷反解（brentq）的收敛容差。"""

ENERGY_FEASIBILITY_TOL = 1e-6
"""能量约束回代验证的相对容差。"""

TIME_TOL = 1e-6
"""时间比较容差（秒）。"""


# ---------------------------------------------------------------- 连续通信判定

COMM_SAMPLE_DT_S = 1.0
"""连续通信判定的采样步长（秒）。

★ 题目要求运输无人机在爬升/巡航/下降/投送**全程**保持通信，
  因此必须沿航段逐时刻采样（ADR-007）。该步长须做**敏感性分析**，
  并在论文中说明取值依据与对结论的影响。
"""

COMM_SAMPLE_DISTANCE_M = 50.0
"""备选采样方式：按航段距离步长采样（米）。

当航段很长而速度较慢时，按距离采样比按时间采样更节省计算量。
实现时二者取其一，并在论文中说明。
"""


# ---------------------------------------------------------------- 问题规模提示

N_TASK_GROUPS = (2, 3)
"""Q4 要求考察的任务分组数。"""
