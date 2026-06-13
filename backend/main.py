import os
import sys
import json
import math
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

app = FastAPI(title="Caissa API")

# Comma-separated list, e.g. "https://caissa.vercel.app,http://localhost:3000".
# Defaults to * so existing deployments keep working until the var is set.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_supabase_url = os.getenv("SUPABASE_URL")
_supabase_key = os.getenv("SUPABASE_KEY")

if not _supabase_url or not _supabase_key:
    raise RuntimeError(
        "\n\n  Missing environment variables!\n"
        "  Set SUPABASE_URL and SUPABASE_KEY before starting.\n"
        "  Railway: project → Variables tab → add them there.\n"
    )

supabase = create_client(_supabase_url, _supabase_key)


# ── HELPERS ───────────────────────────────────────────────
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_status(username: str, status: str, **extra):
    supabase.table("users").update({"status": status, **extra}).eq(
        "username", username
    ).execute()


def fetch_all(build_query, page_size: int = 1000) -> list:
    """
    Collect every row from a PostgREST query, paging past the 1000-row
    server cap. `build_query` is a zero-arg callable returning a fresh
    (unexecuted) query each call.
    """
    rows, start = [], 0
    while True:
        res = build_query().range(start, start + page_size - 1).execute()
        data = res.data or []
        rows.extend(data)
        if len(data) < page_size:
            return rows
        start += page_size


