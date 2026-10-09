"""
CFB Mechanism Audit #2 -- Team Form v1 (opponent-adjusted exponentially-weighted SRS, H=3)

Executed under the FROZEN pre-registration (docs/cfb_mechanism_audit_02_preregistration.md).
Nothing here is chosen at run time: population, weighting, half-life, eligibility, uncertainty
procedure, success/failure criteria and the decision rule are all frozen. This script only
produces the Team Form v1 result on the frozen, paired population and reports the mechanical
verdict against the frozen criteria. Interpretation beyond those boundaries is a separate gate.

Guard: recompute the eligible-game fingerprint; ABORT on mismatch (rolling CFBD fetch).
Read-only. Run: py -3 research/cfb_mechanism/audit_team_form_w1.py
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_opponent_adjusted_strength as a1          # _load, _srs, _wilson, consts
import freeze_audit2_population as fz                   # eligible_games, fingerprint, manifest

H = 3.0            # FROZEN half-life (weeks)
MIN_DISAGREE = 200  # FROZEN decisive-test floor
BREAKEVEN = 52.4    # FROZEN hypothetical -110 reference
INFO = 50.0         # FROZEN informational threshold


def _srs_weighted(prior: pd.DataFrame, target_week: int):
    """SRS with recency weights w=0.5**((target_week-game_week)/H); rows scaled by sqrt(w).
    Gauge (sum-to-zero) row keeps weight a1.RIDGE, unweighted. Frozen objective, Audit #2 S1."""
    teams = pd.Index(sorted(set(prior["Home"]) | set(prior["Away"])))
    idx = {t: i for i, t in enumerate(teams)}
    nt = len(teams)
    rows = len(prior)
    A = np.zeros((rows + 1, nt + 1))
    b = np.zeros(rows + 1)
    for r, (_, g) in enumerate(prior.iterrows()):
        w = 0.5 ** ((target_week - g["Week"]) / H)
        s = math.sqrt(w)
        A[r, idx[g["Home"]]] = s
        A[r, idx[g["Away"]]] = -s
        A[r, nt] = s
        b[r] = s * g["margin"]
    A[rows, :nt] = a1.RIDGE
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return {t: float(sol[idx[t]]) for t in teams}, float(sol[nt])


def _wlo(k, n):
    lo, _ = a1._wilson(k, n)
    return lo


