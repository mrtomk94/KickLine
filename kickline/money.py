"""Parlay suggestions, the weekly v3 paper bankroll and the K×V paper account.
All credits are simulated. Nothing here talks to a betting site."""
from __future__ import annotations

from datetime import datetime, timedelta

from .util import (dec_to_american, decimal, iso, parse_iso, price_band, price_in_pick, pt_date, to_num,
                   week_bounds)


def leg_price(g: dict) -> str | None:
    p = price_in_pick(g.get("pick", ""))
    if p:
        return p
    if g.get("market") in ("Spread", "Total"):
        return "-110"
    return None


def candidates(games: dict, now: datetime, rules: dict, hours: int) -> list[dict]:
    out = []
    ex = rules.get("excludeFromParlays", {})
    for gid, g in games.items():
        st = parse_iso(g.get("start"))
        if not st or st <= now + timedelta(minutes=30) or st > now + timedelta(hours=hours):
            continue
        if g.get("pick") in (None, "Pass") or (g.get("stars") or 0) < 2:
            continue
        if (g.get("confidence") or 0) < rules["parlayConfFloor"]:
            continue
        if g.get("market") not in ("Moneyline", "Draw"):
            continue
        if g.get("league") in ex.get("leagues", []):
            continue
        pr = leg_price(g)
        if not pr or price_band(pr) in ex.get("bands", []):
            continue
        out.append(dict(gameId=gid, sport=g["sport"], league=g["league"],
                        matchup=f"{g['away']['abbr']} @ {g['home']['abbr']}", start=g["start"], pick=g["pick"],
                        market=g["market"], price=pr, confidence=g["confidence"], stars=g["stars"],
                        _vision=1 if g.get("visionAgreed") else 0))
    out.sort(key=lambda c: (-c["confidence"], -c["stars"], -c["_vision"], decimal(c["price"])))
    for c in out:
        c.pop("_vision", None)
    return out


def ticket(legs: list[dict], size, batch: str, now: datetime, note: str, extra: dict | None = None) -> dict:
    d, p = 1.0, 1.0
    for l in legs:
        d *= decimal(l["price"])
        p *= l["confidence"] / 100
    doc = dict(size=len(legs), batch=batch, createdAt=iso(now), status="open", legs=[dict(l) for l in legs],
               decimalOdds=round(d, 3), americanOdds=dec_to_american(d), estHitPct=round(p * 100, 1),
               impliedPct=round(100 / d, 1), note=note)
    if extra:
        doc.update(extra)
    return doc


def build_parlays(cands: list[dict], batch: str, now: datetime) -> dict[str, dict]:
    out = {}
    n = len(cands)
    if n < 3:
        return out
    for size in range(3, min(12, n) + 1):
        t = ticket(cands[:size], size, batch, now, "")
        hit = t["estHitPct"]
        note = "Safest of the set" if size == 3 else f"{size} legs"
        note += f", about a 1-in-{max(1, round(100 / hit))} shot." if hit else "."
        if size == min(12, n):
            note += f" {n} legs qualified."
        t["note"] = note
        out[f"{batch}-{size}"] = t
    if n >= 6:
        t = ticket(cands[3:6], 3, batch, now, "Second 3-leg from candidates 4-6.", {"ticket": "3b"})
        out[f"{batch}-3b"] = t
    return out


def regrade_decimal(p: dict) -> None:
    d = 1.0
    for l in p["legs"]:
        if l.get("outcome") == "win" or l.get("outcome") is None:
            d *= decimal(l["price"])
    p["decimalOdds"] = round(d, 3)
    p["americanOdds"] = dec_to_american(d) if d > 1 else "+0"


# ---------- bankroll v3 ----------
WEEK_DEFAULT = dict(system="v3", startCredit=500, cap=700, tolerance=1200, target=1000, protectAt=750, stretch=1500,
                    singlesBudget=200, parlayBudget=550, longshotBudget=35, staked=0, status="active", lastParlayDay="")


def week_doc(bankroll: dict, now: datetime) -> tuple[str, dict]:
    wk, start, end = week_bounds(now)
    if wk not in bankroll:
        bankroll[wk] = dict(WEEK_DEFAULT, weekStart=iso(start), weekEnd=iso(end), updatedAt=iso(now))
    return wk, bankroll[wk]


