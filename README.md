# Caissa — Chess Improvement Intelligence

Reads your Chess.com or Lichess games, finds the patterns costing you rating
points, and tells you exactly what to study.

## Architecture

| Piece    | Tech                                   | Hosted on |
|----------|----------------------------------------|-----------|
| Frontend | React 19 + Vite 6 (`frontend/caissa-ui`) | Vercel    |
| Backend  | FastAPI + Stockfish + CrewAI (`backend`) | Railway (Dockerfile) |
| Database | Postgres (`users`, `games`, `moves`, `reports`, `reference_players`) | Supabase |

Pipeline: fetch games → Stockfish / Lichess evals per move → blunder &
phase stats → tactical pattern extraction (python-chess) → collaborative
filter vs. reference players → 3-step AI report (`agents.CoachPipeline`)
that writes the diagnosis, coaching JSON, and searches for study resources.
The AI steps call the Gemini and Serper REST APIs directly via `requests`
(no agent framework).

## Environment variables

**Backend (Railway):** see `.env.example` — `SUPABASE_URL`, `SUPABASE_KEY`,
`GEMINI_API_KEY`, `SERPER_API_KEY`, `STOCKFISH_PATH`, `ANALYSIS_DEPTH`,
optional `ALLOWED_ORIGINS` (comma-separated, defaults to `*`), `MAX_GAMES`
(default 150).

**Frontend (Vercel):** `VITE_API_URL` — the public URL of the Railway
backend (e.g. `https://caissa-api.up.railway.app`). ⚠️ This replaced the old
`REACT_APP_API_URL` when the app moved from Create React App to Vite —
update the variable name in Vercel project settings.

## Local development

```bash
# backend
pip install -r requirements.txt
uvicorn main:app --reload --app-dir backend     # http://localhost:8000

# frontend
cd frontend/caissa-ui
npm install
npm run dev                                      # http://localhost:3000
```

`.env.development` already points the frontend at `http://localhost:8000`.

## Notes

- Python dependencies are pinned to a set verified end-to-end (a real report
  generation against Gemini + Serper). The report pipeline uses plain REST
  calls, so there's no agent-framework version coupling to worry about.
- Gemini model is configurable via the `GEMINI_MODEL` env var (default
  `gemini-2.5-flash`).
- `recharts` is pinned to v2 — v3 pulls in `eval`, which Vercel's CSP blocks.
- `render.yaml` is a leftover from a previous Render deployment; Railway
  builds from the `Dockerfile`.
