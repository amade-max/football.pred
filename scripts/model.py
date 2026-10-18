"""
Modelo de previsão: Poisson com força de ataque/defesa por equipa.

Melhorias face à versão simples (últimos 5 jogos):
  * usa toda a época atual + a anterior, com decaimento exponencial no tempo;
  * força de ataque/defesa estimada de forma iterativa (ajusta pela qualidade
    dos adversários) e "encolhida" para a média da liga (pseudo-observações),
    o que evita valores extremos com poucos jogos;
  * mando de campo estimado dos dados (médias de golos em casa vs. fora);
  * golos esperados (lambda) limitados a um intervalo realista;
  * correção Dixon-Coles para placares baixos (0-0, 1-0, 0-1, 1-1);
  * suavização final das probabilidades em direção à frequência da liga.

Só usa a biblioteca padrão.
"""

import math
from collections import defaultdict
from datetime import date

# ---- Hiperparâmetros (podem ser afinados com scripts/backtest.py) ----
HALF_LIFE_DAYS = 120      # um jogo de há 120 dias pesa metade de um de hoje
PREV_SEASON_WEIGHT = 0.5  # peso extra dos jogos da época anterior
PRIOR_K = 6.0             # pseudo-golos que puxam cada equipa para a média
ITERATIONS = 80
LAMBDA_MIN, LAMBDA_MAX = 0.35, 3.3
MAX_GOALS = 8
RHO = -0.06               # Dixon-Coles: correlação em placares baixos
FLATTEN = 0.08            # mistura final com a frequência da liga
DEFAULT_BASE = (0.45, 0.26, 0.29)  # frequência H/D/A de reserva

# Limiares do nível de confiança (jogos efetivos da equipa com menos dados)
CONF_HIGH_MARGIN, CONF_HIGH_EFF = 22.0, 5.0
CONF_MID_MARGIN, CONF_MID_EFF = 10.0, 3.0


def poisson(lmbda, k):
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lmbda + k * math.log(lmbda) - math.lgamma(k + 1))


def _tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return 1.0 - lh * la * rho
    if i == 0 and j == 1:
        return 1.0 + lh * rho
    if i == 1 and j == 0:
        return 1.0 + la * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def fit(results, ref_date, half_life=HALF_LIFE_DAYS, prior_k=PRIOR_K):
    """
    results: lista de dicts {date: date, home, away, hg, ag, prev: bool}
    Devolve dict com base_home, base_away, att, dfn, eff, base_probs.
    """
    if not results:
        return {
            "base_home": 1.5, "base_away": 1.2, "att": {}, "dfn": {},
            "eff": {}, "n": 0, "base_probs": DEFAULT_BASE,
        }

    rows = []
    for r in results:
        age = max(0, (ref_date - r["date"]).days)
        w = 0.5 ** (age / half_life)
        if r.get("prev"):
            w *= PREV_SEASON_WEIGHT
        rows.append((r["home"], r["away"], r["hg"], r["ag"], w))

    total_w = sum(r[4] for r in rows)
    base_home = sum(r[2] * r[4] for r in rows) / total_w
    base_away = sum(r[3] * r[4] for r in rows) / total_w
    base_home = max(base_home, 0.3)
    base_away = max(base_away, 0.3)

    # frequência de H/D/A (para suavização final)
    wh = sum(r[4] for r in rows if r[2] > r[3])
    wd = sum(r[4] for r in rows if r[2] == r[3])
    wa = sum(r[4] for r in rows if r[2] < r[3])
    base_probs = (wh / total_w, wd / total_w, wa / total_w)

    teams = {t for r in rows for t in (r[0], r[1])}
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    eff = defaultdict(float)
    for h, a, _, _, w in rows:
        eff[h] += w
        eff[a] += w

    for _ in range(ITERATIONS):
        # ataque: golos marcados / golos esperados com att=1
        num = defaultdict(float)
        den = defaultdict(float)
        for h, a, hg, ag, w in rows:
            num[h] += w * hg
            den[h] += w * base_home * dfn[a]
            num[a] += w * ag
            den[a] += w * base_away * dfn[h]
        for t in teams:
            att[t] = (num[t] + prior_k) / (den[t] + prior_k)

        # defesa: golos sofridos / golos esperados com dfn=1
        num = defaultdict(float)
        den = defaultdict(float)
        for h, a, hg, ag, w in rows:
            num[h] += w * ag
            den[h] += w * base_away * att[a]
            num[a] += w * hg
            den[a] += w * base_home * att[h]
        for t in teams:
            dfn[t] = (num[t] + prior_k) / (den[t] + prior_k)

    return {
        "base_home": base_home,
        "base_away": base_away,
        "att": att,
        "dfn": dfn,
        "eff": dict(eff),
        "n": len(rows),
        "base_probs": base_probs,
    }


