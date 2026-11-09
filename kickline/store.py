"""JSON-file database in data/. Each collection is one file {doc_id: doc}."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("KICKLINE_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
DOCS = ROOT / "docs"

COLLECTIONS = ["games", "results", "parlays", "bets", "bankroll", "kv", "kvparlays", "kvbets", "meta", "state", "overrides"]


def _path(name: str) -> Path:
    return DATA / f"{name}.json"


def load(name: str) -> dict:
    p = _path(name)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(name: str, data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = _path(name).with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    tmp.replace(_path(name))


def load_rules() -> dict:
    with open(DATA / "rules.json", encoding="utf-8") as f:
        return json.load(f)


def load_vision() -> dict:
    """Vision reads dropped into data/vision/*.json. Keyed by gameId (or file stem)."""
    out = {}
    folder = DATA / "vision"
    if not folder.exists():
        return out
    for p in sorted(folder.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        docs = doc if isinstance(doc, list) else [doc]
        for d in docs:
            if isinstance(d, dict):
                key = d.get("gameId") or d.get("id") or p.stem
                d.setdefault("_file", p.name)
                out[key] = d
    return out


def history_path(game_id: str) -> Path:
    return DATA / "history" / f"{game_id}.json"


def save_history(game_id: str, doc: dict) -> None:
    p = history_path(game_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def load_all_history() -> list[dict]:
    folder = DATA / "history"
    out = []
    for p in folder.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return out