def week_numbers(bets: dict, wk: str) -> dict:
    mine = [b for b in bets.values() if b.get("week") == wk]
    staked = sum(b["stake"] for b in mine)
    settled = [b for b in mine if b["status"] != "open"]
    profit = sum(b.get("payout", 0) - b["stake"] for b in settled)
    payouts = sum(b.get("payout", 0) for b in settled)
    return dict(staked=staked, settledProfit=round(profit, 2), value=round(500 + profit, 2),
                cash=round(500 - staked + payouts, 2),
                singles=sum(b["stake"] for b in mine if b["kind"] == "single"),
                parlays=sum(b["stake"] for b in mine if b["kind"] == "parlay" and len(b.get("legs") or []) < 6),
                longshots=sum(b["stake"] for b in mine if b["kind"] == "parlay" and len(b.get("legs") or []) >= 6),
                open=len(mine) - len(settled))


def place_bets(games: dict, parlays_new: dict, bets: dict, bankroll: dict, rules: dict, now: datetime,
               batch: str, parlay_records: dict) -> tuple[list[str], list[str]]:
    """Returns (placed bet ids, alerts)."""
    placed, alerts = [], []
    wk, w = week_doc(bankroll, now)
    nums = week_numbers(bets, wk)
    limit = min(w["tolerance"], w["cap"] + max(0, nums["settledProfit"]))
    room = min(limit - nums["staked"], nums["cash"])
    old_status = w.get("status")
    if nums["value"] >= w["target"]:
        w["status"] = "target hit"
    elif room < 50:
        w["status"] = "stopped"
    elif nums["value"] >= w["protectAt"]:
        w["status"] = "protect"
    else:
        w["status"] = "active"
    if w["status"] != old_status and w["status"] in ("protect", "target hit", "stopped"):
        alerts.append(f"Kickline bankroll: week of {wk} is now '{w['status']}' (value {nums['value']:.0f} cr).")
    if w["status"] in ("target hit", "stopped"):
        w["updatedAt"] = iso(now)
        return placed, alerts
    half = w["status"] == "protect"

    def put(bid, doc):
        nonlocal room
        bets[bid] = doc
        room -= doc["stake"]
        nums["staked"] += doc["stake"]
        placed.append(bid)

    # singles
    ex = rules.get("excludeFromSingles", {}).get("leagues", [])
    singled = {b["ref"] for b in bets.values() if b["kind"] == "single"}
    run_budget = 120
    picks = []
    for gid, g in games.items():
        st = parse_iso(g.get("start"))
        if not st or not (now + timedelta(minutes=30) < st < now + timedelta(hours=36)):
            continue
        if (g.get("stars") or 0) < 3 or g.get("market") not in ("Moneyline", "Draw") or gid in singled:
            continue
        if g.get("league") in ex:
            continue
        pr = to_num(price_in_pick(g["pick"]))
        if pr is None or (-149 <= pr <= -100) or (100 <= pr <= 149):
            continue
        picks.append((g["stars"], g["confidence"], gid, g))
    picks.sort(key=lambda x: (-x[0], -x[1]))
    n = 0
    for stars, conf, gid, g in picks:
        want = {5: 90, 4: 70, 3: 50}[min(stars, 5)]
        stake = min(want, run_budget, w["singlesBudget"] - nums["singles"], room)
        if stake < 20:
            break
        n += 1
        pr = price_in_pick(g["pick"])
        d = decimal(pr)
        put(f"b-{batch}-s{n}", dict(week=wk, kind="single", sport=g["sport"], label=g["pick"],
                                    matchup=f"{g['away']['abbr']} @ {g['home']['abbr']}", start=g["start"], ref=gid,
                                    odds=pr, decimal=round(d, 3), stake=stake, toReturn=round(stake * d, 2),
                                    status="open", placedAt=iso(now), reason=f"{stars}★ · {conf}%"))
        run_budget -= stake
        nums["singles"] += stake

    # parlays: one batch per Pacific day
    today = pt_date(now)
    if w.get("lastParlayDay") != today and parlays_new:
        plan = [("3", 60, 30), ("4", 40, 20), ("3b", 30, 15)]
        did = False
        for size, full, halfst in plan:
            pid = f"{batch}-{size}"
            p = parlays_new.get(pid)
            if not p:
                continue
            stake = full if all(l["confidence"] >= 70 for l in p["legs"]) else halfst
            if half:
                stake = stake / 2
            stake = min(stake, w["parlayBudget"] - nums["parlays"], room)
            if stake < 5:
                continue
            put(f"b-{batch}-p{size}", _parlay_bet(wk, p, pid, stake, now))
            nums["parlays"] += stake
            did = True
        # long shot: largest 6-10 leg ticket
        big = [p for k, p in parlays_new.items() if 6 <= p["size"] <= 10 and p.get("ticket") != "3b"]
        if big:
            p = max(big, key=lambda x: x["size"])
            stake = 5 / (2 if half else 1)
            if nums["longshots"] + stake <= w["longshotBudget"] and stake <= room:
                pid = f"{batch}-{p['size']}"
                doc = _parlay_bet(wk, p, pid, stake, now)
                doc["longshot"] = True
                put(f"b-{batch}-p{p['size']}", doc)
                nums["longshots"] += stake
                did = True
        if did:
            w["lastParlayDay"] = today
    w["staked"] = nums["staked"]
    w["updatedAt"] = iso(now)
    return placed, alerts


