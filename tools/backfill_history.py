"""Fill data/history with finished games from the last N days so the rater has
form/stat history from day one.
Usage:  python tools/backfill_history.py --days 45 [--leagues eng.1,esp.1,nfl]"""
import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kickline import espn, history, store  # noqa: E402
from kickline.util import ET, now_utc  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=30)
ap.add_argument("--leagues", default="")
a = ap.parse_args()
want = {x.strip() for x in a.leagues.split(",") if x.strip()}
now = now_utc()
saved = 0
for key, sport, league, name, extra in espn.LEAGUES:
    if want and league not in want and key not in want:
        continue
    for i in range(1, a.days + 1):
        d = (now - timedelta(days=i)).astimezone(ET).strftime("%Y%m%d")
        for ev in espn.scoreboard(sport, league, d, extra):
            g = espn.parse_event(ev, key, name, league)
            if not g or not g["completed"] or store.history_path(g["id"]).exists():
                continue
            s = espn.summary(sport, league, g["espnId"])
            history.record_game(g, g["home"]["score"], g["away"]["score"], s)
            saved += 1
            time.sleep(0.25)
    print(f"{name}: done ({saved} saved so far)", flush=True)
print("saved", saved)