def extract_coaching_json(text: str):
    """
    Find the JSON object containing the "coaching" key by balancing braces
    (handles nested objects, which a regex cannot).
    """
    if not text:
        return None
    idx = text.find('"coaching"')
    while idx != -1:
        start = text.rfind("{", 0, idx)
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                c = text[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except Exception:
                            break
        idx = text.find('"coaching"', idx + 1)
    return None


def run_agents_and_store(username: str) -> bool:
    """
    Build the weakness profile, run the CrewAI agents, and replace the
    user's report. Returns False when there is no data to work with.
    """
    from agents import (
        get_weakness_profile, collaborative_filter,
        build_crew, extract_blunder_patterns,
    )

    profile = get_weakness_profile(username, supabase)
    if not profile:
        return False

    collab   = collaborative_filter(profile, supabase)
    patterns = extract_blunder_patterns(username, supabase)

    print(f"[{username}] Found {len(patterns)} tactical patterns")

    crew   = build_crew(profile, collab, patterns)
    result = crew.kickoff()

    coaching_json = extract_coaching_json(str(result))

    supabase.table("reports").delete().eq("username", username).execute()
    supabase.table("reports").insert({
        "username":        username,
        "weakness_phase":  profile["worst_phase"],
        "blunder_rate":    profile["phase_stats"][profile["worst_phase"]]["blunder_rate"],
        "recommendations": json.dumps(profile, default=str),
        "resources":       str(result),
        "patterns":        json.dumps(patterns, default=str),
        "coaching":        coaching_json,
    }).execute()
    return True


# ── BACKGROUND ANALYSIS ───────────────────────────────────
def run_analysis(username: str, platform: str = "chesscom"):
    try:
        from pipeline import (
            fetch_games, analyze_games,
            fetch_lichess_games, analyze_lichess_games,
        )

        set_status(username, "fetching")

        # compute since timestamp for incremental fetch
        since_ts = None
        since_ms = None
        try:
            user_row = supabase.table("users").select("last_sync").eq("username", username).execute()
            last_sync_str = user_row.data[0].get("last_sync") if user_row.data else None
            if last_sync_str:
                last_dt  = datetime.fromisoformat(last_sync_str.replace("Z", "+00:00"))
                since_ts = int(last_dt.timestamp())
                since_ms = since_ts * 1000
        except Exception:
            pass

        if platform == "lichess":
            print(f"[{username}] Fetching Lichess games (since={since_ms})...")
            games = fetch_lichess_games(username, since_ms=since_ms)
        else:
            print(f"[{username}] Fetching Chess.com games (since={since_ts})...")
            games = fetch_games(username, since_ts=since_ts)

        if not games:
            # Incremental sync with nothing new is success, not failure —
            # only error out if the user has no stored games at all.
            existing = supabase.table("games").select("game_id").eq(
                "username", username
            ).limit(1).execute()
            if existing.data:
                print(f"[{username}] No new games — keeping existing report.")
                set_status(username, "ready", last_sync=utcnow_iso())
            else:
                print(f"[{username}] No games found for this account.")
                set_status(username, "error")
            return

        if platform == "lichess":
            players    = games[0].get("players", {})
            white_id   = players.get("white", {}).get("user", {}).get("id", "").lower()
            color      = "white" if white_id == username.lower() else "black"
            current_rating = players.get(color, {}).get("rating")
        else:
            color = "white" if games[0]["white"]["username"].lower() == username.lower() else "black"
            current_rating = games[0][color]["rating"]

        set_status(username, "analyzing", rating_current=current_rating)

        print(f"[{username}] Running analysis ({platform})...")
        if platform == "lichess":
            analyze_lichess_games(username, games, supabase)
        else:
            analyze_games(username, games, supabase)

        set_status(username, "researching")

        print(f"[{username}] Running agents...")
        if not run_agents_and_store(username):
            set_status(username, "error")
            return

        set_status(username, "ready", last_sync=utcnow_iso())
        print(f"[{username}] Done.")

    except Exception as e:
        print(f"[{username}] Error: {e}")
        set_status(username, "error")


# ── ENDPOINTS ─────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Caissa API running"}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/onboard/{username}")
async def onboard(
    username:         str,
    background_tasks: BackgroundTasks,
    platform:         str = Query("chesscom"),
):
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username required")

    existing = supabase.table("users").select("*").eq("username", username).execute()

    if existing.data:
        status = existing.data[0]["status"]
        if status in ["analyzing", "fetching", "researching"]:
            return {"message": f"Already analyzing {username}", "status": status}

    supabase.table("users").upsert({
        "username": username,
        "status":   "pending",
        "platform": platform,
    }).execute()

    background_tasks.add_task(run_analysis, username, platform)
    return {"message": f"Analysis started for {username}", "status": "pending"}


@app.get("/api/status/{username}")
def get_status(username: str):
    result = supabase.table("users").select("*").eq("username", username).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    return result.data[0]


@app.get("/api/profile/{username}")
def get_profile(username: str):
    user = supabase.table("users").select("*").eq("username", username).execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")

    if user.data[0]["status"] != "ready":
        return {"status": user.data[0]["status"], "message": "Analysis not complete yet"}

    report = supabase.table("reports").select("*").eq(
        "username", username
    ).order("created_at", desc=True).limit(1).execute()

    # paginate — these tables routinely exceed the 1000-row PostgREST cap
    games = fetch_all(lambda: supabase.table("games").select(
        "game_id, result, your_rating, opening_name, color, date"
    ).eq("username", username))

    moves = fetch_all(lambda: supabase.table("moves").select(
        "game_phase, mistake_type, centipawn_loss"
    ).eq("username", username))

    # phase stats
    phase_stats = {}
    for phase in ["opening", "middlegame", "endgame"]:
        pm = [m for m in moves if m["game_phase"] == phase]
        if pm:
            blunders = sum(1 for m in pm if m["mistake_type"] == "blunder")
            phase_stats[phase] = {
                "blunder_rate": round(blunders / len(pm), 4),
                "total_moves":  len(pm),
            }

    # opening stats — min 5 games
    from collections import defaultdict
    op = defaultdict(lambda: {"wins": 0, "draws": 0, "total": 0})
    for g in games:
        name = g["opening_name"] or "Unknown"
        op[name]["total"] += 1
        if g["result"] == "win":
            op[name]["wins"] += 1
        elif g["result"] == "draw":
            op[name]["draws"] += 1

    opening_stats = [
        {
            "name":      name,
            "games":     d["total"],
            "wins":      d["wins"],
            "draws":     d["draws"],
            "losses":    d["total"] - d["wins"] - d["draws"],
            "win_rate":  round(d["wins"] / d["total"], 4),
            "draw_rate": round(d["draws"] / d["total"], 4),
        }
        for name, d in op.items() if d["total"] >= 5
    ]
    opening_stats.sort(key=lambda x: x["win_rate"], reverse=True)

    # recent win rate (last 50 games)
    sorted_games = sorted(games, key=lambda x: x["date"], reverse=True)
    recent_50    = sorted_games[:50]
    wins         = sum(1 for g in recent_50 if g["result"] == "win")
    overall_wr   = wins / len(recent_50) if recent_50 else 0

    # rating history — most recent first (frontend reverses for chart)
    ratings = [g["your_rating"] for g in sorted_games if g["your_rating"]]

    # weighted worst phase
    if phase_stats:
        worst_phase = max(
            phase_stats,
            key=lambda p: phase_stats[p]["blunder_rate"] * math.log(
                max(phase_stats[p]["total_moves"], 1)
            )
        )
    else:
        worst_phase = "middlegame"

    return {
        "username":         username,
        "status":           "ready",
        "platform":         user.data[0].get("platform", "chesscom"),
        "phase_stats":      phase_stats,
        "opening_stats":    opening_stats,
        "rating_history":   ratings,
        "overall_win_rate": round(overall_wr, 4),
        "total_games":      len(games),
        "report":           report.data[0] if report.data else None,
        "worst_phase":      worst_phase,
    }


@app.get("/api/report/{username}")
def get_report(username: str):
    report = supabase.table("reports").select("*").eq(
        "username", username
    ).order("created_at", desc=True).limit(1).execute()
    if not report.data:
        raise HTTPException(status_code=404, detail="No report found")

    data = report.data[0]

    # parse patterns JSON
    if data.get("patterns"):
        try:
            data["patterns_parsed"] = json.loads(data["patterns"])
        except Exception:
            data["patterns_parsed"] = []
    else:
        data["patterns_parsed"] = []

    return data


@app.get("/api/patterns/{username}")
def get_patterns(username: str):
    try:
        import chess
        import chess.pgn
        import io
        from collections import defaultdict

        games_res = supabase.table("games").select(
            "game_id, date, pgn, color, result, opening_name"
        ).eq("username", username).order("date", desc=True).limit(20).execute()
        games = games_res.data

        if not games:
            return {"patterns": []}

        games_dict = {g["game_id"]: g for g in games}
        patterns   = defaultdict(list)

        for gid in [g["game_id"] for g in games[:10]]:
            try:
                res = supabase.table("moves").select(
                    "game_id, move_number, move, best_move, centipawn_loss, game_phase, color"
                ).eq("game_id", gid).eq("mistake_type", "blunder").execute()

                for blunder in res.data:
                    game = games_dict.get(blunder["game_id"])
                    if not game or not game.get("pgn"):
                        continue
                    try:
                        pgn_game   = chess.pgn.read_game(io.StringIO(game["pgn"]))
                        if not pgn_game:
                            continue

                        board      = pgn_game.board()
                        moves_list = list(pgn_game.mainline_moves())
                        move_idx   = (blunder["move_number"] - 1) * 2
                        if blunder["color"] == "black":
                            move_idx += 1
                        if move_idx >= len(moves_list):
                            continue

                        for i, m in enumerate(moves_list):
                            if i == move_idx:
                                break
                            board.push(m)

                        fen_before = board.fen()
                        move_uci   = blunder["move"]
                        phase      = blunder["game_phase"] or "middlegame"

                        try:
                            move_obj  = chess.Move.from_uci(move_uci)
                            piece     = board.piece_at(move_obj.from_square)
                            pnames    = {1:"pawn",2:"knight",3:"bishop",4:"rook",5:"queen",6:"king"}
                            piece_str = pnames.get(piece.piece_type if piece else 0, "piece")
                        except Exception:
                            piece_str = "piece"

                        patterns[f"{phase}_{piece_str}"].append({
                            "fen":         fen_before,
                            "move_played": move_uci,
                            "best_move":   blunder["best_move"],
                            "cp_loss":     blunder["centipawn_loss"],
                            "phase":       phase,
                            "piece":       piece_str,
                            "opening":     game.get("opening_name", ""),
                            "date":        game.get("date", ""),
                        })
                    except Exception:
                        continue
            except Exception:
                continue

        ranked = sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True)[:3]
        result = []
        for key, instances in ranked:
            worst = max(instances, key=lambda x: x["cp_loss"] or 0)
            phase, piece = key.split("_", 1)
            result.append({
                "pattern":     f"Hanging {piece} in {phase}",
                "description": f"You blundered a {piece} {len(instances)} times in the {phase}.",
                "frequency":   len(instances),
                "phase":       phase,
                "piece":       piece,
                "example":     worst,
            })

        return {"patterns": result}

    except Exception as e:
        print(f"Patterns error: {e}")
        return {"patterns": []}


