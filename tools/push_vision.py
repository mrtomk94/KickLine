"""Send a Match Vision read to the repo so the next Kickline scan uses it.
Call this from the Match Vision desktop app after it finishes a read.

Usage:  python push_vision.py read.json
Env:    GITHUB_TOKEN  (fine-grained token, this repo only, "Contents: read and write")
        KICKLINE_REPO (e.g. yourname/kickline-slate)

The JSON should follow the format in data/vision/README.md. Its "gameId" (e.g.
"soccer-401882807") ties it to a game; without one Kickline matches on home team + date."""
import base64
import json
import os
import sys

import requests

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    doc = json.load(f)
name = (doc.get("gameId") or doc.get("id") or os.path.splitext(os.path.basename(path))[0]) + ".json"
repo, token = os.environ["KICKLINE_REPO"], os.environ["GITHUB_TOKEN"]
url = f"https://api.github.com/repos/{repo}/contents/data/vision/{name}"
h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
sha = (requests.get(url, headers=h, timeout=20).json() or {}).get("sha")
body = {"message": f"vision: {name}", "content": base64.b64encode(json.dumps(doc, ensure_ascii=False, indent=1).encode()).decode()}
if sha:
    body["sha"] = sha
r = requests.put(url, headers=h, json=body, timeout=20)
print(r.status_code, r.json().get("content", {}).get("path") if r.ok else r.text[:300])
