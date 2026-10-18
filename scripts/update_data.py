#!/usr/bin/env python3
"""
Atualiza os dados das 5 grandes ligas a partir de openfootball/football.json
e gera previsões com o modelo de scripts/model.py.

Uso:
  python scripts/update_data.py                 # descarrega da internet
  python scripts/update_data.py --dir pasta/    # lê ficheiros locais
                                                # (pasta/<época>-<liga>.json)
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model  # noqa: E402

LEAGUES = {
    "en.1": {"name": "Premier League", "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "tz": "Europe/London"},
    "es.1": {"name": "La Liga", "flag": "🇪🇸", "tz": "Europe/Madrid"},
    "it.1": {"name": "Serie A", "flag": "🇮🇹", "tz": "Europe/Rome"},
    "de.1": {"name": "Bundesliga", "flag": "🇩🇪", "tz": "Europe/Berlin"},
    "fr.1": {"name": "Ligue 1", "flag": "🇫🇷", "tz": "Europe/Paris"},
}

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"
UPCOMING_LIMIT = 30
RECENT_LIMIT = 30
STALE_DAYS = 7  # aviso se o último resultado for mais antigo que isto


# ---------- Época ----------

def season_for(d: date, offset: int = 0) -> str:
    """Época europeia (ago-mai) que contém a data d. offset=-1 → anterior."""
    start = d.year if d.month >= 7 else d.year - 1
    start += offset
    return f"{start}-{(start + 1) % 100:02d}"


# ---------- Leitura ----------

def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "football-predictor/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def load_raw(season: str, code: str, local_dir):
    if local_dir:
        p = Path(local_dir) / f"{season}-{code}.json"
        if not p.exists():
            raise FileNotFoundError(p)
        return json.loads(p.read_text(encoding="utf-8"))
    return fetch_json(f"{BASE_URL}/{season}/{code}.json")


def normalize_score(score):
    """Aceita {'ft': [h,a]} ou [h,a]; devolve (h, a) ou None."""
    if score is None:
        return None
    ft = score.get("ft") if isinstance(score, dict) else score
    if isinstance(ft, (list, tuple)) and len(ft) >= 2:
        try:
            return int(ft[0]), int(ft[1])
        except (TypeError, ValueError):
            return None
    return None


def kickoff_utc(date_s: str, time_s: str, tz: ZoneInfo):
    """Hora de início em UTC (ISO) ou None se a hora for desconhecida."""
    if not date_s or not time_s:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})", time_s.strip())
    if not m:
        return None
    try:
        d = date.fromisoformat(date_s)
        local = datetime(d.year, d.month, d.day, int(m.group(1)), int(m.group(2)), tzinfo=tz)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).isoformat()


def load_matches(season: str, code: str, local_dir=None):
    """Lista de jogos 'crus' (dicts do openfootball) de uma época/liga."""
    return load_raw(season, code, local_dir).get("matches", [])


def to_results(raw_matches, prev=False):
    out = []
    for m in raw_matches:
        sc = normalize_score(m.get("score"))
        d = model.parse_date(m.get("date"))
        if sc is None or d is None:
            continue
        out.append({
            "date": d, "home": m.get("team1", ""), "away": m.get("team2", ""),
            "hg": sc[0], "ag": sc[1], "prev": prev,
        })
    return out


# ---------- Processamento ----------

def process_league(code, meta, season, prev_season, local_dir, now):
    raw = load_matches(season, code, local_dir)
    try:
        prev_raw = load_matches(prev_season, code, local_dir)
    except (urllib.error.URLError, FileNotFoundError, OSError, ValueError) as e:
        print(f"  (sem época anterior {prev_season}: {e})")
        prev_raw = []

    results = to_results(raw) + to_results(prev_raw, prev=True)
    fitted = model.fit(results, now.date())

    tz = ZoneInfo(meta["tz"])
    today = now.date().isoformat()
    upcoming, recent, pending_past = [], [], 0

    for m in raw:
        sc = normalize_score(m.get("score"))
        entry = {
            "round": m.get("round", ""),
            "date": m.get("date", ""),
            "time": m.get("time", ""),
            "home": m.get("team1", ""),
            "away": m.get("team2", ""),
        }
        if sc is not None:
            entry["score"] = f"{sc[0]}-{sc[1]}"
            entry["result"] = "H" if sc[0] > sc[1] else ("A" if sc[1] > sc[0] else "D")
            recent.append(entry)
        elif entry["date"] >= today:
            entry["kickoff_utc"] = kickoff_utc(entry["date"], entry["time"], tz)
            entry.update(model.predict(entry["home"], entry["away"], fitted))
            entry["form_home"] = model.form_string(results, entry["home"])
            entry["form_away"] = model.form_string(results, entry["away"])
            upcoming.append(entry)
        elif entry["date"]:
            pending_past += 1  # jogo passado ainda sem resultado na fonte

    upcoming.sort(key=lambda x: (x["date"], x["time"]))
    recent.sort(key=lambda x: (x["date"], x["time"]), reverse=True)

    cur_results = [r for r in results if not r["prev"]]
    latest = max((r["date"] for r in cur_results), default=None)

    current_teams = {x for m in raw for x in (m.get("team1"), m.get("team2"))}
    teams = {}
    for t in sorted(t for t in fitted["att"] if t in current_teams):
        teams[t] = {
            "attack": round(fitted["att"][t], 2),
            "defense": round(fitted["dfn"][t], 2),  # <1 = defesa melhor
            "games_eff": round(fitted["eff"].get(t, 0.0), 1),
            "form": model.form_string(results, t),
        }

    return {
        "code": code,
        "name": meta["name"],
        "flag": meta["flag"],
        "season": season,
        "matches_used": len(cur_results),
        "matches_used_prev": len(results) - len(cur_results),
        "latest_result": latest.isoformat() if latest else None,
        "pending_past": pending_past,
        "avg_goals_home": round(fitted["base_home"], 2),
        "avg_goals_away": round(fitted["base_away"], 2),
        "upcoming": upcoming[:UPCOMING_LIMIT],
        "recent": recent[:RECENT_LIMIT],
        "teams": teams,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="pasta com ficheiros locais <época>-<liga>.json")
    ap.add_argument("--season", help="forçar época, ex.: 2026-27")
    ap.add_argument("--out", help="ficheiro de saída (por omissão data/matches.json)")
    ap.add_argument("--provisional", action="store_true",
                    help="marca os dados como provisórios (amostra parcial)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = args.season or season_for(now.date())
    prev_season = season_for(date(int(season[:4]), 8, 1), -1)

    out_path = Path(args.out) if args.out else \
        Path(__file__).resolve().parent.parent / "data" / "matches.json"
    out_path.parent.mkdir(exist_ok=True)

    old = {}
    if out_path.exists():
        try:
            old = {l["code"]: l for l in json.loads(out_path.read_text("utf-8")).get("leagues", [])}
        except (ValueError, KeyError):
            old = {}

    leagues, errors = [], 0
    for code, meta in LEAGUES.items():
        print(f"{meta['name']} ({season}, anterior {prev_season}) ...")
        try:
            lg = process_league(code, meta, season, prev_season, args.dir, now)
            print(f"  → {len(lg['upcoming'])} próximos, {lg['matches_used']} resultados usados, "
                  f"{len(lg['teams'])} equipas")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ERRO {code}: {e}")
            if code in old:
                lg = old[code]
                lg["stale_fetch"] = True  # mantém os dados anteriores
            else:
                continue
        leagues.append(lg)

    if not leagues:
        sys.exit("Nenhuma liga carregada; ficheiro existente mantido.")

    payload = {
        "generated_at": now.isoformat(),
        "season": season,
        "model": "poisson-attack-defense-shrinkage-dixon-coles",
        "model_version": 2,
        "provisional": bool(args.provisional),
        "leagues": leagues,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nGuardado → {out_path}")
    if errors and errors == len(LEAGUES):
        sys.exit(1)


if __name__ == "__main__":
    main()