def _clamp(x):
    return max(LAMBDA_MIN, min(LAMBDA_MAX, x))


def expected_goals(home, away, model):
    lam_h = model["base_home"] * model["att"].get(home, 1.0) * model["dfn"].get(away, 1.0)
    lam_a = model["base_away"] * model["att"].get(away, 1.0) * model["dfn"].get(home, 1.0)
    return _clamp(lam_h), _clamp(lam_a)


def score_matrix(lam_h, lam_a, rho=RHO):
    m = {}
    total = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = poisson(lam_h, i) * poisson(lam_a, j) * _tau(i, j, lam_h, lam_a, rho)
            m[(i, j)] = max(p, 0.0)
            total += m[(i, j)]
    return {k: v / total for k, v in m.items()}


def _round_probs(ph, pd, pa):
    h = round(ph * 100, 1)
    d = round(pd * 100, 1)
    a = round(100.0 - h - d, 1)
    return h, d, a


def predict(home, away, model, flatten=FLATTEN):
    lam_h, lam_a = expected_goals(home, away, model)
    mat = score_matrix(lam_h, lam_a)

    ph = sum(p for (i, j), p in mat.items() if i > j)
    pd = sum(p for (i, j), p in mat.items() if i == j)
    pa = sum(p for (i, j), p in mat.items() if i < j)

    bh, bd, ba = model["base_probs"]
    ph = (1 - flatten) * ph + flatten * bh
    pd = (1 - flatten) * pd + flatten * bd
    pa = (1 - flatten) * pa + flatten * ba
    s = ph + pd + pa
    ph, pd, pa = ph / s, pd / s, pa / s

    over25 = sum(p for (i, j), p in mat.items() if i + j >= 3)
    btts = sum(p for (i, j), p in mat.items() if i >= 1 and j >= 1)
    top_score = max(mat, key=mat.get)

    probs = dict(zip("HDA", _round_probs(ph, pd, pa)))
    best = max(probs, key=probs.get)
    ordered = sorted(probs.values(), reverse=True)
    margin = round(ordered[0] - ordered[1], 1)

    eff_h = model["eff"].get(home, 0.0)
    eff_a = model["eff"].get(away, 0.0)
    eff_min = min(eff_h, eff_a)

    if margin >= CONF_HIGH_MARGIN and eff_min >= CONF_HIGH_EFF:
        level = "alta"
    elif margin >= CONF_MID_MARGIN and eff_min >= CONF_MID_EFF:
        level = "média"
    else:
        level = "baixa"

    labels = {"H": "Casa", "D": "Empate", "A": "Fora"}
    return {
        "lambda_home": round(lam_h, 2),
        "lambda_away": round(lam_a, 2),
        "prob_home": probs["H"],
        "prob_draw": probs["D"],
        "prob_away": probs["A"],
        "best_bet": best,
        "best_bet_label": labels[best],
        "best_bet_prob": probs[best],
        "confidence": margin,
        "conf_level": level,
        "data_games": round(eff_min, 1),
        "top_score": f"{top_score[0]}-{top_score[1]}",
        "over25": round(over25 * 100),
        "btts": round(btts * 100),
    }


# ---- Utilidades ----

def form_string(results, team, n=5):
    """Últimos n resultados da equipa (W/D/L), o mais recente à esquerda."""
    games = sorted(
        (r for r in results if team in (r["home"], r["away"])),
        key=lambda r: r["date"],
    )[-n:]
    out = []
    for r in games:
        gf, ga = (r["hg"], r["ag"]) if r["home"] == team else (r["ag"], r["hg"])
        out.append("W" if gf > ga else ("D" if gf == ga else "L"))
    return "".join(reversed(out)) if out else "—"


def parse_date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None
