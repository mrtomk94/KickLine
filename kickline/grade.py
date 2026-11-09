"""Grade pick text against a final score: ML, Draw, spread/handicap, totals, double chance."""
from __future__ import annotations

import re


def _side_of(text: str, home: dict, away: dict) -> str | None:
    t = text.lower()
    best = None
    for side, team in (("home", home), ("away", away)):
        names = [team.get("abbr"), team.get("name"), team.get("short")]
        names += [re.sub(r"^#\d+\s+", "", team.get("name") or "")]
        for n in names:
            if not n:
                continue
            n = n.lower()
            if re.search(r"(^|[^a-z])" + re.escape(n) + r"([^a-z]|$)", t):
                if best is None or len(n) > best[1]:
                    best = (side, len(n))
    return best[0] if best else None


def grade(pick: str, home: dict, away: dict, hs: float, as_: float, soccer: bool = False) -> str:
    """Return win | loss | push | void (void when the pick can't be read)."""
    p = (pick or "").strip()
    pl = p.lower()
    if not p or pl == "pass":
        return "void"
    # totals
    m = re.match(r"^(over|under)\s+(\d+(\.\d+)?)", pl)
    if m:
        line, tot = float(m.group(2)), hs + as_
        if tot == line:
            return "push"
        return "win" if (tot > line) == (m.group(1) == "over") else "loss"
    # draw
    if re.match(r"^draw\b", pl):
        return "win" if hs == as_ else "loss"
    side = _side_of(re.sub(r"\(.*?\)", "", p), home, away)
    if side is None:
        return "void"
    mine, theirs = (hs, as_) if side == "home" else (as_, hs)
    if "double chance" in pl or " or draw" in pl:
        return "win" if mine >= theirs else "loss"
    if re.search(r"\bml\b|moneyline", pl):
        return "win" if mine > theirs else "loss"
    m = re.search(r"([+-]\d+(\.\d+)?)(?!\))", re.sub(r"\(.*?\)", "", p))
    if m:
        adj = mine + float(m.group(1))
        if adj == theirs:
            return "push"
        return "win" if adj > theirs else "loss"
    return "win" if mine > theirs else "loss"


def final_string(home: dict, away: dict, hs, as_) -> str:
    return f"{away.get('abbr')} {int(float(as_))} – {home.get('abbr')} {int(float(hs))}"


def parlay_status(legs: list[dict]) -> str:
    outs = [l.get("outcome") for l in legs]
    if "loss" in outs:
        return "loss"
    if any(o is None for o in outs):
        return "open"
    if all(o in ("push", "void") for o in outs):
        return "void"
    return "win"