def _parlay_bet(wk, p, pid, stake, now):
    return dict(week=wk, kind="parlay", size=p["size"], legs=p["legs"], label=f"{p['size']}-leg parlay {p['americanOdds']}",
                start=min(l["start"] for l in p["legs"]), ref=pid, odds=p["americanOdds"], decimal=p["decimalOdds"],
                stake=stake, toReturn=round(stake * p["decimalOdds"], 2), status="open", placedAt=iso(now),
                reason="Legs: " + ", ".join(l["pick"] for l in p["legs"]))


# ---------- K×V ----------
def kv_run(games: dict, vision: dict, kv: dict, kvparlays: dict, kvbets: dict, rules: dict, now: datetime,
           batch: str) -> list[str]:
    acct = kv.setdefault("account", {"startCredit": 250, "stake": 5, "status": "active", "lastTicketDay": ""})
    settled = [b for b in kvbets.values() if b["status"] != "open"]
    bal = acct["startCredit"] + sum(b.get("payout", 0) - b["stake"] for b in settled)
    cash = bal - sum(b["stake"] for b in kvbets.values() if b["status"] == "open")
    acct["balance"] = round(bal, 2)
    if cash < 5:
        acct["status"] = "stopped"
        return []
    legs = []
    for c in candidates(games, now, dict(rules, excludeFromParlays={"leagues": [], "bands": []}), 72):
        v = vision.get(c["gameId"])
        if not v:
            continue
        imp = parse_iso(v.get("importedAt"))
        st = parse_iso(c["start"])
        if imp and st and st - imp > timedelta(days=7):
            continue
        g = games[c["gameId"]]
        pick_side = "draw" if c["market"] == "Draw" else g.get("side")
        if (v.get("lean") or {}).get("side") != pick_side:
            continue
        legs.append(c)
    alerts = []
    if len(legs) < 2:
        return alerts
    legs = legs[:6]
    for k, p in list(kvparlays.items()):
        if p["status"] == "open" and all(parse_iso(l["start"]) > now for l in p["legs"]) and \
                not any(b["ref"] == k for b in kvbets.values()):
            del kvparlays[k]
    pid = f"{batch}-kv"
    t = ticket(legs, len(legs), batch, now, f"{len(legs)} legs where Kickline and Match Vision agree.", {"kind": "kv"})
    kvparlays[pid] = t
    today = pt_date(now)
    same = any(b["status"] == "open" and {l["gameId"] for l in b["legs"]} == {l["gameId"] for l in legs} for b in kvbets.values())
    if acct.get("lastTicketDay") != today and not same:
        kvbets[f"kb-{batch}"] = dict(kind="parlay", legs=t["legs"], label=f"{len(legs)}-leg K×V parlay {t['americanOdds']}",
                                     start=min(l["start"] for l in legs), ref=pid, odds=t["americanOdds"],
                                     decimal=t["decimalOdds"], stake=5, toReturn=round(5 * t["decimalOdds"], 2),
                                     status="open", placedAt=iso(now), reason="Legs: " + ", ".join(l["pick"] for l in legs))
        acct["lastTicketDay"] = today
        alerts.append(f"K×V ticket placed: {t['americanOdds']} — " + ", ".join(l["pick"] for l in legs))
    acct["updatedAt"] = iso(now)
    return alerts
