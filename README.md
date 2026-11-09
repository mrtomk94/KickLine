# Kickline Slate

A self-running sports research board. GitHub runs it every 10 minutes. Each run:

1. **Grades** finished games (moneyline, spread, total, draw, double chance), parlays, and paper bets.
2. **Saves match history**: box score and key events for every finished game go to `data/history/`.
3. **Pulls the slate** from ESPN (NFL, FBS college football, MLB, NBA and the main soccer leagues) for the next 72 hours.
4. **Researches** each game: ESPN win probability, injuries, last-5 form, headlines, and line movement.
5. **Rates** each game 1–5★ using Kickline's rules, the lessons, match history, and Match Vision reads.
6. **Builds parlays** of 3 to 12 legs and places **paper** bets under bankroll v3 and the K×V account.
7. **Publishes** `docs/data.json`, which the board page at `https://<you>.github.io/<repo>/` shows.

A **Claude review** runs twice a day. It checks news with web search, rewrites the lessons, and can adjust
individual games and tune a few rule numbers within safe bounds.

Everything is simulated paper credits. Nothing connects to a betting site.

## Setup (about 10 minutes)

1. **Create a public repo** on GitHub, for example `kickline-slate`, and upload everything in this folder.
   Keep the folder layout, including the hidden `.github` folder. You can drag the files in on github.com
   ("Add file → Upload files"), or use GitHub Desktop.
   *Why public:* a run every 10 minutes uses about 4,000+ Action minutes a month. Public repos get them
   free; private repos get 2,000 free minutes a month. If you want it private, change the scan to
   `*/30 * * * *`.
2. **Allow pushes.** Go to Settings → Actions → General → Workflow permissions, choose
   **Read and write permissions**, and click Save.
3. **Turn on the board.** Go to Settings → Pages → Build and deployment. Set Source to
   "Deploy from a branch", Branch to `main`, and Folder to `/docs`. Click Save.
4. **Start it.** Go to Actions → "Kickline scan" → **Run workflow**. After that it runs on its own every
   10 minutes.
5. **Fill the history.** Run Actions → "History backfill" with, for example, `30` days.
6. **Optional: Claude review.** Go to Settings → Secrets and variables → Actions → New repository secret,
   name it `ANTHROPIC_API_KEY`, and paste a key from console.anthropic.com. Each review uses API credit,
   roughly a few cents to tens of cents depending on the model and how many searches it runs. To pick the
   model, add a repository *variable* `CLAUDE_MODEL` (default `claude-sonnet-4-5`).
7. **Optional: phone alerts.** Install the free **ntfy** app and subscribe to a long, hard-to-guess
   topic name, such as `kickline-7f3k9q2`. Add that name as the secret `NTFY_TOPIC`. You'll get a push
   for new 4–5★ games, bankroll status changes, cashed 4+ leg parlays, and new K×V tickets.

GitHub's scheduler is best-effort. At busy times a "10 minute" run can come 5–20 minutes late, and that
is normal.

## Match Vision

The desktop app sends each read into `data/vision/`. Two ways to do that:

- **Automatic:** after each read, the app calls `tools/push_vision.py read.json`. Before that, set
  `KICKLINE_REPO=you/kickline-slate` and `GITHUB_TOKEN`, a fine-grained token for this repo only with
  **Contents: read and write**.
- **By hand:** upload the JSON file into `data/vision/` on github.com.

The file format is in `data/vision/README.md`. It is the same format the old board's Match Vision tab
used. Vision's effect stays small (±1 confidence, no star change) until 5 of its reads have been graded.
After that it counts as a full factor. K×V tickets are built only from legs where Vision and Kickline agree.

## How the rating works (`kickline/rate.py`)

- Kickline takes the market favorite, then blends no-vig market odds (60%) with ESPN's model (40%).
- Factors for the pick: ESPN model ahead of the market by 5+ points, a 4+ point line move toward the
  side, the opponent's QB out, a form gap of 3+ wins, a better last-5 margin in match history, and a
  Match Vision lean that agrees.
- Stars: 2★ for a lean of 58%+. 3★ needs 65%+ and one factor. 4★ needs two factors including the ESPN
  gap. 5★ needs three factors and an ESPN gap of 8+.
- Caps from the lessons: plus money 1★, −100 to −149 2★, prices of −400 or shorter 3★, and NBA, MLS,
  Europa League, Liga MX and MLB 2★. Huge college spreads (20+) are also capped at 2★.
- All of these numbers live in `data/rules.json`. You can edit them, and the Claude review can tune
  some of them.

## Files

| Path | What it is |
|---|---|
| `kickline/run.py` | One scan, every 10 minutes |
| `kickline/review.py` | Claude review, twice a day |
| `kickline/espn.py` | ESPN feeds |
| `kickline/rate.py`, `grade.py`, `money.py`, `record.py`, `history.py` | Rating, grading, parlays and bankroll, learning, match history |
| `data/*.json` | The board's database (your old board's history is already loaded) |
| `data/history/` | One file per finished game: score, team stats, key events |
| `docs/index.html` | The board page |
| `tests/test_offline.py` | Runs a full scan against fake ESPN data: `python tests/test_offline.py` |

Run it on your own computer with `pip install requests`, then `python -m kickline.run`.
