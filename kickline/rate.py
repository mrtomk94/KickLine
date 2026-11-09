"""Rule-based 1-5★ rating that mirrors Kickline's written rules and lessons."""
from __future__ import annotations

import re

from .util import implied, novig, price_band, to_num


def _label(game: dict, side: str) -> str:
    t = game[side]
    if game["sport"] == "soccer":
        return t.get("short") or t.get("name")
    return t.get("abbr")


def _spread_size(spread: str | None) -> float | None:
    m = re.search(r"-(\d+(\.\d+)?)", spread or "")
    return float(m.group(1)) if m else None


def _form_wins(f: str | None) -> int | None:
    return f.count("W") if f else None


def vision_side(v: dict | None, game: dict) -> str | None:
    if not v:
        return None
    lean = (v.get("lean") or {}).get("side")
    return lean if lean in ("home", "away", "draw") else None


def rate(game: dict, rules: dict, vision: dict | None = None, hist: dict | None = None,
         vision_graded: int = 0, override: dict | None = None) -> dict:
    odds = game.get("odds") or {}
    mh, ma, md = odds.get("mlHome"), odds.get("mlAway"), odds.get("mlDraw")
    soccer = game["sport"] == "soccer"
    base = {"stars": 1, "pick": "Pass", "market": None, "confidence": None, "risks": [], "factors": []}
    if not mh or not ma or (soccer and not md):
        base["reason"] = "No moneyline posted yet; Pass until a price appears."
        return _apply_override(base, override, game)
    probs = novig(mh, ma, md) if soccer else novig(mh, ma)
    p_home, p_away = probs[0], probs[1]
    side = "home" if p_home >= p_away else "away"
    price = mh if side == "home" else ma
    market_p = p_home if side == "home" else p_away
    other = "away" if side == "home" else "home"

    factors, risks, notes = [], [], []
    conf = market_p * 100

    # ESPN model
    ewp = game.get("espnWinProb") or {}
    espn_p = ewp.get(side)
    if espn_p is not None:
        gap = espn_p - market_p * 100
        conf = 0.6 * market_p * 100 + 0.4 * espn_p
        if gap >= rules["espnGapForFactor"]:
            factors.append(f"ESPN model {espn_p:.0f}% vs market {market_p*100:.0f}%")
        elif gap <= -rules["espnGapForFactor"]:
            risks.append(f"ESPN model only {espn_p:.0f}% vs market {market_p*100:.0f}%")

    # line movement toward the side
    open_price = odds.get("mlHomeOpen") if side == "home" else odds.get("mlAwayOpen")
    if open_price and implied(open_price) and implied(price):
        move = (implied(price) - implied(open_price)) * 100
        if move >= rules["lineMoveForFactor"]:
            factors.append(f"line moved toward {_label(game, side)} ({open_price} → {price})")
        elif move <= -rules["lineMoveForFactor"]:
            risks.append(f"line drifted away ({open_price} → {price})")
            conf -= 2

    # injuries (football QBs carry the most weight)
    inj = game.get("injuriesRaw") or {}
    def qb_out(s):
        return [i for i in inj.get(s, []) if i.get("pos") == "QB" and not i.get("stale") and i.get("status", "").lower() == "out"]
    if game["sport"] in ("nfl", "ncaaf"):
        if qb_out(side):
            conf -= 5
            risks.append(f"{_label(game, side)} QB {qb_out(side)[0]['player']} out")
        if qb_out(other):
            factors.append(f"{_label(game, other)} QB {qb_out(other)[0]['player']} out")
            conf += 2

    # recent form
    fs, fo = _form_wins(game[side].get("form")), _form_wins(game[other].get("form"))
    if fs is not None and fo is not None:
        if fs - fo >= 3:
            factors.append(f"form {game[side]['form']} vs {game[other]['form']}")
            conf += 1
        elif fo - fs >= 2:
            risks.append(f"opponent in better form ({game[other]['form']})")
            conf -= 1

    # match history (rolling stats from finished games)
    if hist:
        edge = hist.get(side, 0) - hist.get(other, 0)
        if edge >= hist.get("threshold", 99):
            factors.append(hist.get("label", "history edge"))
            conf += 1
        elif edge <= -hist.get("threshold", 99):
            risks.append("history stats favor the opponent")
            conf -= 1

    # Match Vision
    vs = vision_side(vision, game)
    vision_agrees = None
    if vs:
        full = vision_graded >= rules["visionGradedReadsForFullWeight"]
        vision_agrees = vs == side
        if vision_agrees:
            conf += 2 if full else 1
            notes.append(f"Match Vision agrees ({(vision.get('lean') or {}).get('pct', '?')}%)")
        else:
            conf -= 3 if full else 1
            risks.append(f"Match Vision leans {vs}")

    conf = round(conf - rules["confTrim"])

    # stars
    n = len(factors)
    stars = 1
    if conf >= rules["minConfForTwoStars"]:
        stars = 2
    espn_factor = any(f.startswith("ESPN model") for f in factors)
    if stars == 2 and conf >= 65 and n >= 1 and (espn_factor or espn_p is None or espn_p >= market_p * 100 - 2):
        stars = 3
    if stars == 3 and n >= 2 and espn_factor and conf >= 65:
        stars = 4
    if stars == 4 and n >= 3 and espn_p is not None and espn_p - market_p * 100 >= 8:
        stars = 5
    # Vision never creates 4-5★ on its own; a disagreeing read caps at 3★
    if vision_agrees is False and stars > 3:
        stars = 3
    caps = []
    band = price_band(price)
    if band in rules["bandMaxStars"]:
        caps.append((rules["bandMaxStars"][band], f"{band} prices have been weak"))
    if game["league"] in rules["leagueMaxStars"]:
        caps.append((rules["leagueMaxStars"][game["league"]], f"{game['league']} capped by lessons"))
    if to_num(price) is not None and to_num(price) <= rules.get("shortPriceCap", -10000):
        caps.append((rules.get("shortPriceMaxStars", 3), f"prices of {rules['shortPriceCap']} or shorter pay too little for 4-5★"))
    if game["sport"] == "ncaaf":
        sz = _spread_size(odds.get("spread"))
        if sz and sz >= rules["collegeHugeSpread"]:
            caps.append((2, "huge college spread"))
    for cap, why in caps:
        if stars > cap:
            stars = cap
            notes.append(f"Capped at {cap}★: {why}.")

    if stars <= 1:
        out = dict(base, confidence=conf, factors=factors, risks=risks[:3])
        out["reason"] = (f"{_label(game, side)} about {market_p*100:.0f}% no-vig at {price}; no edge worth a pick. " + " ".join(notes)).strip()
        return _apply_override(out, override, game)

    label = _label(game, side)
    pick = f"{label} ML ({price})"
    parts = [f"{label} are about {market_p*100:.0f}% no-vig at {price}"]
    if espn_p is not None:
        parts[0] += f"; ESPN's model has {espn_p:.0f}%"
    parts[0] += "."
    if factors:
        parts.append("For: " + "; ".join(factors) + ".")
    parts += notes
    out = {"stars": stars, "pick": pick, "market": "Moneyline", "confidence": conf, "risks": risks[:3],
           "factors": factors, "reason": " ".join(parts), "visionAgreed": vision_agrees, "side": side}
    return _apply_override(out, override, game)


def _apply_override(out: dict, ov: dict | None, game: dict) -> dict:
    """Claude review can adjust a game's rating; scanner keeps it while the price is unchanged."""
    if not ov:
        return out
    if ov.get("priceAt") and out.get("pick") not in ("Pass", None):
        # if the line moved a lot since review, trust the fresh code rating
        from .util import price_in_pick
        now_p = to_num(price_in_pick(out["pick"]))
        then_p = to_num(ov.get("priceAt"))
        if now_p and then_p and abs(implied(now_p) - implied(then_p)) > 0.04:
            out["reason"] += " (Claude review skipped: line moved since.)"
            return out
    for k in ("stars", "confidence", "pick", "market"):
        if ov.get(k) is not None:
            out[k] = ov[k]
    if ov.get("note"):
        out["reason"] = (out.get("reason", "") + " Claude review: " + ov["note"]).strip()
    if ov.get("news"):
        game["news"] = ov["news"][:3]
    out["reviewed"] = True
    return out
