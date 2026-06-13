import os
import sys
import time
import json
import chess
import chess.pgn
import io
import requests
from stockfish import Stockfish
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STOCKFISH_PATH = os.getenv("STOCKFISH_PATH")
ANALYSIS_DEPTH = int(os.getenv("ANALYSIS_DEPTH", "8"))
HEADERS        = {"User-Agent": "Caissa/1.0 chess analysis tool"}
MAX_GAMES      = int(os.getenv("MAX_GAMES", "150"))

# log at import time so Railway shows this in startup logs
_sf_exists = os.path.isfile(STOCKFISH_PATH) if STOCKFISH_PATH else False
print(f"[pipeline] STOCKFISH_PATH={STOCKFISH_PATH!r}  exists={_sf_exists}")


# ── HELPERS ───────────────────────────────────────────────
def classify_mistake(cp_loss):
    if cp_loss is None: return "unknown"
    if cp_loss >= 300:  return "blunder"
    if cp_loss >= 100:  return "mistake"
    if cp_loss >= 50:   return "inaccuracy"
    return "good"


def classify_phase(move_num, piece_count):
    if move_num <= 10:    return "opening"
    if piece_count <= 10: return "endgame"
    return "middlegame"


def make_sf():
    return Stockfish(STOCKFISH_PATH, depth=ANALYSIS_DEPTH)


# ── CHESS.COM ─────────────────────────────────────────────
def fetch_games(username: str, since_ts: int = None) -> list:
    """Fetch most recent rapid games from Chess.com, capped at MAX_GAMES."""
    try:
        archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
        archives     = requests.get(archives_url, headers=HEADERS, timeout=30).json()
        all_archives = archives.get("archives", [])

        all_games = []
        for url in reversed(all_archives):
            if len(all_games) >= MAX_GAMES:
                break
            try:
                month = requests.get(url, headers=HEADERS, timeout=30).json()
                rapid = [g for g in month.get("games", []) if g.get("time_class") == "rapid"]
                all_games.extend(rapid)
                # stop fetching older archives once we're past the since date
                if since_ts and rapid:
                    oldest = min(g.get("end_time", 0) for g in rapid)
                    if oldest < since_ts:
                        break
            except Exception:
                continue
            time.sleep(0.2)

        all_games.sort(key=lambda x: x.get("end_time", 0), reverse=True)
        result = all_games[:MAX_GAMES]
        print(f"[{username}] Fetched {len(result)} Chess.com rapid games (capped at {MAX_GAMES})")
        return result

    except Exception as e:
        print(f"[{username}] fetch_games error: {e}")
        return []


def analyze_games(username: str, games_data: list, supabase) -> None:
    """Run Stockfish on Chess.com games and save to Supabase."""
    if not STOCKFISH_PATH:
        raise ValueError("STOCKFISH_PATH not set in .env")

    games_data   = games_data[:MAX_GAMES]
    existing     = supabase.table("games").select("game_id").eq("username", username).execute()
    existing_ids = {r["game_id"] for r in (existing.data or [])}

    to_analyze = [
        g for g in games_data
        if (g.get("uuid") or g.get("url", "").split("/")[-1]) not in existing_ids
    ]

    if not to_analyze:
        print(f"[{username}] No new Chess.com games to analyze")
        return

    total    = len(to_analyze)
    analyzed = 0
    print(f"[{username}] Analyzing {total} new Chess.com games at depth {ANALYSIS_DEPTH}...")

    sf = make_sf()

    for game_data in to_analyze:
        game_id = game_data.get("uuid") or game_data.get("url", "").split("/")[-1]
        if not game_id:
            continue

        pgn_str = game_data.get("pgn", "")
        if not pgn_str:
            continue

        try:
            game = chess.pgn.read_game(io.StringIO(pgn_str))
            if not game:
                continue

            headers  = game.headers
            white    = game_data["white"]["username"].lower()
            color    = "white" if white == username.lower() else "black"
            result_r = game_data[color]["result"]
            result   = (
                "win"  if result_r == "win" else
                "loss" if result_r in ["checkmated", "timeout", "resigned", "abandoned", "lose"] else
                "draw"
            )

            from datetime import datetime
            ts   = datetime.fromtimestamp(game_data.get("end_time", 0))
            date = ts.strftime("%Y-%m-%d")

            supabase.table("games").upsert({
                "game_id":         game_id,
                "username":        username,
                "date":            date,
                "time_class":      game_data.get("time_class"),
                "color":           color,
                "opponent_rating": game_data["black" if color == "white" else "white"]["rating"],
                "your_rating":     game_data[color]["rating"],
                "result":          result,
                "opening_name":    headers.get("ECOUrl", "").split("/")[-1].replace("-", " "),
                "opening_eco":     headers.get("ECO", ""),
                "pgn":             pgn_str,
            }).execute()

            board      = game.board()
            moves_list = list(game.mainline_moves())
            batch      = []
            sf_dead    = False

            for j, move in enumerate(moves_list):
                move_color = "white" if board.turn == chess.WHITE else "black"

                if move_color == color and not sf_dead:
                    try:
                        sf.set_fen_position(board.fen())
                        raw         = sf.get_evaluation()
                        eval_before = (
                            10000  if raw["type"] == "mate" and raw["value"] > 0
                            else -10000 if raw["type"] == "mate"
                            else raw["value"]
                        )
                        best_move = sf.get_best_move()
                    except Exception:
                        try: sf = make_sf()
                        except Exception: sf_dead = True
                        board.push(move)
                        continue
                else:
                    eval_before = None
                    best_move   = None

                board.push(move)

                if move_color == color and eval_before is not None and not sf_dead:
                    try:
                        sf.set_fen_position(board.fen())
                        raw2       = sf.get_evaluation()
                        eval_after = (
                            10000  if raw2["type"] == "mate" and raw2["value"] > 0
                            else -10000 if raw2["type"] == "mate"
                            else raw2["value"]
                        )
                    except Exception:
                        try: sf = make_sf()
                        except Exception: sf_dead = True
                        continue

                    cp_loss  = (
                        max(0, eval_before - eval_after) if color == "white"
                        else max(0, eval_after - eval_before)
                    )
                    move_num = j // 2 + 1

                    batch.append({
                        "game_id":        game_id,
                        "username":       username,
                        "move_number":    move_num,
                        "color":          move_color,
                        "move":           move.uci(),
                        "best_move":      best_move,
                        "eval_before":    eval_before,
                        "eval_after":     eval_after,
                        "centipawn_loss": cp_loss,
                        "mistake_type":   classify_mistake(cp_loss),
                        "game_phase":     classify_phase(move_num, len(board.piece_map())),
                    })

            if batch:
                supabase.table("moves").insert(batch).execute()

            existing_ids.add(game_id)
            analyzed += 1
            print(f"[{username}] Analyzed {analyzed}/{total}...", end="\r")

        except Exception as e:
            print(f"\n[{username}] Skipped game {game_id}: {e}")
            continue

    print(f"\n[{username}] Chess.com analysis complete — {analyzed} new games")