def main() -> int:
    df = a1._load()
    df = df[df["Season"].isin(fz.EVAL_SEASONS)]
    rec = []
    for season, sdf in df.groupby("Season"):
        for week in sorted(sdf["Week"].unique()):
            if week < a1.MIN_WEEK:
                continue
            prior = sdf[sdf["Week"] < week]
            if len(prior) < 20:
                continue
            ra, hfa_a, rated = a1._srs(prior)              # Model A: cumulative SRS (Audit #1)
            rb, hfa_b = _srs_weighted(prior, week)          # Model B: Team Form v1 (H=3)
            for _, g in sdf[sdf["Week"] == week].iterrows():
                h, a = g["Home"], g["Away"]
                if h not in rated or a not in rated or g["ats_home"] == 0:
                    continue
                predA = ra[h] - ra[a] + hfa_a
                predB = rb[h] - rb[a] + hfa_b
                rec.append({
                    "season": int(season), "week": int(week), "away": str(a), "home": str(h),
                    "hspread": round(float(g["HSpread"]), 1), "margin": int(g["margin"]),
                    "ats_home": int(g["ats_home"]), "predA": predA, "predB": predB,
                })
    p = pd.DataFrame(rec)

    # ---- FINGERPRINT GUARD (frozen population, abort on mismatch) ----
    man = json.loads((HERE / "audit2_frozen_population.json").read_text(encoding="utf-8"))
    fp = fz.fingerprint(p[["season", "week", "away", "home", "hspread", "margin"]].to_dict("records"))
    if len(p) != man["n_eligible"] or fp != man["sha256"]:
        print(f"[ABORT] population mismatch: n={len(p)} (frozen {man['n_eligible']}), "
              f"sha256={fp[:12]}.. (frozen {man['sha256'][:12]}..). Re-freeze + re-review required.")
        return 2
    print("Audit #2 -- Team Form v1 (H=3) | fingerprint OK, population frozen & paired\n")

    # ---- predictions -> sides (frozen tie rule: edge==0 => no-action) ----
    p["edgeA"] = p["predA"] + p["hspread"]
    p["edgeB"] = p["predB"] + p["hspread"]
    p["sideA"] = np.sign(p["edgeA"]).astype(int)
    p["sideB"] = np.sign(p["edgeB"]).astype(int)
    p["coverA"] = np.where(p["sideA"] == 0, np.nan, (p["sideA"] == p["ats_home"]).astype(float))
    p["coverB"] = np.where(p["sideB"] == 0, np.nan, (p["sideB"] == p["ats_home"]).astype(float))

    # ---- S7(I) margin error (full paired population) ----
    errA = (p["predA"] - p["margin"]).abs()
    errB = (p["predB"] - p["margin"]).abs()
    errS = ((-p["hspread"]) - p["margin"]).abs()
    maeA, maeB, maeS = errA.mean(), errB.mean(), errS.mean()
    rmseA = math.sqrt((errA ** 2).mean()); rmseB = math.sqrt((errB ** 2).mean())
    rmseS = math.sqrt((errS ** 2).mean())
    print(f"  margin error (paired n={len(p)}):")
    print(f"    spread  MAE={maeS:5.2f}  RMSE={rmseS:5.2f}")
    print(f"    A (cum) MAE={maeA:5.2f}  RMSE={rmseA:5.2f}")
    print(f"    B (form)MAE={maeB:5.2f}  RMSE={rmseB:5.2f}   -> B reduces MAE vs A: {bool(maeB < maeA)}")

    # ---- overall ATS cover (context) ----
    def cov(mask, colname):
        s = p.loc[mask, colname].dropna()
        k, n = int(s.sum()), int(len(s))
        lo, hi = a1._wilson(k, n)
        return k, n, (k / n * 100 if n else float("nan")), lo, hi
    for col, lbl in (("coverA", "A (cumulative)"), ("coverB", "B (team form)")):
        k, n, pct, lo, hi = cov(p.index.to_series().astype(bool) | True, col)
        print(f"  ATS cover {lbl:<16} n={n:>5} {pct:5.1f}%  95%CI[{lo}, {hi}]")

    # ---- S7 DECISIVE: disagreement subset (A and B opposite, non-zero) ----
    dis = p[(p["sideA"] != 0) & (p["sideB"] != 0) & (p["sideA"] != p["sideB"])].copy()
    nd = len(dis)
    kB = int((dis["sideB"] == dis["ats_home"]).sum())
    coverBdis = kB / nd * 100 if nd else float("nan")
    loB, hiB = a1._wilson(kB, nd)
    print(f"\n  DISAGREEMENT subset (recency flipped A's side): n={nd}")
    print(f"    B cover on flips = {coverBdis:.1f}%  95%CI[{loB}, {hiB}]  (A would be {100-coverBdis:.1f}%)")

    # per-season (frozen: seasons with >=30 flips count toward stability)
    per = {}
    for s in sorted(dis["season"].unique()):
        ds = dis[dis["season"] == s]
        kk, nn = int((ds["sideB"] == ds["ats_home"]).sum()), len(ds)
        per[int(s)] = (kk, nn, kk / nn * 100 if nn else float("nan"))
        print(f"      {int(s)}: n={nn:>4}  B cover={per[int(s)][2]:5.1f}%"
              + ("" if nn >= 30 else "   (<30, excluded from stability)"))

    # ---- FROZEN composite rule (Option A) for the informational claim (50%) ----
    elig_seasons = {s: v for s, v in per.items() if v[1] >= 30}
    maj = sum(1 for s, v in elig_seasons.items() if v[2] > INFO)
    # leave-one-season-out: remove best season, does overall still clear 50%?
    if nd:
        best = max(per, key=lambda s: per[s][2]) if per else None
        loo = dis[dis["season"] != best]
        loo_cov = (loo["sideB"] == loo["ats_home"]).mean() * 100 if len(loo) else float("nan")
    else:
        best, loo_cov = None, float("nan")
    c_n = nd >= MIN_DISAGREE
    c_wilson_info = (loB is not None and loB > INFO)
    c_major = maj >= 3
    c_notdom = (loo_cov > INFO)
    info_pass = c_n and c_wilson_info and c_major and c_notdom

    c_wilson_bet = (loB is not None and loB > BREAKEVEN)
    loo_bet = (loo_cov > BREAKEVEN)
    major_bet = sum(1 for s, v in elig_seasons.items() if v[2] > BREAKEVEN) >= 3
    bet_pass = c_n and c_wilson_bet and major_bet and loo_bet

    print("\n  FROZEN composite rule (Option A):")
    print(f"    disagreement n>=200 .............. {c_n}  (n={nd})")
    print(f"    informational (50%):  WilsonLB>50 = {c_wilson_info} (LB={loB}) | "
          f">=3/5 seasons = {c_major} ({maj}) | LOO>50 = {c_notdom} (drop {best}, {loo_cov:.1f}%)")
    print(f"    betting-edge (52.4%): WilsonLB>52.4= {c_wilson_bet} (LB={loB}) | "
          f">=3/5 seasons = {major_bet} | LOO>52.4 = {loo_bet}")

    # ---- FROZEN decision rule ----
    mae_better = bool(maeB < maeA)
    if not c_n:
        verdict = "UNDERPOWERED -> No demonstrated incremental edge"
    elif mae_better and info_pass and bet_pass:
        verdict = "GRADUATE -- informational AND betting-edge (research only; NO build)"
    elif mae_better and info_pass:
        verdict = "GRADUATE (informational only) -- adds info, no betting-edge claim (research only; NO build)"
    else:
        verdict = "No demonstrated incremental edge -- Audit #1 SRS remains the benchmark"
    print(f"\n  margin MAE improved vs A: {mae_better}")
    print(f"  VERDICT (frozen): {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
