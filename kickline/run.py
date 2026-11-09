"""One Kickline scan: grade → schedule → research → rate → parlays → paper bets → board data.
Run with:  python -m kickline.run"""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta

from . import espn, grade, history, money, record, store
from .rate import rate
from .util import ET, PT, et_dates, iso, now_utc, parse_iso, pt_date, pt_label, price_in_pick

SOCCER_SLUG = {v: k for k, v in espn.SOCCER.items()}


def log(*a):
    print(*a, flush=True)


def ensure_paths(g: dict) -> None:
    if g.get("espnSport"):
        return
    if g["sport"] == "soccer":
        g["espnSport"], g["espnLeague"] = "soccer", SOCCER_SLUG.get(g.get("league"), "")
    else:
        g["espnSport"], g["espnLeague"] = espn.SPORT_OF[g["sport"]]
    g.setdefault("espnId", g["id"].split("-", 1)[1] if "id" in g else None)


# ---------------------------------------------------------------- grading
def find_final(g: dict, cache: dict) -> tuple[str, float | None, float | None, dict | None]:
    """Return (state, homeScore, awayScore, summary)."""
    ensure_paths(g)
    if not g.get("espnLeague"):
        return "unknown", None, None, None
    st = parse_iso(g["start"])
    date = st.astimezone(ET).strftime("%Y%m%d")
    key = (g["espnSport"], g["espnLeague"], date)
    if key not in cache:
        extra = "groups=80&limit=400" if g["sport"] == "ncaaf" else ""
        cache[key] = {e["id"]: e for e in espn.scoreboard(g["espnSport"], g["espnLeague"], date, extra)}
    ev = cache[key].get(g["espnId"])
    summ = espn.summary(g["espnSport"], g["espnLeague"], g["espnId"])
    state, hs, as_ = "unknown", None, None
    if ev:
        p = espn.parse_event(ev, g["sport"], g["league"], g.get("slug") or g["espnLeague"])
        if p:
            state = "post" if p["completed"] else p["state"]
            if p["statusName"] in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
                state = "void"
            hs, as_ = p["home"]["score"], p["away"]["score"]
    if state != "post" and summ:
        comp = ((summ.get("header") or {}).get("competitions") or [{}])[0]
        stt = (comp.get("status") or {}).get("type") or {}
        if stt.get("completed"):
            state = "post"
            for c in comp.get("competitors", []):
                if c.get("homeAway") == "home":
                    hs = c.get("score")
                else:
                    as_ = c.get("score")
        elif stt.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            state = "void"
    try:
        hs, as_ = float(hs), float(as_)
    except (TypeError, ValueError):
        if state == "post":
            state = "unknown"
        hs = as_ = None
    return state, hs, as_, summ


def grade_games(db, vision, now, alerts):
    games, results = db["games"], db["results"]
    cache, n = {}, {"win": 0, "loss": 0, "push": 0, "void": 0}
    for gid, g in list(games.items()):
        st = parse_iso(g.get("start"))
        if not st or now - st < timedelta(hours=3):
            continue
        has_pick = g.get("pick") not in (None, "Pass")
        need_result = gid not in results and (has_pick or gid in vision)
        need_hist = not store.history_path(gid).exists()
        if not (need_result or need_hist):
            continue
        state, hs, as_, summ = find_final(g, cache)
        if state == "void" and need_result:
            results[gid] = _result(g, None, None, "void", "Postponed or cancelled.", now, vision)
            n["void"] += 1
            continue
        if state != "post":
            continue
        if need_hist:
            history.record_game(g, hs, as_, summ)
        if need_result:
            if has_pick:
                out = grade.grade(g["pick"], g["home"], g["away"], hs, as_, g["sport"] == "soccer")
            else:
                out = "void"
            winner = g["home"]["abbr"] if hs > as_ else g["away"]["abbr"] if as_ > hs else "draw"
            note = f"Final {grade.final_string(g['home'], g['away'], hs, as_)}; " + (
                "the pick won." if out == "win" else "the pick lost." if out == "loss" else "graded " + out + ".")
            if winner == "draw":
                note += " Match ended level."
            results[gid] = _result(g, hs, as_, out, note, now, vision)
            n[out] += 1
    log("graded", n)
    return n


