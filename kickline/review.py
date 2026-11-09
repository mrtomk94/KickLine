"""Claude review (runs a few times a day): checks news for the top games with web
search, rewrites the lessons from the graded record, and may tune a few rule
numbers within safe bounds. Needs the ANTHROPIC_API_KEY secret.
Run with:  python -m kickline.review"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import timedelta

from . import store
from .util import iso, now_utc, parse_iso, price_in_pick, pt_label

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-5"

BOUNDS = {
    "confTrim": (0, 8), "parlayConfFloor": (55, 75), "minConfForTwoStars": (52, 65),
    "espnGapForFactor": (3, 10), "lineMoveForFactor": (2, 8),
}

SYSTEM = """You are the reviewer for Kickline Slate, a personal sports research board that grades its own
picks and keeps a simulated (paper-credit) bankroll. Nothing is ever bet with real money and you never
visit or recommend betting sites. Your job:
1. For each listed upcoming game, use web search to check for important news the ESPN feed may miss
   (starting QB or pitcher changes, star players ruled out, lineup news). Only use articles from the
   current season and the current week; last season's previews with the same teams have fooled us before.
2. Adjust a game only when news justifies it. Be stingy: normally no more than ~10% of games at 4-5 stars,
   and a 4-5 star rating needs at least two independent factors (news alone is not enough).
3. Rewrite up to 8 short, evidence-based lessons from the graded record (state sample sizes; a pattern
   is a rule only with n>=5, otherwise "early sign (n=3)"). One lesson should track Match Vision once it
   has 5+ graded reads, and one should compare bankroll weeks.
4. Optionally tune these rule numbers (stay inside the bounds given): confTrim, parlayConfFloor,
   minConfForTwoStars, espnGapForFactor, lineMoveForFactor, and per-league / per-price-band star caps.
