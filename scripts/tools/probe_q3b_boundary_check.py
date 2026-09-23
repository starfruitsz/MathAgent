"""临时探针 2：检查 Q*=1 边界解是否稳健（决定 Q3 是否"太容易"）。"""
import numpy as np
from scipy.optimize import minimize

ETA = 2e-4
LCTX = 30000
G = {"exp": (1e7, 6.0), "pow": (5e9, 4.0), "log": (2e9, 10.0)}


def gval(kind, Q):
    gm, lam = G[kind]
    if kind == "exp":
        return gm * np.exp(lam * Q)
    if kind == "pow":
        return gm * Q**lam
    return gm * np.log(1 + lam * Q)


def run(C, kind, gam, Q0=0.5, n_starts=16):
    """用 logit 参数化避免溢出，并显式限制 Q<=1。"""
    E, A, ALPHA, B, BETA = 1.8, 400.0, 0.34, 400.0, 0.28

    def unpack(x):
        N, D = np.exp(np.clip(x[0], -30, 30)), np.exp(np.clip(x[1], -30, 30))
        Q = 1.0 / (1.0 + np.exp(-np.clip(x[2], -30, 30)))
        return N, D, min(max(Q, 1e-4), 1.0)

    def loss(x):
        N, D, Q = unpack(x)
        return E + A * N**-ALPHA + B * (D**-BETA) * (Q**-gam)

    def cost(x):
        N, D, Q = unpack(x)
        Cq = max(gval(kind, Q) - gval(kind, Q0), 0.0) * D
        return 6 * N * D + Cq + ETA * N * D * LCTX - C

    best = None
    for s in range(n_starts):
        rng = np.random.default_rng(s)
        x0 = np.array([rng.uniform(6, 14), rng.uniform(7, 15), rng.uniform(-3, 3)])
        with np.errstate(all="ignore"):
            r = minimize(loss, x0, constraints=[{"type": "ineq", "fun": lambda x: -cost(x)}],
                         method="SLSQP", options={"maxiter": 800, "ftol": 1e-12})
        if r.success and np.isfinite(r.fun) and (best is None or r.fun < best.fun):
            best = r
    if best is None:
        return None
    N, D, Q = unpack(best.x)
    Cq = max(gval(kind, Q) - gval(kind, Q0), 0.0) * D
    return dict(N=N, D=D, Q=Q, share_Cq=Cq / C, interior=bool(1e-3 < Q < 1 - 1e-3))


print("扫描质量损失弹性 gamma，观察 Q* 是否为内点解（Q*<1）")
print(f"{'kind':<6}{'gamma':>7}{'Q*@1e19':>10}{'Q*@1e22':>10}{'Q*@1e24':>10}{'内点?':>8}")
print("-" * 52)
for kind in ["exp", "pow", "log"]:
    for gam in [0.2, 0.6, 1.5, 3.0]:
        qs = []
        interior_any = False
        for C in [1e19, 1e22, 1e24]:
            r = run(C, kind, gam)
            if r is None:
                qs.append(float("nan"))
                continue
            qs.append(r["Q"])
            interior_any = interior_any or r["interior"]
        print(f"{kind:<6}{gam:>7.1f}{qs[0]:>10.3f}{qs[1]:>10.3f}{qs[2]:>10.3f}{'是' if interior_any else '否':>8}")