def _result(g, hs, as_, outcome, note, now, vision):
    r = dict(sport=g["sport"], league=g["league"], start=g["start"], matchup=f"{g['away']['abbr']} @ {g['home']['abbr']}",
             pick=g.get("pick") or "Pass", market=g.get("market"), stars=g.get("stars"), confidence=g.get("confidence"),
             oddsAtPick=price_in_pick(g.get("pick", "")) or (g.get("odds") or {}).get("mlHome"),
             reason=g.get("reason"), outcome=outcome, note=note, gradedAt=iso(now))
    if hs is not None:
        r["final"] = grade.final_string(g["home"], g["away"], hs, as_)
        r["homeScore"], r["awayScore"] = hs, as_
    if g.get("espnWinProb"):
        r["espnWinProb"] = g["espnWinProb"]
    v = vision.get(g["id"])
    if v and v.get("lean"):
        r["visionLean"] = {"side": v["lean"].get("side"), "pct": v["lean"].get("pct")}
        r["visionAgreed"] = g.get("visionAgreed") if g.get("market") == "Moneyline" else None
    return {k: v for k, v in r.items() if v is not None}


def grade_parlays_and_bets(db, now, alerts):
    results = db["results"]
    games = db["games"]

    def leg_outcome(l):
        r = results.get(l["gameId"])
        if not r:
            return None
        if r["outcome"] == "void" and r.get("pick") not in ("Pass",) and "homeScore" not in r:
            return "void"
        if "homeScore" in r:
            g = games.get(l["gameId"]) or {"home": {"abbr": r["matchup"].split(" @ ")[1]}, "away": {"abbr": r["matchup"].split(" @ ")[0]}}
            return grade.grade(l["pick"], g["home"], g["away"], r["homeScore"], r["awayScore"], l.get("sport") == "soccer")
        if r.get("pick") == l["pick"]:
            return r["outcome"]
        return None

    for coll in ("parlays", "kvparlays"):
        for pid, p in db[coll].items():
            if p["status"] != "open":
                continue
            for l in p["legs"]:
                if l.get("outcome") is None:
                    o = leg_outcome(l)
                    if o:
                        l["outcome"] = o
            stt = grade.parlay_status(p["legs"])
            if any(l.get("outcome") in ("push", "void") for l in p["legs"]):
                money.regrade_decimal(p)
            if stt != "open":
                p["status"] = stt
                p["gradedAt"] = iso(now)
    for coll, pcoll in (("bets", "parlays"), ("kvbets", "kvparlays")):
        for bid, b in db[coll].items():
            if b["status"] != "open":
                continue
            if b["kind"] == "single":
                r = results.get(b["ref"])
                if not r:
                    continue
                if "homeScore" in r:
                    g = games.get(b["ref"]) or {"home": {"abbr": r["matchup"].split(" @ ")[1]}, "away": {"abbr": r["matchup"].split(" @ ")[0]}}
                    o = grade.grade(b["label"], g["home"], g["away"], r["homeScore"], r["awayScore"], b.get("sport") == "soccer")
                else:
                    o = r["outcome"] if r.get("pick") == b["label"] else ("void" if r["outcome"] == "void" else None)
                if not o:
                    continue
                dec = b["decimal"]
            else:
                p = db[pcoll].get(b["ref"])
                if not p or p["status"] == "open":
                    continue
                o, dec = p["status"], p["decimalOdds"]
                if o == "win" and len(p["legs"]) >= 4:
                    alerts.append(f"Kickline: {b['label']} cashed — {b['stake']} cr returns {b['stake'] * dec:.2f}.")
            b["status"] = o
            b["payout"] = round(b["stake"] * dec, 2) if o == "win" else 0 if o == "loss" else b["stake"]
            b["settledAt"] = iso(now)