Reply with ONLY a JSON object:
{"lessons": ["..."], "rules": {...only keys you change...},
 "overrides": {"<gameId>": {"stars": 1-5, "confidence": number, "pick": "Pass" or the exact current pick,
                            "note": "one sentence citing the news", "news": ["headline", ...]}}}"""


def _compact_stats(stats: dict) -> dict:
    keep = {}
    for name, tab in (stats.get("tables") or {}).items():
        keep[name] = {k: f"{v['w']}-{v['l']}-{v['p']} hit {v['hit']} roi {v['roi']}" for k, v in tab.items()}
    keep["parlays"] = {k: f"{v['w']}-{v['l']} roi {v['roi']}" for k, v in (stats.get("parlays") or {}).items()}
    keep["weeks"] = stats.get("weeks")
    keep["vision"] = stats.get("vision")
    keep["kvProfit"] = stats.get("kvProfit")
    return keep


def build_prompt(now) -> tuple[str, dict]:
    games = store.load("games")
    meta = store.load("meta")
    rules = store.load_rules()
    up = []
    for gid, g in games.items():
        st = parse_iso(g.get("start"))
        if not st or st <= now or st > now + timedelta(hours=36):
            continue
        if g.get("pick") in (None, "Pass") and (g.get("confidence") or 0) < 55:
            continue
        up.append(g)
    up.sort(key=lambda g: (-(g.get("stars") or 0), -(g.get("confidence") or 0)))
    up = up[:15]
    lines = []
    for g in up:
        lines.append(json.dumps({
            "gameId": g["id"], "league": g["league"], "kickoffPT": pt_label(g["start"]),
            "matchup": f"{g['away'].get('name')} @ {g['home'].get('name')}", "pick": g.get("pick"),
            "stars": g.get("stars"), "confidence": g.get("confidence"), "odds": g.get("odds"),
            "espnWinProb": g.get("espnWinProb"), "injuries": {s: g[s].get("injuries") for s in ("home", "away")},
            "form": {s: g[s].get("form") for s in ("home", "away")}, "reason": g.get("reason"),
        }, ensure_ascii=False))
    rec = meta.get("record", {})
    prompt = (
        f"Now: {iso(now)} ({pt_label(now)} Pacific).\n\n"
        f"Current lessons:\n- " + "\n- ".join(rec.get("lessons") or ["(none)"]) + "\n\n"
        f"Graded record (w-l-p, hit %, flat ROI %; recent_* = last 21 days):\n{json.dumps(_compact_stats(rec.get('stats') or {}), ensure_ascii=False)}\n\n"
        f"Rule numbers now: {json.dumps({k: rules.get(k) for k in list(BOUNDS) + ['leagueMaxStars', 'bandMaxStars']})}\n"
        f"Bounds: {json.dumps(BOUNDS)}; star caps must be 1-5.\n\n"
        f"Upcoming games to check (next 36 hours):\n" + ("\n".join(lines) or "(none)")
    )
    return prompt, {g["id"]: g for g in up}


def parse_reply(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


def apply(reply: dict, games: dict, now) -> list[str]:
    changes = []
    rules = store.load_rules()
    for k, v in (reply.get("rules") or {}).items():
        if k in BOUNDS and isinstance(v, (int, float)):
            lo, hi = BOUNDS[k]
            nv = max(lo, min(hi, v))
            if nv != rules.get(k):
                changes.append(f"rule {k}: {rules.get(k)} → {nv}")
                rules[k] = nv
        elif k in ("leagueMaxStars", "bandMaxStars") and isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, int) and 1 <= vv <= 5:
                    rules[k][kk] = vv
                    changes.append(f"{k}[{kk}] = {vv}")
    with open(store.DATA / "rules.json", "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)
    ov = store.load("overrides")
    ov = {k: v for k, v in ov.items() if (parse_iso(v.get("until")) or now) > now}
    for gid, o in (reply.get("overrides") or {}).items():
        g = games.get(gid)
        if not g or not isinstance(o, dict):
            continue
        clean = {}
        if isinstance(o.get("stars"), int) and 1 <= o["stars"] <= 5:
            clean["stars"] = o["stars"]
        if isinstance(o.get("confidence"), (int, float)) and 1 <= o["confidence"] <= 99:
            clean["confidence"] = round(o["confidence"])
        if o.get("pick") in ("Pass", g.get("pick")):
            clean["pick"] = o["pick"]
            if o["pick"] == "Pass":
                clean["stars"], clean["market"] = 1, None
        if o.get("note"):
            clean["note"] = str(o["note"])[:300]
        if isinstance(o.get("news"), list):
            clean["news"] = [str(x)[:140] for x in o["news"][:3]]
        if clean:
            clean["priceAt"] = price_in_pick(g.get("pick", ""))
            clean["until"] = g["start"]
            clean["reviewedAt"] = iso(now)
            ov[gid] = clean
            changes.append(f"{gid}: {clean.get('stars', g.get('stars'))}★ {clean.get('note', '')}")
    store.save("overrides", ov)
    meta = store.load("meta")
    rec = meta.setdefault("record", {})
    if reply.get("lessons"):
        rec["lessons"] = [str(x)[:400] for x in reply["lessons"][:8]]
        rec["lessonsSource"] = "claude"
        rec["reviewedAt"] = iso(now)
    store.save("meta", meta)
    return changes


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping Claude review.")
        return 0
    import anthropic
    now = now_utc()
    prompt, games = build_prompt(now)
    client = anthropic.Anthropic()
    msgs = [{"role": "user", "content": prompt}]
    text = ""
    for _ in range(4):  # allow pause_turn continuations from server tools
        resp = client.messages.create(
            model=MODEL, max_tokens=6000, system=SYSTEM, messages=msgs,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if resp.stop_reason != "pause_turn":
            break
        msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": resp.content}]
    try:
        reply = parse_reply(text)
    except (ValueError, json.JSONDecodeError) as e:
        print("Could not read Claude's reply:", e, text[:500])
        return 1
    for c in apply(reply, games, now):
        print(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
