#!/usr/bin/env python3
"""
Backtest "walk-forward": para cada dia de jogos, ajusta o modelo só com
resultados ANTERIORES a esse dia e prevê os jogos desse dia.

Compara:
  * modelo novo (scripts/model.py)
  * modelo antigo (últimos 5 jogos, sem suavização)
  * baseline (frequência histórica H/D/A da liga)

Métricas (menor é melhor): Brier score (3 classes) e log-loss.
Também mostra a calibração: quando o modelo diz X%, acerta X%?

Uso:
  python scripts/backtest.py                 # descarrega da internet
  python scripts/backtest.py --dir pasta/    # ficheiros locais
  python scripts/backtest.py --season 2025-26
"""

import argparse
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model  # noqa: E402
import update_data as ud  # noqa: E402

MIN_TRAIN = 40  # mínimo de resultados antes de começar a avaliar


# ---------- Modelo antigo (para comparação) ----------

def old_predict(home, away, results, ref_date, home_adv=0.28, n=5, avg=1.35):
    past = [r for r in results if r["date"] < ref_date]

    def recent(team):
        g = []
        for r in sorted((r for r in past if team in (r["home"], r["away"])), key=lambda r: r["date"]):
            if r["home"] == team:
                g.append((r["hg"], r["ag"], True))
            else:
                g.append((r["ag"], r["hg"], False))
        return g[-n:]

    def side(games, is_home):
        sel = [g for g in games if g[2] == is_home] or games
        if not sel:
            return avg, avg
        return (sum(g[0] for g in sel) / len(sel), sum(g[1] for g in sel) / len(sel))

    h_att, h_def = side(recent(home), True)
    a_att, a_def = side(recent(away), False)
    lh = max(0.2, h_att * (a_def / avg) + home_adv)
    la = max(0.15, a_att * (h_def / avg))
    ph = pd = pa = 0.0
    for i in range(7):
        for j in range(7):
            p = model.poisson(lh, i) * model.poisson(la, j)
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    s = ph + pd + pa
    return ph / s, pd / s, pa / s


# ---------- Métricas ----------

def outcome(r):
    return 0 if r["hg"] > r["ag"] else (1 if r["hg"] == r["ag"] else 2)


def brier(p, y):
    return sum((p[k] - (1.0 if k == y else 0.0)) ** 2 for k in range(3))


def logloss(p, y):
    return -math.log(max(p[y], 1e-9))


class Acc:
    def __init__(self):
        self.n = self.hits = 0
        self.b = self.l = 0.0

    def add(self, p, y):
        self.n += 1
        self.hits += int(max(range(3), key=lambda k: p[k]) == y)
        self.b += brier(p, y)
        self.l += logloss(p, y)

    def row(self, name):
        if not self.n:
            return f"{name:<22} (sem dados)"
        return (f"{name:<22} acerto {self.hits / self.n * 100:5.1f}%   "
                f"Brier {self.b / self.n:.4f}   log-loss {self.l / self.n:.4f}")


def run(code, season, prev_season, local_dir):
    cur_raw = ud.load_matches(season, code, local_dir)
    try:
        prev_raw = ud.load_matches(prev_season, code, local_dir)
    except Exception:  # noqa: BLE001
        prev_raw = []
    cur = ud.to_results(cur_raw)
    prev = ud.to_results(prev_raw, prev=True)
    cur.sort(key=lambda r: r["date"])

    new, old, base = Acc(), Acc(), Acc()
    calib = defaultdict(lambda: [0, 0, 0.0])  # bucket -> [n, hits, soma p]
    days = sorted({r["date"] for r in cur})

    for d in days:
        train = [r for r in cur if r["date"] < d]
        if len(train) < MIN_TRAIN:
            continue
        m = model.fit(train + prev, d)
        # baseline: frequência no treino
        freq = [0, 0, 0]
        for r in train:
            freq[outcome(r)] += 1
        pb = [f / len(train) for f in freq]

        for r in (x for x in cur if x["date"] == d):
            y = outcome(r)
            pr = model.predict(r["home"], r["away"], m)
            p_new = [pr["prob_home"] / 100, pr["prob_draw"] / 100, pr["prob_away"] / 100]
            p_old = old_predict(r["home"], r["away"], train, d)
            new.add(p_new, y)
            old.add(p_old, y)
            base.add(pb, y)
            top = max(range(3), key=lambda k: p_new[k])
            bucket = min(int(p_new[top] * 10) / 10, 0.9)
            c = calib[bucket]
            c[0] += 1
            c[1] += int(top == y)
            c[2] += p_new[top]

    return new, old, base, calib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--season")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    season = args.season or ud.season_for(today)
    prev_season = ud.season_for(date(int(season[:4]), 8, 1), -1)

    tot_new, tot_old, tot_base = Acc(), Acc(), Acc()
    tot_cal = defaultdict(lambda: [0, 0, 0.0])

    print(f"Backtest walk-forward · época {season} (anterior {prev_season})\n")
    for code, meta in ud.LEAGUES.items():
        try:
            new, old, base, cal = run(code, season, prev_season, args.dir)
        except Exception as e:  # noqa: BLE001
            print(f"{meta['name']}: erro ({e})\n")
            continue
        print(f"{meta['name']}  ({new.n} jogos avaliados)")
        print("  " + new.row("modelo novo"))
        print("  " + old.row("modelo antigo (5 jogos)"))
        print("  " + base.row("baseline (frequência)"))
        print()
        for acc, tot in ((new, tot_new), (old, tot_old), (base, tot_base)):
            tot.n += acc.n
            tot.hits += acc.hits
            tot.b += acc.b
            tot.l += acc.l
        for k, v in cal.items():
            for i in range(3):
                tot_cal[k][i] += v[i]

    print("TOTAL")
    print("  " + tot_new.row("modelo novo"))
    print("  " + tot_old.row("modelo antigo (5 jogos)"))
    print("  " + tot_base.row("baseline (frequência)"))
    print("\nCalibração do modelo novo (prob. da opção mais provável):")
    print("  faixa      jogos   prob. média   acertos")
    for k in sorted(tot_cal):
        n, hits, sp = tot_cal[k]
        if n:
            print(f"  {k * 100:3.0f}-{k * 100 + 10:3.0f}%   {n:5d}   {sp / n * 100:9.1f}%   {hits / n * 100:6.1f}%")


if __name__ == "__main__":
    main()