@app.post("/api/generate-report/{username}")
async def generate_report(username: str, background_tasks: BackgroundTasks):
    user = supabase.table("users").select("*").eq("username", username).execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="User not found")

    if user.data[0]["status"] == "researching":
        return {"message": "Already generating", "status": "researching"}

    set_status(username, "researching")

    def run_agents():
        try:
            run_agents_and_store(username)
        except Exception as e:
            print(f"[{username}] Agent error: {e}")
        finally:
            # the user still has their data — never strand them in "researching"
            set_status(username, "ready")

    background_tasks.add_task(run_agents)
    return {"message": "Report generation started", "status": "researching"}


@app.get("/api/reference/stats")
def reference_stats():
    result = supabase.table("reference_players").select(
        "rating_band, middlegame_blunder_rate, overall_win_rate"
    ).execute()

    from collections import defaultdict
    bands = defaultdict(list)
    for r in (result.data or []):
        bands[r["rating_band"]].append(r)

    stats = []
    for band, players in sorted(bands.items()):
        stats.append({
            "rating_band":     band,
            "player_count":    len(players),
            "avg_mid_blunder": round(
                sum(p["middlegame_blunder_rate"] or 0 for p in players) / len(players), 4
            ),
            "avg_win_rate":    round(
                sum(p["overall_win_rate"] or 0 for p in players) / len(players), 4
            ),
        })

    return {"bands": stats}


