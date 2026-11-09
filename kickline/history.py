"""Match history: save every finished game's box score and key events, and turn
the archive into simple rolling team features the rater can use."""
from __future__ import annotations

from collections import defaultdict

from . import espn, store

THRESH = {"soccer": 2.0, "nfl": 7.0, "ncaaf": 10.0, "nba": 6.0, "mlb": 1.5}


def record_game(game: dict, hs, as_, summary: dict | None) -> dict:
    doc = {
        "id": game["id"], "sport": game["sport"], "league": game["league"], "start": game["start"],
        "home": {k: game["home"].get(k) for k in ("name", "abbr", "teamId")} | {"score": hs},
        "away": {k: game["away"].get(k) for k in ("name", "abbr", "teamId")} | {"score": as_},
        "odds": game.get("odds"), "espnWinProb": game.get("espnWinProb"),
    }
    if summary:
        doc.update(espn.parse_box(summary))
    store.save_history(game["id"], doc)
    return doc


def _num(v):
    try:
        return float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _team_key(sport: str, t: dict) -> str:
    return f"{sport}:{t.get('teamId') or t.get('abbr')}"


def build_index(docs: list[dict]) -> dict:
    idx = defaultdict(list)
    for d in docs:
        hs, as_ = _num(d["home"].get("score")), _num(d["away"].get("score"))
        if hs is None or as_ is None:
            continue
        sport = d["sport"]
        teams = d.get("teams") or {}
        for side, opp in (("home", "away"), ("away", "home")):
            mine, theirs = (hs, as_) if side == "home" else (as_, hs)
            row = {"start": d["start"], "for": mine, "against": theirs}
            if sport == "soccer":
                a = _num(((teams.get(side) or {}).get("stats") or {}).get("shotsOnTarget"))
                b = _num(((teams.get(opp) or {}).get("stats") or {}).get("shotsOnTarget"))
                if a is not None and b is not None:
                    row["sotFor"], row["sotAgainst"] = a, b
            idx[_team_key(sport, d[side])].append(row)
    for k in idx:
        idx[k].sort(key=lambda r: r["start"], reverse=True)
    return idx


def features(game: dict, idx: dict) -> dict | None:
    sport = game["sport"]
    out = {"threshold": THRESH.get(sport, 99)}
    rows = {}
    for side in ("home", "away"):
        rows[side] = [r for r in idx.get(_team_key(sport, game[side]), []) if r["start"] < (game.get("start") or "")][:5]
        if len(rows[side]) < 3:
            return None
    used_sot = sport == "soccer" and all("sotFor" in r for side in rows for r in rows[side])
    labels = []
    for side in ("home", "away"):
        if used_sot:
            out[side] = sum(r["sotFor"] - r["sotAgainst"] for r in rows[side]) / len(rows[side])
        else:
            out[side] = sum(r["for"] - r["against"] for r in rows[side]) / len(rows[side])
        labels.append(f"{game[side]['abbr']} {out[side]:+.1f}")
    if sport == "soccer" and not used_sot:
        out["threshold"] = 1.0
    what = "shots-on-target margin" if used_sot else "scoring margin"
    out["label"] = f"last-5 {what}: " + ", ".join(labels)
    return out