# ---------------------------------------------------------------- schedule + research
def refresh_schedule(db, rules, now, state):
    games = db["games"]
    horizon = now + timedelta(hours=rules["parlayWindowHours"])
    dates = et_dates(now, horizon)
    seen = 0
    for key, sport, league, name, extra in espn.LEAGUES:
        for d in dates:
            for ev in espn.scoreboard(sport, league, d, extra):
                g = espn.parse_event(ev, key, name, league)
                if not g:
                    continue
                st = parse_iso(g["start"])
                if not st or st < now - timedelta(hours=6) or st > horizon:
                    continue
                gid = g["id"]
                old = games.get(gid, {})
                if g["state"] != "pre" and not old:
                    continue
                merged = dict(old)
                for k in ("espnId", "sport", "league", "slug", "espnSport", "espnLeague", "start", "state", "venue", "link"):
                    if g.get(k):
                        merged[k] = g[k]
                for side in ("home", "away"):
                    t = dict(old.get(side, {}))
                    for k in ("name", "abbr", "record", "teamId", "short"):
                        if g[side].get(k):
                            t[k] = g[side][k]
                    merged[side] = t
                odds = g["odds"]
                if not odds.get("mlHome") and g["state"] == "pre":
                    odds = espn.core_odds(sport, league, g["espnId"], g["home"]["abbr"], g["away"]["abbr"]) or odds
                if odds.get("mlHome"):
                    keep = old.get("odds") or {}
                    # first sighting becomes the open line when ESPN has none
                    odds.setdefault("mlHomeOpen", keep.get("mlHomeOpen") or keep.get("mlHome") or odds["mlHome"])
                    odds.setdefault("mlAwayOpen", keep.get("mlAwayOpen") or keep.get("mlAway") or odds["mlAway"])
                    merged["odds"] = odds
                else:
                    merged.setdefault("odds", old.get("odds") or {"provider": "DraftKings"})
                merged["id"] = gid
                games[gid] = merged
                seen += 1
    log("schedule events seen", seen)


def research(db, rules, now, state, vision):
    games = db["games"]
    sumat = state.setdefault("summaryAt", {})
    for gid, g in games.items():
        st = parse_iso(g.get("start"))
        if not st or st < now or st > now + timedelta(hours=rules["parlayWindowHours"]):
            continue
        if not (g.get("odds") or {}).get("mlHome") and gid not in vision:
            continue
        last = parse_iso(sumat.get(gid))
        if last and now - last < timedelta(minutes=rules["summaryRefreshMinutes"]):
            continue
        ensure_paths(g)
        s = espn.summary(g["espnSport"], g["espnLeague"], g["espnId"])
        sumat[gid] = iso(now)
        if not s:
            continue
        info = espn.parse_summary(s, g, now)
        if info.get("espnWinProb"):
            g["espnWinProb"] = info["espnWinProb"]
        inj = info.get("injuries") or {}
        if inj.get("home") or inj.get("away"):
            g["injuriesRaw"] = inj
            for side in ("home", "away"):
                g[side]["injuries"] = [f"{i['player']} ({i['pos']}) – {i['status']}{', ' + i['detail'] if i['detail'] else ''}"
                                       for i in inj.get(side, []) if not i.get("stale")][:6]
        for side in ("home", "away"):
            f = (info.get("form") or {}).get(side)
            if f:
                g[side]["form"] = f
        if info.get("news"):
            g["news"] = info["news"]
        if info.get("probables"):
            g["probables"] = info["probables"]


def rate_all(db, rules, now, vision, hist_idx, vision_graded):
    games, overrides = db["games"], db["overrides"]
    for gid, g in games.items():
        st = parse_iso(g.get("start"))
        if not st or st <= now:
            continue
        r = rate(g, rules, vision.get(gid), history.features(g, hist_idx), vision_graded, overrides.get(gid))
        for k in ("stars", "pick", "market", "confidence", "reason", "risks", "visionAgreed", "side", "reviewed"):
            if r.get(k) is not None or k in g:
                g[k] = r.get(k)
        if r.get("pick") not in (None, "Pass") and r.get("pick") != g.get("_lastPick"):
            g["_lastPick"] = r["pick"]
        if g.get("pick") not in (None, "Pass"):
            side = grade._side_of(g["pick"], g["home"], g["away"])
            if side:
                g["side"] = side
        g["updatedAt"] = iso(now)


