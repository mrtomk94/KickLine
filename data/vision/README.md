# Match Vision inbox

Drop one JSON file per read here (or let the desktop app call `tools/push_vision.py`).
The next scan (within 10 minutes) uses it. Kickline only reads these files; it never changes them.

```json
{
  "gameId": "soccer-401882807",
  "sport": "soccer", "league": "LaLiga", "start": "2026-11-08T17:30:00Z",
  "importedAt": "2026-11-08T09:00:00Z",
  "lean": {"side": "home", "pct": 64},
  "home": {"name": "Villarreal", "abbr": "VIL", "form": "WWDLW", "chemistry": 78,
           "pairs": [{"a": "Player A", "b": "Player B", "score": 81}], "strongLines": ["midfield"], "weakLines": []},
  "away": {"name": "Getafe", "abbr": "GET", "form": "LDLWL", "chemistry": 61},
  "players": [{"name": "Player A", "team": "VIL", "pos": "FW", "predPts": 7.1, "fantasy": 9.4}],
  "notes": "free text"
}
```

`lean.side` is `home`, `away` or `draw`. Until 5 Vision reads have been graded, a read moves confidence by at most ±1
and never changes the star tier; after that, an agreeing read adds up to +2 and a disagreeing one takes up to −3 and caps the pick at 3★.