# ── LICHESS ───────────────────────────────────────────────
def fetch_lichess_games(username: str, since_ms: int = None) -> list:
    """
    Fetch recent rapid+blitz games from Lichess.
    Requests evals and PGN in JSON format.
    """
    try:
        url    = f"https://lichess.org/api/games/user/{username}"
        params = {
            "max":       MAX_GAMES,
            "perfType":  "rapid,blitz",
            "evals":     "true",
            "opening":   "true",
            "clocks":    "false",
            "moves":     "true",
            "pgnInJson": "true",
        }
        if since_ms:
            params["since"] = since_ms
        headers = {"Accept": "application/x-ndjson", "User-Agent": "Caissa/1.0"}
        res     = requests.get(url, params=params, headers=headers, timeout=30, stream=True)
        games   = []
        for line in res.iter_lines():
            if line:
                try:
                    games.append(json.loads(line))
                except Exception:
                    continue
        print(f"[{username}] Fetched {len(games)} Lichess games")
        return games
    except Exception as e:
        print(f"[{username}] Lichess fetch error: {e}")
        return []


def analyze_lichess_games(username: str, games_data: list, supabase) -> None:
    """
    Hybrid Lichess analysis:
    - Uses pre-computed Lichess evals when available (fast)
    - Falls back to Stockfish for unanalyzed games
    """
    if not STOCKFISH_PATH:
        raise ValueError("STOCKFISH_PATH not set in .env")

    existing     = supabase.table("games").select("game_id").eq("username", username).execute()
    existing_ids = {r["game_id"] for r in (existing.data or [])}
    to_analyze   = [g for g in games_data if g.get("id") not in existing_ids]

    if not to_analyze:
        print(f"[{username}] No new Lichess games")
        return

    total          = len(to_analyze)
    used_lichess   = 0
    used_stockfish = 0
    sf             = make_sf()

    print(f"[{username}] Processing {total} Lichess games (hybrid mode)...")

    for i, game_data in enumerate(to_analyze):
        game_id = game_data.get("id")
        if not game_id:
            continue

        try:
            # build PGN string — try pgn field first, then construct from moves
            pgn_str = game_data.get("pgn", "")
            if not pgn_str:
                moves_str = game_data.get("moves", "")
                if not moves_str:
                    continue
                pgn_str = f'[Event "Lichess"]\n[White "?"]\n[Black "?"]\n\n{moves_str}'

            game = chess.pgn.read_game(io.StringIO(pgn_str))
            if not game:
                continue

            players  = game_data.get("players", {})
            white_id = players.get("white", {}).get("user", {}).get("id", "").lower()
            color    = "white" if white_id == username.lower() else "black"
            opp_col  = "black" if color == "white" else "white"

            winner = game_data.get("winner", "")
            if winner == color:
                result = "win"
            elif winner and winner != color:
                result = "loss"
            else:
                result = "draw"

            from datetime import datetime
            date_str = datetime.fromtimestamp(
                game_data.get("createdAt", 0) / 1000
            ).strftime("%Y-%m-%d")

            your_rating = players.get(color,   {}).get("rating", 0)
            opp_rating  = players.get(opp_col, {}).get("rating", 0)
            opening     = game_data.get("opening", {}).get("name", "Unknown")

            supabase.table("games").upsert({
                "game_id":         game_id,
                "username":        username,
                "date":            date_str,
                "time_class":      game_data.get("perf", "rapid"),
                "color":           color,
                "opponent_rating": opp_rating,
                "your_rating":     your_rating,
                "result":          result,
                "opening_name":    opening,
                "opening_eco":     game_data.get("opening", {}).get("eco", ""),
                "pgn":             pgn_str,
            }).execute()

            lichess_analysis = game_data.get("analysis", [])
            board      = game.board()
            moves_list = list(game.mainline_moves())
            batch      = []

            if lichess_analysis:
                # ── fast path: use Lichess pre-computed evals ──
                for j, move in enumerate(moves_list):
                    move_color = "white" if board.turn == chess.WHITE else "black"

                    if j > 0 and j < len(lichess_analysis) and (j - 1) < len(lichess_analysis):
                        prev = lichess_analysis[j - 1]
                        curr = lichess_analysis[j]

                        if prev.get("mate") is not None:
                            eval_before = 10000 if prev["mate"] > 0 else -10000
                        elif prev.get("eval") is not None:
                            eval_before = prev["eval"]
                        else:
                            board.push(move)
                            continue

                        if curr.get("mate") is not None:
                            eval_after = 10000 if curr["mate"] > 0 else -10000
                        elif curr.get("eval") is not None:
                            eval_after = curr["eval"]
                        else:
                            board.push(move)
                            continue

                        if move_color == color:
                            cp_loss = (
                                max(0, eval_before - eval_after) if color == "white"
                                else max(0, eval_after - eval_before)
                            )
                            board.push(move)
                            piece_count = len(board.piece_map())
                            move_num    = j // 2 + 1
                            batch.append({
                                "game_id":        game_id,
                                "username":       username,
                                "move_number":    move_num,
                                "color":          move_color,
                                "move":           move.uci(),
                                "best_move":      curr.get("best"),
                                "eval_before":    eval_before,
                                "eval_after":     eval_after,
                                "centipawn_loss": cp_loss,
                                "mistake_type":   classify_mistake(cp_loss),
                                "game_phase":     classify_phase(move_num, piece_count),
                            })
                        else:
                            board.push(move)
                    else:
                        board.push(move)

                used_lichess += 1

            else:
                # ── fallback: Stockfish ───────────────────────
                sf_dead = False
                for j, move in enumerate(moves_list):
                    move_color = "white" if board.turn == chess.WHITE else "black"

                    if move_color == color and not sf_dead:
                        try:
                            sf.set_fen_position(board.fen())
                            raw         = sf.get_evaluation()
                            eval_before = (
                                10000  if raw["type"] == "mate" and raw["value"] > 0
                                else -10000 if raw["type"] == "mate"
                                else raw["value"]
                            )
                            best_move = sf.get_best_move()
                        except Exception:
                            try: sf = make_sf()
                            except Exception: sf_dead = True
                            board.push(move)
                            continue
                    else:
                        eval_before = None
                        best_move   = None

                    board.push(move)

                    if move_color == color and eval_before is not None and not sf_dead:
                        try:
                            sf.set_fen_position(board.fen())
                            raw2       = sf.get_evaluation()
                            eval_after = (
                                10000  if raw2["type"] == "mate" and raw2["value"] > 0
                                else -10000 if raw2["type"] == "mate"
                                else raw2["value"]
                            )
                        except Exception:
                            try: sf = make_sf()
                            except Exception: sf_dead = True
                            continue

                        cp_loss  = (
                            max(0, eval_before - eval_after) if color == "white"
                            else max(0, eval_after - eval_before)
                        )
                        move_num = j // 2 + 1
                        batch.append({
                            "game_id":        game_id,
                            "username":       username,
                            "move_number":    move_num,
                            "color":          move_color,
                            "move":           move.uci(),
                            "best_move":      best_move,
                            "eval_before":    eval_before,
                            "eval_after":     eval_after,
                            "centipawn_loss": cp_loss,
                            "mistake_type":   classify_mistake(cp_loss),
                            "game_phase":     classify_phase(move_num, len(board.piece_map())),
                        })

                used_stockfish += 1

            if batch:
                supabase.table("moves").insert(batch).execute()

            existing_ids.add(game_id)
            print(f"[{username}] Processed {i + 1}/{total}...", end="\r")

        except Exception as e:
            print(f"\n[{username}] Skipped Lichess game {game_id}: {e}")
            continue

    print(f"\n[{username}] Lichess complete — "
          f"{used_lichess} used Lichess evals, "
          f"{used_stockfish} used Stockfish")

    if used_stockfish > 0:
        print(f"\n💡 TIP for {username}: {used_stockfish} games had no Lichess analysis.")
        print(f"   After each game, click 'Request computer analysis' to pre-compute evals.")
        print(f"   This makes Caissa analysis instant for those games next time.")
        print(f"   Visit: https://lichess.org/@/{username}/all")