def prune_games(db, vision, now):
    games, results = db["games"], db["results"]
    open_refs = {b["ref"] for b in db["bets"].values() if b["status"] == "open" and b["kind"] == "single"}
    open_legs = {l["gameId"] for coll in ("bets", "kvbets") for b in db[coll].values() if b["status"] == "open" for l in b.get("legs", [])}
    for gid, g in list(games.items()):
        st = parse_iso(g.get("start"))
        if not st or now - st < timedelta(hours=24):
            continue
        if gid in open_refs or gid in open_legs:
            if now - st < timedelta(hours=72):
                continue
        has_pick = g.get("pick") not in (None, "Pass")
        done = gid in results or (not has_pick and gid not in vision)
        if done and store.history_path(gid).exists() or now - st > timedelta(hours=72):
            del games[gid]


def do_parlays(db, rules, now, batch):
    games, parlays = db["games"], db["parlays"]
    cands = money.candidates(games, now, rules, rules["windowHours"])
    if len(cands) < 12:
        cands = money.candidates(games, now, rules, rules["parlayWindowHours"])
    referenced = {b["ref"] for b in db["bets"].values()}
    for pid, p in list(parlays.items()):
        if p["status"] == "open" and pid not in referenced and all((parse_iso(l["start"]) or now) > now for l in p["legs"]):
            del parlays[pid]
    new = money.build_parlays(cands, batch, now)
    parlays.update(new)
    return new, len(cands)


# ---------------------------------------------------------------- notify + board
def notify(lines: list[str]) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not lines:
        return
    for l in lines:
        log("ALERT:", l)
    if not topic:
        return
    import requests
    try:
        requests.post(f"https://ntfy.sh/{topic}", data="\n".join(lines)[:3900].encode(),
                      headers={"Title": "Kickline Slate", "Tags": "football"}, timeout=15)
    except requests.RequestException as e:
        log("notify failed", e)


def board_data(db, now, ncands):
    games = db["games"]
    upcoming = sorted([g for g in games.values() if (parse_iso(g.get("start")) or now) > now], key=lambda g: g["start"])
    slim = []
    for g in upcoming:
        d = {k: g.get(k) for k in ("id", "sport", "league", "start", "venue", "home", "away", "odds", "espnWinProb", "stars",
                                    "pick", "market", "confidence", "reason", "news", "risks", "link", "reviewed", "visionAgreed")}
        d["kickoffPT"] = pt_label(g["start"])
        slim.append(d)
    wk = max((k for k in db["bankroll"] if k[:2] == "20"), default=None)
    recent_results = sorted(db["results"].items(), key=lambda kv: kv[1].get("start", ""), reverse=True)[:120]
    open_parlays = {k: v for k, v in db["parlays"].items() if v["status"] == "open"}
    recent_parlays = dict(sorted(((k, v) for k, v in db["parlays"].items() if v["status"] != "open"), reverse=True)[:40])
    return {
        "updatedAt": iso(now), "updatedPT": pt_label(now), "games": slim,
        "results": [dict(v, id=k) for k, v in recent_results],
        "parlays": open_parlays, "settledParlays": recent_parlays,
        "bets": sorted([dict(v, id=k) for k, v in db["bets"].items() if v.get("week") == wk], key=lambda b: b["placedAt"], reverse=True),
        "week": dict(db["bankroll"].get(wk, {}), id=wk) if wk else None,
        "bankrollSystem": db["bankroll"].get("system"),
        "kv": db["kv"].get("account"), "kvbets": list(db["kvbets"].values())[-20:],
        "record": db["meta"].get("record"), "latest": db["meta"].get("latest"),
        "historyCount": len(list((store.DATA / "history").glob("*.json"))), "candidates": ncands,
    }