@app.get("/api/openings/{username}")
def get_openings(username: str):
    try:
        from agents import analyze_opening_deviations
        deviations = analyze_opening_deviations(username, supabase)
        return {"deviations": deviations}
    except Exception as e:
        print(f"[{username}] Openings error: {e}")
        return {"deviations": []}


# ── SCHEDULER: daily auto-sync ────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler

def _daily_sync_job():
    """Re-sync every ready user whose data is >20 hours old."""
    try:
        users = supabase.table("users").select(
            "username, last_sync, platform"
        ).eq("status", "ready").execute()

        now = datetime.now(timezone.utc)
        for u in (users.data or []):
            try:
                ls = u.get("last_sync")
                if ls:
                    last = datetime.fromisoformat(ls.replace("Z", "+00:00"))
                    if (now - last).total_seconds() < 72000:  # 20 hours
                        continue
                username = u["username"]
                platform = u.get("platform", "chesscom")
                print(f"[scheduler] auto-syncing {username}...")
                import threading
                t = threading.Thread(target=run_analysis, args=(username, platform), daemon=True)
                t.start()
            except Exception as e:
                print(f"[scheduler] sync error for {u.get('username')}: {e}")
    except Exception as e:
        print(f"[scheduler] daily_sync_job error: {e}")


def _nightly_reference_update():
    """Promote well-analyzed Caissa users into the reference_players table."""
    try:
        from agents import get_weakness_profile
        users = supabase.table("users").select(
            "username, rating_current"
        ).eq("status", "ready").execute()

        for u in (users.data or []):
            username = u["username"]
            try:
                profile = get_weakness_profile(username, supabase)
                if not profile or profile.get("total_games", 0) < 30:
                    continue
                rating = profile.get("chesscom_rating", 0)
                if rating < 400:
                    continue
                bands = [(2500,"2000+"), (2000,"1800-2000"), (1800,"1600-1800"),
                         (1600,"1400-1600"), (1400,"1200-1400"),
                         (1200,"1000-1200"), (1000,"800-1000"), (0,"under-800")]
                band = next(b for threshold, b in bands if rating >= threshold)
                ps = profile["phase_stats"]
                avg_cp = round(
                    sum(ps.get(ph, {}).get("avg_cp_loss", 0) for ph in ["opening","middlegame","endgame"]) / 3, 4
                )
                supabase.table("reference_players").upsert({
                    "username":                username,
                    "rating":                  rating,
                    "rating_band":             band,
                    "games_analyzed":          profile["total_games"],
                    "opening_blunder_rate":    ps.get("opening",    {}).get("blunder_rate", 0),
                    "middlegame_blunder_rate": ps.get("middlegame", {}).get("blunder_rate", 0),
                    "endgame_blunder_rate":    ps.get("endgame",    {}).get("blunder_rate", 0),
                    "avg_cp_loss":             avg_cp,
                    "white_win_rate":          profile.get("overall_win_rate", 0),
                    "black_win_rate":          profile.get("overall_win_rate", 0),
                    "overall_win_rate":        profile.get("overall_win_rate", 0),
                    "best_opening":            profile.get("best_opening", ""),
                    "worst_opening":           profile.get("worst_opening", ""),
                    "trend_slope":             1.0 if profile.get("trend") == "improving" else -1.0,
                    "source":                  "caissa_user",
                }).execute()
                print(f"[scheduler] reference updated: {username} ({rating}, {band})")
            except Exception as e:
                print(f"[scheduler] reference error for {username}: {e}")
    except Exception as e:
        print(f"[scheduler] nightly_reference_update error: {e}")


_scheduler = BackgroundScheduler(timezone="UTC")
_scheduler.add_job(_daily_sync_job,        "cron", hour=3,  minute=0)
_scheduler.add_job(_nightly_reference_update, "cron", hour=4, minute=0)
_scheduler.start()
print("[scheduler] started — daily sync 03:00 UTC, reference update 04:00 UTC")
