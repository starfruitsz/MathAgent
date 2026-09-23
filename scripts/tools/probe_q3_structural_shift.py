"""临时探针：验证 Q3 结构性转移的前提是否成立（不属于交付物，验证后删除）。"""
import numpy as np
from scipy.optimize import minimize

ETA = 2e-4
LCTX = 30000  # 取临界值
G = {"exp": (1e7, 6.0), "pow": (5e9, 4.0), "log": (2e9, 10.0)}


def gval(kind, Q):
    gm, lam = G[kind]
    if kind == "exp":
        return gm * np.exp(lam * Q)
    if kind == "pow":
        return gm * Q**lam
    return gm * np.log(1 + lam * Q)


E, A, ALPHA, B, BETA, GAM = 1.8, 400.0, 0.34, 400.0, 0.28, 0.6


def unpack(x):
    N, D = np.exp(x[0]), np.exp(x[1])
    Q = 1.0 / (1.0 + np.exp(-x[2]))
    return N, D, min(max(Q, 1e-4), 1.0)


def loss(x):
    N, D, Q = unpack(x)
    return E + A * N**-ALPHA + B * (D**-BETA) * (Q**-GAM)


def make_cost(C, kind, Q0=0.5):
    def cost(x):
        N, D, Q = unpack(x)
        Cq = max(gval(kind, Q) - gval(kind, Q0), 0.0) * D
        return 6 * N * D + Cq + ETA * N * D * LCTX - C

    return cost


def solve(C, kind, n_starts=16, Q0=0.5):
    cost = make_cost(C, kind, Q0)
    best = None
    for s in range(n_starts):
        rng = np.random.default_rng(s)
        x0 = np.array([rng.uniform(6, 14), rng.uniform(7, 15), rng.uniform(-3, 3)])
        try:
            r = minimize(
                loss,
                x0,
                constraints=[{"type": "ineq", "fun": lambda x: -cost(x)}],
                method="SLSQP",
                options={"maxiter": 800, "ftol": 1e-12},
            )
        except Exception:
            continue
        if r.success and (best is None or r.fun < best.fun):
            best = r
    if best is None:
        return None
    N, D, Q = unpack(best.x)
    Cq = max(gval(kind, Q) - gval(kind, Q0), 0.0) * D
    Ct, Ca = 6 * N * D, ETA * N * D * LCTX
    return dict(
        N=N, D=D, Q=Q, loss=best.fun,
        share_Cq=Cq / C, share_Ct=Ct / C, share_Ca=Ca / C,
        N_over_D=N / D,
    )


hdr = f"{'g(Q)':<6}{'budget':>9}{'N':>11}{'D':>12}{'Q':>8}{'loss':>9}{'质量占比':>10}{'训练占比':>10}{'注意占比':>10}"
print(hdr)
print("-" * len(hdr))
for kind in ["exp", "pow", "log"]:
    for C in [1e19, 1e22, 1e24]:
        r = solve(C, kind)
        if r is None:
            print(f"{kind:<6}{C:>9.0e}   FAILED")
            continue
        print(
            f"{kind:<6}{C:>9.0e}{r['N']:>11.3e}{r['D']:>12.3e}{r['Q']:>8.3f}"
            f"{r['loss']:>9.4f}{r['share_Cq']:>10.4f}{r['share_Ct']:>10.4f}{r['share_Ca']:>10.4f}"
        )
