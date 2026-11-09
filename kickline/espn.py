"""ESPN public JSON feeds: scoreboards, core odds, game summaries."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import requests

from .util import american_str, parse_iso

SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"

# key, espn sport, espn league, display league, extra query
LEAGUES = [
    ("nfl", "football", "nfl", "NFL", ""),
    ("ncaaf", "football", "college-football", "College Football", "groups=80&limit=400"),
    ("mlb", "baseball", "mlb", "MLB", ""),
    ("nba", "basketball", "nba", "NBA", ""),
]
SOCCER = {
    "eng.1": "Premier League", "esp.1": "LaLiga", "ita.1": "Serie A", "ger.1": "Bundesliga",
    "fra.1": "Ligue 1", "usa.1": "MLS", "mex.1": "Liga MX", "uefa.champions": "Champions League",
    "uefa.europa": "Europa League", "uefa.nations": "UEFA Nations League", "fifa.friendly": "International Friendly",
    "fifa.worldq.uefa": "World Cup Qualifying - UEFA",
}
for slug, name in SOCCER.items():
    LEAGUES.append(("soccer", "soccer", slug, name, ""))

SPORT_OF = {"nfl": ("football", "nfl"), "ncaaf": ("football", "college-football"), "mlb": ("baseball", "mlb"), "nba": ("basketball", "nba")}

_session = requests.Session()
_session.headers["User-Agent"] = "kickline-slate/1.0 (personal research board)"
OFFLINE = os.environ.get("KICKLINE_FIXTURES")  # folder of saved JSON for tests


def get(url: str, retries: int = 2) -> dict | None:
    if OFFLINE:
        from hashlib import md5
        p = os.path.join(OFFLINE, md5(url.encode()).hexdigest() + ".json")
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
        return None
    for i in range(retries + 1):
        try:
            r = _session.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 400):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (i + 1))
    return None


def league_path(sportkey: str, slug: str | None = None) -> tuple[str, str]:
    if sportkey == "soccer":
        return "soccer", slug
    return SPORT_OF[sportkey]


# ---------- scoreboard ----------
def scoreboard(espn_sport: str, espn_league: str, date: str, extra: str = "") -> list[dict]:
    q = f"dates={date}" + (f"&{extra}" if extra else "")
    data = get(f"{SITE}/{espn_sport}/{espn_league}/scoreboard?{q}")
    return (data or {}).get("events", []) or []


def _ml_from_block(block: dict, side: str, when: str):
    try:
        return american_str(block["moneyline"][side][when]["odds"])
    except (KeyError, TypeError):
        return None


def _line(block: dict, kind: str, side: str, when: str):
    try:
        return block[kind][side][when]["line"]
    except (KeyError, TypeError):
        return None


def parse_odds(o: dict | None, home_abbr: str, away_abbr: str) -> dict:
    if not o:
        return {}
    out = {"provider": (o.get("provider") or {}).get("name") or "DraftKings"}
    if o.get("details"):
        out["spread"] = o["details"]
    if o.get("overUnder") is not None:
        out["total"] = str(o["overUnder"])
    h = o.get("homeTeamOdds") or {}
    a = o.get("awayTeamOdds") or {}
    d = o.get("drawOdds") or {}
    out["mlHome"] = _ml_from_block(o, "home", "close") or american_str(h.get("moneyLine")) or _core_ml(h, "current")
    out["mlAway"] = _ml_from_block(o, "away", "close") or american_str(a.get("moneyLine")) or _core_ml(a, "current")
    draw = _ml_from_block(o, "draw", "close") or american_str(d.get("moneyLine"))
    if draw:
        out["mlDraw"] = draw
    out["mlHomeOpen"] = _ml_from_block(o, "home", "open") or _core_ml(h, "open")
    out["mlAwayOpen"] = _ml_from_block(o, "away", "open") or _core_ml(a, "open")
    so = _line(o, "pointSpread", "home", "open")
    if so is not None:
        try:
            v = float(str(so))
            fav = home_abbr if v < 0 else away_abbr
            out["spreadOpen"] = f"{fav} {-abs(v):g}" if v != 0 else "PK"
        except ValueError:
            pass
    to = _line(o, "total", "over", "open")
    if to is not None:
        out["totalOpen"] = str(to).lstrip("ou")
    return {k: v for k, v in out.items() if v not in (None, "")}


def _core_ml(team_odds: dict, when: str):
    try:
        return american_str(team_odds[when]["moneyLine"]["american"])
    except (KeyError, TypeError):
        return None


def core_odds(espn_sport: str, espn_league: str, event_id: str, home_abbr: str, away_abbr: str) -> dict:
    data = get(f"{CORE}/{espn_sport}/leagues/{espn_league}/events/{event_id}/competitions/{event_id}/odds")
    items = (data or {}).get("items") or []
    if not items:
        return {}
    items.sort(key=lambda x: 0 if "draft" in str((x.get("provider") or {}).get("name", "")).lower() else 1)
    return parse_odds(items[0], home_abbr, away_abbr)


def parse_event(ev: dict, sportkey: str, league_name: str, slug: str) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    teams = {}
    for c in comp.get("competitors", []):
        t = c.get("team", {})
        rank = (c.get("curatedRank") or {}).get("current")
        name = t.get("displayName") or t.get("shortDisplayName") or t.get("name") or "?"
        if sportkey == "ncaaf" and rank and rank <= 25:
            name = f"#{rank} {t.get('location') or name}"
        rec = (c.get("records") or [{}])[0].get("summary") if c.get("records") else None
        teams[c.get("homeAway")] = {
            "name": name, "abbr": t.get("abbreviation") or t.get("shortDisplayName") or name[:4].upper(),
            "record": rec, "score": c.get("score"), "winner": c.get("winner"), "teamId": t.get("id"),
            "short": t.get("shortDisplayName") or t.get("name"),
        }
    if "home" not in teams or "away" not in teams:
        return None
    st = (ev.get("status") or comp.get("status") or {}).get("type", {})
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    odds = parse_odds((comp.get("odds") or [None])[0], teams["home"]["abbr"], teams["away"]["abbr"])
    sport_path, league_path_ = league_path(sportkey, slug)
    gid = f"{sportkey}-{ev['id']}"
    link_sport = {"ncaaf": "college-football"}.get(sportkey, sportkey)
    link = f"https://www.espn.com/{link_sport}/{'match' if sportkey == 'soccer' else 'game'}/_/gameId/{ev['id']}"
    return {
        "id": gid, "espnId": ev["id"], "sport": sportkey, "league": league_name, "slug": slug,
        "espnSport": sport_path, "espnLeague": league_path_,
        "start": ev.get("date"), "state": st.get("state"), "completed": st.get("completed"),
        "statusName": st.get("name"), "statusDetail": st.get("detail") or st.get("shortDetail"),
        "venue": ", ".join(x for x in [venue.get("fullName"), addr.get("city")] if x),
        "home": teams["home"], "away": teams["away"], "odds": odds, "link": link,
    }


# ---------- summary ----------
def summary(espn_sport: str, espn_league: str, event_id: str) -> dict | None:
    return get(f"{SITE}/{espn_sport}/{espn_league}/summary?event={event_id}")


def parse_summary(s: dict, game: dict, now: datetime) -> dict:
    out: dict = {}
    start = parse_iso(game.get("start")) or now
    # predictor
    pr = s.get("predictor") or {}
    try:
        hp = float(pr["homeTeam"]["gameProjection"])
        ap = float(pr["awayTeam"]["gameProjection"])
        if hp + ap > 0:
            out["espnWinProb"] = {"home": round(hp, 1), "away": round(ap, 1)}
    except (KeyError, TypeError, ValueError):
        pass
    # injuries (only Out / Doubtful, fresh)
    abbr_side = {game["home"]["abbr"]: "home", game["away"]["abbr"]: "away"}
    inj = {"home": [], "away": []}
    for block in s.get("injuries") or []:
        side = abbr_side.get((block.get("team") or {}).get("abbreviation"))
        if not side:
            continue
        for i in block.get("injuries") or []:
            status = str(i.get("status") or "")
            if status.lower() not in ("out", "doubtful", "injured reserve", "ir"):
                continue
            dt = parse_iso(i.get("date"))
            if dt and (start - dt) > timedelta(days=21) and status.lower() not in ("out", "injured reserve", "ir"):
                continue
            ath = i.get("athlete") or {}
            pos = ((ath.get("position") or {}).get("abbreviation")) or ""
            det = ((i.get("details") or {}).get("type")) or ""
            inj[side].append({"player": ath.get("displayName"), "pos": pos, "status": status, "detail": det,
                              "stale": bool(dt and (start - dt) > timedelta(days=21))})
    out["injuries"] = inj
    # last five
    form = {}
    for block in s.get("lastFiveGames") or []:
        side = abbr_side.get((block.get("team") or {}).get("abbreviation"))
        if not side:
            continue
        evs = sorted(block.get("events") or [], key=lambda e: e.get("gameDate") or "", reverse=True)
        recent = [e for e in evs if (parse_iso(e.get("gameDate")) or start) > start - timedelta(days=120)]
        form[side] = "".join((e.get("gameResult") or "?")[0] for e in recent[:5])
    out["form"] = form
    # headlines
    heads = []
    for a in (s.get("news") or {}).get("articles", [])[:6]:
        pub = parse_iso(a.get("published"))
        if pub and start - pub < timedelta(days=10):
            heads.append(a.get("headline"))
    out["news"] = [h for h in heads if h][:3]
    # MLB probables
    if game["sport"] == "mlb":
        probs = {}
        for c in ((s.get("header") or {}).get("competitions") or [{}])[0].get("competitors", []):
            p = (c.get("probables") or [{}])[0].get("athlete", {}).get("displayName") if c.get("probables") else None
            if p:
                probs[c.get("homeAway")] = p
        out["probables"] = probs
    return out


def parse_box(s: dict) -> dict:
    """Team stats + key events from a finished game's summary, for history."""
    teams = {}
    for t in (s.get("boxscore") or {}).get("teams", []):
        side = t.get("homeAway") or ("home" if len(teams) else "away")
        stats = {}
        for st in t.get("statistics") or []:
            name = st.get("name") or st.get("label")
            val = st.get("displayValue") if st.get("displayValue") is not None else st.get("value")
            if name:
                stats[name] = val
        teams[side] = {"abbr": (t.get("team") or {}).get("abbreviation"), "stats": stats}
    events = []
    for k in s.get("keyEvents") or []:
        events.append({
            "type": (k.get("type") or {}).get("text"), "clock": (k.get("clock") or {}).get("displayValue"),
            "team": (k.get("team") or {}).get("abbreviation") if k.get("team") else None,
            "text": (k.get("text") or k.get("shortText") or "")[:200],
        })
    scoring = []
    for p in s.get("scoringPlays") or []:
        scoring.append({"period": (p.get("period") or {}).get("number"), "clock": (p.get("clock") or {}).get("displayValue"),
                        "team": (p.get("team") or {}).get("abbreviation"), "text": (p.get("text") or "")[:160]})
    return {"teams": teams, "keyEvents": events[:40], "scoringPlays": scoring[:40]}