def main() -> int:
    now = now_utc()
    if os.environ.get("KICKLINE_NOW"):
        now = parse_iso(os.environ["KICKLINE_NOW"])
    batch = now.strftime("%Y%m%d-%H%M")
    db = {c: store.load(c) for c in store.COLLECTIONS}
    rules = store.load_rules()
    vision = store.load_vision()
    state = db["state"]
    alerts: list[str] = []

    # vision docs without a gameId: match by team names and date
    for key, v in list(vision.items()):
        if key in db["games"]:
            continue
        for gid, g in db["games"].items():
            names = {(g["home"].get("abbr") or "").lower(), (g["home"].get("name") or "").lower()}
            if (v.get("home") or {}).get("abbr", "").lower() in names or (v.get("home") or {}).get("name", "").lower() in names:
                if (v.get("start") or "")[:10] == (g.get("start") or "")[:10]:
                    vision[gid] = v
                    break

    grade_games(db, vision, now, alerts)
    grade_parlays_and_bets(db, now, alerts)
    refresh_schedule(db, rules, now, state)
    research(db, rules, now, state, vision)
    hist_idx = history.build_index(store.load_all_history())
    vision_graded = sum(1 for r in db["results"].values() if r.get("visionLean"))
    rate_all(db, rules, now, vision, hist_idx, vision_graded)
    prune_games(db, vision, now)
    new_parlays, ncands = do_parlays(db, rules, now, batch)
    hour_pt = now.astimezone(PT).hour
    if hour_pt >= rules.get("parlayBetHourPT", 7):
        _, a = money.place_bets(db["games"], new_parlays, db["bets"], db["bankroll"], rules, now, batch, db["parlays"])
    else:
        _, a = money.place_bets(db["games"], {}, db["bets"], db["bankroll"], rules, now, batch, db["parlays"])
    alerts += a
    alerts += money.kv_run(db["games"], vision, db["kv"], db["kvparlays"], db["kvbets"], rules, now, batch)

    # learning
    stats = record.compute(db["results"], db["parlays"], db["bets"], db["kvbets"], now)
    rec = db["meta"].get("record", {})
    rec.update(updatedAt=iso(now), graded=stats["graded"], stats=stats)
    rev = parse_iso(rec.get("reviewedAt"))
    if not rec.get("lessons") or rev is None or now - rev > timedelta(days=4):
        rec["lessons"] = record.auto_lessons(stats)
        rec["lessonsSource"] = "auto"
    db["meta"]["record"] = rec

    # alerts for new 4-5★ games
    notified = set(state.get("notified", []))
    top = [g for g in db["games"].values() if (g.get("stars") or 0) >= 4 and (parse_iso(g["start"]) or now) > now]
    fresh = [g for g in top if f"{g['id']}:{g['pick']}" not in notified]
    if fresh:
        alerts.insert(0, f"Kickline: {len(fresh)} top pick{'s' if len(fresh) > 1 else ''} — " + ", ".join(
            f"{g['pick']} ({g['stars']}★, {pt_label(g['start'])})" for g in fresh[:4]))
        notified |= {f"{g['id']}:{g['pick']}" for g in fresh}
    state["notified"] = sorted(notified)[-500:]
    upcoming = [g for g in db["games"].values() if (parse_iso(g.get("start")) or now) > now]
    db["meta"]["latest"] = {"ranAt": iso(now), "gamesCount": len(upcoming), "topCount": len(top),
                            "note": f"{len(upcoming)} upcoming games, {len(top)} at 4–5★, {ncands} parlay legs qualify."}
    # trim state
    state["summaryAt"] = {k: v for k, v in state.get("summaryAt", {}).items() if k in db["games"]}
    for c in store.COLLECTIONS:
        store.save(c, db[c])
    store.DOCS.mkdir(exist_ok=True)
    with open(store.DOCS / "data.json", "w", encoding="utf-8") as f:
        json.dump(board_data(db, now, ncands), f, ensure_ascii=False, separators=(",", ":"))
    notify(alerts)
    log(db["meta"]["latest"]["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
