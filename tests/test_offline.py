"""Offline smoke test: runs a full scan on a copy of data/ with fake ESPN responses.
Usage:  python tests/test_offline.py"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
shutil.copytree(REPO / "data", tmp / "data")
os.environ["KICKLINE_ROOT"] = str(tmp)
sys.path.insert(0, str(REPO))

from kickline import espn, grade, run, store  # noqa: E402


def comp(eid, home, away, start, state="pre", hs=None, as_=None, odds=None):
    def team(t, side, score):
        return {"homeAway": side, "score": score, "team": {"id": t[0], "abbreviation": t[0], "displayName": t[1],
                "shortDisplayName": t[1].split()[-1], "location": t[1]}, "records": [{"summary": t[2]}]}
    return {"id": eid, "date": start, "status": {"type": {"state": state, "completed": state == "post",
            "name": "STATUS_FINAL" if state == "post" else "STATUS_SCHEDULED"}},
            "competitions": [{"venue": {"fullName": "Stadium", "address": {"city": "City"}},
                              "competitors": [team(home, "home", hs), team(away, "away", as_)], "odds": [odds] if odds else []}]}


def odds(h, a, ho, ao, details, total):
    return {"provider": {"name": "DraftKings"}, "details": details, "overUnder": total,
            "moneyline": {"home": {"open": {"odds": ho}, "close": {"odds": h}}, "away": {"open": {"odds": ao}, "close": {"odds": a}}}}


EVENTS = {
    ("football/nfl", "20261109"): [comp("401873051", ("MIN", "Minnesota Vikings", "6-1"), ("BUF", "Buffalo Bills", "6-1"),
                                        "2026-11-10T01:15Z", odds("+154", "-185", "+130", "-155", "BUF -3", 44.5))],
    ("football/nfl", "20261108"): [comp("401873050", ("CHI", "Chicago Bears", "7-2"), ("TB", "Tampa Bay Buccaneers", "3-6"),
                                        "2026-11-09T01:20Z", "post", "27", "24")],
    ("football/college-football", "20261110"): [
        comp("401866458", ("AKR", "Akron Zips", "1-8"), ("WMU", "Western Michigan Broncos", "6-3"), "2026-11-11T00:00Z",
             odds=odds("+440", "-600", "+400", "-500", "WMU -13.5", 47.5)),
        comp("401866459", ("BGSU", "Bowling Green Falcons", "2-7"), ("KENT", "Kent State Golden Flashes", "3-6"), "2026-11-11T00:00Z",
             odds=odds("-205", "+170", "-205", "+170", "BGSU -5.5", 44.5))],
    ("football/college-football", "20261111"): [
        comp("401866462", ("CMU", "Central Michigan Chippewas", "4-5"), ("SAC", "Sacramento State Hornets", "2-8"), "2026-11-12T00:30Z",
             odds=odds("-750", "+525", "-750", "+525", "CMU -15.5", 44.5)),
        comp("401866463", ("TOL", "Toledo Rockets", "7-2"), ("MASS", "UMass Minutemen", "5-4"), "2026-11-11T05:00Z",
             odds=odds("-575", "+425", "-575", "+425", "TOL -14", 53.5))],
    ("soccer/esp.1", "20261110"): [comp("999001", ("RMA", "Real Madrid", "9-1-1"), ("ALA", "Alaves", "2-4-5"), "2026-11-11T20:00Z",
                                        odds={**odds("-400", "+1000", "-300", "+900", "RMA -1.5", 3.5),
                                              "drawOdds": {"moneyLine": 550}})],
}
SUMMARIES = {
    "401873051": {"predictor": {"homeTeam": {"gameProjection": "39.6"}, "awayTeam": {"gameProjection": "60.1"}},
                  "injuries": [{"team": {"abbreviation": "MIN"}, "injuries": [{"status": "Out", "date": "2026-11-05T12:00Z",
                               "athlete": {"displayName": "Kyler Murray", "position": {"abbreviation": "QB"}}, "details": {"type": "Hamstring"}}]}]},
    "401866458": {"predictor": {"homeTeam": {"gameProjection": "10.1"}, "awayTeam": {"gameProjection": "90"}}},
    "401866462": {"predictor": {"homeTeam": {"gameProjection": "92.6"}, "awayTeam": {"gameProjection": "7.4"}}},
    "401866463": {"predictor": {"homeTeam": {"gameProjection": "83.7"}, "awayTeam": {"gameProjection": "16.3"}}},
    "999001": {"predictor": {"homeTeam": {"gameProjection": "84"}, "awayTeam": {"gameProjection": "6"}}},
    "401873050": {"boxscore": {"teams": [{"homeAway": "away", "team": {"abbreviation": "TB"}, "statistics": [{"name": "totalYards", "displayValue": "350"}]},
                                         {"homeAway": "home", "team": {"abbreviation": "CHI"}, "statistics": [{"name": "totalYards", "displayValue": "330"}]}]},
                  "scoringPlays": [{"period": {"number": 4}, "clock": {"displayValue": "0:00"}, "team": {"abbreviation": "CHI"}, "text": "Santos 41 Yd Field Goal"}]},
}


def fake_get(url, retries=2):
    if "/scoreboard?" in url:
        path = url.split("/sports/")[1].split("/scoreboard")[0]
        date = url.split("dates=")[1][:8]
        return {"events": EVENTS.get((path, date), [])}
    if "/summary?event=" in url:
        return SUMMARIES.get(url.split("event=")[1])
    return None


espn.get = fake_get

# grading unit checks
H, A = {"abbr": "CHI", "name": "Chicago Bears"}, {"abbr": "TB", "name": "Tampa Bay Buccaneers"}
assert grade.grade("CHI ML (-285)", H, A, 27, 24) == "win"
assert grade.grade("TB +3", H, A, 27, 24) == "push"
assert grade.grade("TB +2.5", H, A, 27, 24) == "loss"
assert grade.grade("Under 51.5", H, A, 27, 24) == "win"
assert grade.grade("Over 51", H, A, 27, 24) == "push"
assert grade.grade("Draw (+250)", H, A, 1, 1, True) == "win"
assert grade.grade("TB +0.5", H, A, 1, 1, True) == "win"

for when in ("2026-11-09T17:00:00Z", "2026-11-10T16:00:00Z"):
    os.environ["KICKLINE_NOW"] = when
    assert run.main() == 0
    games = store.load("games")
    print(f"\n--- scan at {when}: {len(games)} games")
    for g in sorted(games.values(), key=lambda g: g["start"]):
        if g.get("pick") not in (None, "Pass"):
            print(f"  {g['id']:18} {g['pick']:24} {g['stars']}★ {g['confidence']}%  {g['reason'][:110]}")
    pl = {k: v for k, v in store.load("parlays").items() if v["status"] == "open" and v["batch"] == when[:10].replace("-", "") + "-" + when[11:16].replace(":", "")}
    for k, v in sorted(pl.items()):
        print("  parlay", k, v["americanOdds"], v["estHitPct"], [l["pick"] for l in v["legs"]])
    bets = store.load("bets")
    new = [b for k, b in bets.items() if b["placedAt"] == when]
    print("  new bets:", [(b["label"], b["stake"]) for b in new])
    print("  week:", store.load("bankroll").get("2026-11-09", {}).get("staked"))

data = json.load(open(tmp / "docs" / "data.json"))
print("\nboard data:", len(data["games"]), "games;", len(data["results"]), "results; history files:", data["historyCount"])
assert (tmp / "data" / "history" / "nfl-401873050.json").exists()
print("lessons source:", store.load("meta")["record"].get("lessonsSource"))
print("OK")
