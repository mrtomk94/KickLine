"""Learning step: hit rate and flat-stake ROI by tier, market, league, price, confidence."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .util import decimal, iso, parse_iso, price_band, price_in_pick


def _price(r):
    """The price the pick was rated at; '-110' for spreads/totals without one; None if unknown."""
    import re
    pick = r.get("pick", "")
    p = price_in_pick(pick)
    if p:
        return p
    m = re.search(r"(?<![\d.])([+-]\d{3,4})\b", pick)
    if m:
        return m.group(1)
    if r.get("market") in ("Spread", "Total"):
        return "-110"
    o = r.get("oddsAtPick")
    if isinstance(o, str) and re.fullmatch(r"[+-]\d{3,4}", o.strip()):
        return o.strip()
    if isinstance(o, dict) and r.get("market") == "Draw" and pick.lower().startswith("draw"):
        return o.get("mlDraw")
    return None


def _bucket():
    return {"w": 0, "l": 0, "p": 0, "units": 0.0}


def _add(b, r):
    o = r["outcome"]
    if o == "win":
        b["w"] += 1
        b["units"] += (decimal(_price(r)) if _price(r) else 1.91) - 1
    elif o == "loss":
        b["l"] += 1
        b["units"] -= 1
    elif o == "push":
        b["p"] += 1


def _fmt(t: dict) -> dict:
    out = {}
    for k, b in t.items():
        n = b["w"] + b["l"]
        out[str(k)] = {"w": b["w"], "l": b["l"], "p": b["p"], "hit": round(100 * b["w"] / n, 1) if n else None,
                       "roi": round(100 * b["units"] / n, 1) if n else None}
    return out


def compute(results: dict, parlays: dict, bets: dict, kvbets: dict, now: datetime) -> dict:
    tabs = defaultdict(lambda: defaultdict(_bucket))
    recent_cut = iso(now - timedelta(days=21))
    vision = {"lean": _bucket(), "agree": _bucket(), "disagree": _bucket()}
    for r in results.values():
        if r.get("outcome") == "void" or r.get("pick") in (None, "Pass"):
            # vision lean still counts
            pass
        else:
            c = r.get("confidence") or 0
            keys = {
                "all": "all", "stars": r.get("stars"), "market": r.get("market"),
                "league": r.get("league"), "band": price_band(_price(r)) if _price(r) else "unknown",
                "conf": "70+" if c >= 70 else "60-69" if c >= 60 else "<60",
            }
            for name, k in keys.items():
                _add(tabs[name][k], r)
                if (r.get("start") or "") >= recent_cut:
                    _add(tabs["recent_" + name][k], r)
            if r.get("visionAgreed") is True:
                _add(vision["agree"], r)
            elif r.get("visionAgreed") is False:
                _add(vision["disagree"], r)
        vl = (r.get("visionLean") or {}).get("side")
        if vl and r.get("final"):
            try:
                a, h = r["final"].split("–")
                as_, hs = float(a.split()[-1]), float(h.split()[-1])
                actual = "home" if hs > as_ else "away" if as_ > hs else "draw"
                _add(vision["lean"], {"outcome": "win" if vl == actual else "loss", "pick": "(-110)"})
            except (ValueError, IndexError):
                pass
    par = defaultdict(_bucket)
    for p in parlays.values():
        if p["status"] in ("win", "loss"):
            key = "3b" if p.get("ticket") == "3b" else str(p["size"])
            par[key]["w" if p["status"] == "win" else "l"] += 1
            par[key]["units"] += (p["decimalOdds"] - 1) if p["status"] == "win" else -1
    weeks = defaultdict(lambda: {"staked": 0, "profit": 0.0, "open": 0})
    for b in bets.values():
        w = weeks[b.get("week", "?")]
        w["staked"] += b["stake"]
        if b["status"] == "open":
            w["open"] += 1
        else:
            w["profit"] = round(w["profit"] + b.get("payout", 0) - b["stake"], 2)
    kv_profit = sum(b.get("payout", 0) - b["stake"] for b in kvbets.values() if b["status"] != "open")
    graded = sum(1 for r in results.values())
    return {
        "graded": graded,
        "tables": {k: _fmt(v) for k, v in tabs.items()},
        "parlays": _fmt(par),
        "weeks": dict(sorted(weeks.items())),
        "vision": _fmt(vision),
        "kvProfit": round(kv_profit, 2),
    }


def auto_lessons(stats: dict) -> list[str]:
    """Plain lessons when no Claude review has written any."""
    t = stats["tables"]
    out = []
    a = t.get("all", {}).get("all")
    if a:
        out.append(f"Overall {a['w']}-{a['l']}-{a['p']} ({a['hit']}%, {a['roi']:+}% flat ROI).")
    for name, label in (("stars", "Star tier"), ("band", "Price band"), ("conf", "Confidence")):
        parts = [f"{k}: {v['w']}-{v['l']} ({v['roi']:+}%)" for k, v in sorted(t.get(name, {}).items()) if v["roi"] is not None and v["w"] + v["l"] >= 5]
        if parts:
            out.append(f"{label} — " + "; ".join(parts) + ".")
    weak = [k for k, v in t.get("league", {}).items() if v["w"] + v["l"] >= 5 and (v["hit"] or 0) < 45]
    if weak:
        out.append("Losing leagues (n≥5, under 45%): " + ", ".join(weak) + ".")
    pp = [f"{k}-leg {v['w']}-{v['l']}" for k, v in stats["parlays"].items()]
    if pp:
        out.append("Parlays: " + ", ".join(pp) + ".")
    return out[:8]
