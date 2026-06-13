import os
import sys
import json
import math
import numpy as np
import requests

from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conversion import chesscom_to_lichess


# ── LLM + SEARCH (direct REST — no crewai/litellm) ────────
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def gemini_generate(prompt: str, temperature: float = 0.3, timeout: int = 120) -> str:
    """Single-shot Gemini text generation via the public REST API."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = requests.post(url, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        return ""


def serper_search(query: str, num: int = 5, timeout: int = 30) -> list:
    """Google search via Serper. Returns the list of organic results."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("organic", [])
    except Exception as e:
        print(f"[serper] search failed for {query!r}: {e}")
        return []


# ── TACTICAL CLASSIFIER ───────────────────────────────────
def classify_tactic(board, move_played_uci, best_move_uci):
    """
    Classify the type of tactical mistake using python-chess.
    Returns a dict with tactic type, description, and severity.
    """
    import chess

    tactics = []

    try:
        move_played = chess.Move.from_uci(move_played_uci)
        piece_moved = board.piece_at(move_played.from_square)
        piece_name  = {
            chess.PAWN:   "pawn",
            chess.KNIGHT: "knight",
            chess.BISHOP: "bishop",
            chess.ROOK:   "rook",
            chess.QUEEN:  "queen",
            chess.KING:   "king",
        }.get(piece_moved.piece_type if piece_moved else None, "piece")
    except Exception:
        piece_name = "piece"
        move_played = None

    # ── 1. HANGING PIECE ─────────────────────────────────
    # After the move played, are any of our pieces undefended and attacked?
    try:
        board_after = board.copy()
        if move_played:
            board_after.push(move_played)
        color = board_after.turn  # opponent's turn now
        opp   = not color

        for sq in chess.SQUARES:
            piece = board_after.piece_at(sq)
            if piece and piece.color == opp:  # our piece (we just moved)
                attackers  = board_after.attackers(color, sq)   # opponent attacks it
                defenders  = board_after.attackers(opp, sq)     # our defenders
                if attackers and not defenders:
                    tactics.append({
                        "type":   "hanging_piece",
                        "label":  "Hanging Piece",
                        "detail": f"Your {piece_name} move left a {chess.piece_name(piece.piece_type)} undefended on {chess.square_name(sq)}",
                    })
                    break
    except Exception:
        pass

    # ── 2. MISSED FORK (best move was a fork) ─────────────
    try:
        if best_move_uci:
            best_move   = chess.Move.from_uci(best_move_uci)
            board_best  = board.copy()
            board_best.push(best_move)
            best_piece  = board.piece_at(best_move.from_square)
            color       = not board_best.turn  # us

            if best_piece:
                attacked_valuable = []
                for sq in chess.SQUARES:
                    target = board_best.piece_at(sq)
                    if (target and target.color != best_piece.color
                            and target.piece_type in [chess.QUEEN, chess.ROOK, chess.KNIGHT, chess.BISHOP, chess.KING]
                            and board_best.is_attacked_by(best_piece.color, sq)):
                        attacked_valuable.append(chess.piece_name(target.piece_type))

                if len(attacked_valuable) >= 2:
                    tactics.append({
                        "type":   "missed_fork",
                        "label":  "Missed Fork",
                        "detail": f"Best move forked {' and '.join(attacked_valuable[:2])} but you played elsewhere",
                    })
    except Exception:
        pass

    # ── 3. PIN IGNORED ────────────────────────────────────
    try:
        if move_played:
            board_check = board.copy()
            # check if the piece we moved was pinned (moving it exposes king)
            king_sq = board_check.king(board_check.turn)
            if king_sq is not None:
                board_check.push(move_played)
                if board_check.is_check():
                    tactics.append({
                        "type":   "pin_ignored",
                        "label":  "Moved Pinned Piece",
                        "detail": f"Moving your {piece_name} left your king in check — the piece was pinned",
                    })
    except Exception:
        pass

    # ── 4. BACK RANK WEAKNESS ────────────────────────────
    try:
        import chess
        board_after2 = board.copy()
        if move_played:
            board_after2.push(move_played)

        # check if opponent can deliver back rank mate or win
        our_color  = not board_after2.turn
        back_rank  = chess.BB_RANK_1 if our_color == chess.WHITE else chess.BB_RANK_8
        our_king   = board_after2.king(our_color)

        if our_king and chess.BB_SQUARES[our_king] & back_rank:
            # king is on back rank — check if back rank is weak
            rooks_queens = board_after2.pieces(chess.ROOK, not our_color) | \
                           board_after2.pieces(chess.QUEEN, not our_color)
            for sq in chess.scan_forward(rooks_queens):
                piece = board_after2.piece_at(sq)
                if piece:
                    attacks = board_after2.attacks(sq)
                    if attacks & back_rank:
                        tactics.append({
                            "type":   "back_rank",
                            "label":  "Back Rank Weakness",
                            "detail": "Your back rank became vulnerable — opponent's rook/queen threatens the back rank",
                        })
                        break
    except Exception:
        pass

    # ── 5. SKEWER / OVERLOADED ───────────────────────────
    try:
        if best_move_uci and not tactics:
            board_best2 = board.copy()
            best_move2  = chess.Move.from_uci(best_move_uci)
            board_best2.push(best_move2)
            best_piece2 = board.piece_at(best_move2.from_square)

            if best_piece2 and best_piece2.piece_type in [chess.BISHOP, chess.ROOK, chess.QUEEN]:
                # check if it attacks a high-value piece that shields another
                for sq in chess.SQUARES:
                    target = board_best2.piece_at(sq)
                    if (target and target.color != best_piece2.color
                            and target.piece_type in [chess.QUEEN, chess.KING]
                            and board_best2.is_attacked_by(best_piece2.color, sq)):
                        tactics.append({
                            "type":   "missed_skewer",
                            "label":  "Missed Skewer/Discovery",
                            "detail": f"Best move attacked a {chess.piece_name(target.piece_type)} with a long-range piece — potential skewer or discovery",
                        })
                        break
    except Exception:
        pass

    # ── DEFAULT ───────────────────────────────────────────
    if not tactics:
        tactics.append({
            "type":   "positional_blunder",
            "label":  "Positional Blunder",
            "detail": f"Your {piece_name} move significantly worsened your position without a clear tactical reason",
        })

    return tactics[0]  # return most specific tactic found


# ── EXTRACT BLUNDER PATTERNS ──────────────────────────────
def extract_blunder_patterns(username: str, supabase) -> list:
    """
    Extract top blunder patterns from recent games.
    Returns list of pattern dicts with FEN, tactic type, and context.
    """
    import chess
    import chess.pgn
    import io
    from collections import defaultdict

    # get recent 30 games
    games_res = supabase.table("games").select(
        "game_id, date, pgn, color, result, opening_name, your_rating"
    ).eq("username", username).order("date", desc=True).limit(30).execute()
    games = games_res.data

    if not games:
        return []

    games_dict = {g["game_id"]: g for g in games}
    patterns   = defaultdict(list)

    for game_data in games[:20]:
        gid = game_data["game_id"]
        try:
            blunders_res = supabase.table("moves").select(
                "move_number, move, best_move, centipawn_loss, game_phase, color"
            ).eq("game_id", gid).eq("mistake_type", "blunder").order(
                "centipawn_loss", desc=True
            ).limit(3).execute()

            blunders = blunders_res.data
            if not blunders:
                continue

            game_pgn = game_data.get("pgn", "")
            if not game_pgn:
                continue

            pgn_game = chess.pgn.read_game(io.StringIO(game_pgn))
            if not pgn_game:
                continue

            for blunder in blunders:
                try:
                    board      = pgn_game.board()
                    moves_list = list(pgn_game.mainline_moves())
                    move_idx   = (blunder["move_number"] - 1) * 2
                    if blunder["color"] == "black":
                        move_idx += 1
                    if move_idx >= len(moves_list):
                        continue

                    # replay to position before blunder
                    for i, m in enumerate(moves_list):
                        if i == move_idx:
                            break
                        board.push(m)

                    fen_before = board.fen()
                    tactic     = classify_tactic(
                        board,
                        blunder["move"],
                        blunder.get("best_move", ""),
                    )

                    phase = blunder["game_phase"] or "middlegame"
                    key   = f"{tactic['type']}_{phase}"

                    patterns[key].append({
                        "tactic":       tactic,
                        "fen":          fen_before,
                        "move_played":  blunder["move"],
                        "best_move":    blunder.get("best_move"),
                        "cp_loss":      blunder["centipawn_loss"],
                        "phase":        phase,
                        "move_number":  blunder["move_number"],
                        "opening":      game_data.get("opening_name", ""),
                        "date":         game_data.get("date", ""),
                        "your_rating":  game_data.get("your_rating", 0),
                        "user_color":   game_data.get("color", "white"),
                    })
                except Exception:
                    continue

        except Exception:
            continue

    # rank by frequency, take top 3
    ranked = sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True)[:3]

    result = []
    for key, instances in ranked:
        # pick clearest example (highest cp_loss)
        best_example = max(instances, key=lambda x: x["cp_loss"] or 0)
        tactic       = instances[0]["tactic"]
        phase        = instances[0]["phase"]

        result.append({
            "tactic_type":  tactic["type"],
            "tactic_label": tactic["label"],
            "phase":        phase,
            "frequency":    len(instances),
            "avg_cp_loss":  round(sum(i["cp_loss"] or 0 for i in instances) / len(instances)),
            "opening":      best_example["opening"],
            "example": {
                "fen":         best_example["fen"],
                "move_played": best_example["move_played"],
                "best_move":   best_example["best_move"],
                "cp_loss":     best_example["cp_loss"],
                "date":        best_example["date"],
                "user_color":  best_example.get("user_color", "white"),
                "move_number": best_example.get("move_number"),
                "opening":     best_example.get("opening", ""),
            },
            "tactic_detail": tactic["detail"],
            "all_openings":  list({i["opening"] for i in instances if i["opening"]})[:3],
        })

    return result


# ── STEP 1: WEAKNESS PROFILE ──────────────────────────────
def get_weakness_profile(username: str, supabase) -> dict:
    games_res = supabase.table("games").select(
        "game_id, result, your_rating, opening_name, color, date"
    ).eq("username", username).order("date", desc=True).limit(150).execute()
    games = games_res.data

    if not games:
        return {}

    # batch by chunks of game ids (keeps URLs short), and page each chunk
    # past PostgREST's 1000-row cap
    recent_ids = [g["game_id"] for g in games]
    all_moves  = []
    for c in range(0, len(recent_ids), 50):
        chunk = recent_ids[c:c + 50]
        try:
            start = 0
            while True:
                res = supabase.table("moves").select(
                    "game_phase, mistake_type, centipawn_loss"
                ).in_("game_id", chunk).range(start, start + 999).execute()
                data = res.data or []
                all_moves.extend(data)
                if len(data) < 1000:
                    break
                start += 1000
        except Exception:
            continue
    moves = all_moves

    if not moves:
        return {}

    phase_stats = {}
    for phase in ["opening", "middlegame", "endgame"]:
        pm = [m for m in moves if m["game_phase"] == phase]
        if pm:
            blunders     = sum(1 for m in pm if m["mistake_type"] == "blunder")
            cp_losses    = [m["centipawn_loss"] for m in pm if m["centipawn_loss"] is not None]
            blunder_rate = blunders / len(pm)
            avg_cp       = sum(cp_losses) / len(cp_losses) if cp_losses else 0
        else:
            blunder_rate = 0
            avg_cp       = 0
        phase_stats[phase] = {
            "blunder_rate": round(blunder_rate, 4),
            "avg_cp_loss":  round(avg_cp, 2),
            "total_moves":  len(pm),
        }

    recent_50 = games[:50]
    wins      = sum(1 for g in recent_50 if g["result"] == "win")
    overall_wr = wins / len(recent_50) if recent_50 else 0

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

    ratings   = [g["your_rating"] for g in games if g["your_rating"]]
    current_r = ratings[0] if ratings else 0
    recent_20 = ratings[:20]
    prev_20   = ratings[20:40]
    trend     = "improving" if (
        prev_20 and recent_20 and
        sum(recent_20) / len(recent_20) > sum(prev_20) / len(prev_20)
    ) else "declining"

    if phase_stats:
        worst_phase = max(
            phase_stats,
            key=lambda p: phase_stats[p]["blunder_rate"] * math.log(
                max(phase_stats[p]["total_moves"], 1)
            )
        )
    else:
        worst_phase = "middlegame"

    best_opening  = opening_stats[0]["name"]  if opening_stats else "Unknown"
    worst_opening = opening_stats[-1]["name"] if opening_stats else "Unknown"
    best_wr       = opening_stats[0]["win_rate"]  if opening_stats else 0
    worst_wr      = opening_stats[-1]["win_rate"] if opening_stats else 0

    return {
        "username":         username,
        "chesscom_rating":  current_r,
        "lichess_equiv":    chesscom_to_lichess(current_r)[0],
        "total_games":      len(games),
        "games_analyzed":   len(games),
        "overall_win_rate": round(overall_wr, 4),
        "phase_stats":      phase_stats,
        "worst_phase":      worst_phase,
        "best_opening":     best_opening,
        "best_opening_wr":  round(best_wr, 4),
        "worst_opening":    worst_opening,
        "worst_opening_wr": round(worst_wr, 4),
        "top_openings":     opening_stats[:5],
        "trend":            trend,
    }


# ── STEP 2: COLLABORATIVE FILTER ─────────────────────────
def collaborative_filter(profile: dict, supabase) -> dict:
    from sklearn.preprocessing import normalize

    lichess_rating = profile["lichess_equiv"]
    worst_phase    = profile["worst_phase"]

    ref_res = supabase.table("reference_players").select("*").gte(
        "rating", lichess_rating - 200
    ).lte(
        "rating", lichess_rating + 200
    ).execute()
    ref = ref_res.data

    if len(ref) < 10:
        ref_res = supabase.table("reference_players").select("*").execute()
        ref     = ref_res.data

    if not ref:
        return {"insight": "No reference data yet", "similar_players": []}

    phase_weight = {
        "opening":    [3, 1, 1],
        "middlegame": [1, 3, 1],
        "endgame":    [1, 1, 3],
    }[worst_phase]

    def vec(r):
        return [
            (r["opening_blunder_rate"]    or 0) * phase_weight[0],
            (r["middlegame_blunder_rate"] or 0) * phase_weight[1],
            (r["endgame_blunder_rate"]    or 0) * phase_weight[2],
            r["overall_win_rate"]         or 0,
            min(r["rating"] or 0, 2500) / 2500,
        ]

    ref_vecs = np.array([vec(r) for r in ref])
    user_vec = np.array([[
        profile["phase_stats"]["opening"]["blunder_rate"]    * phase_weight[0],
        profile["phase_stats"]["middlegame"]["blunder_rate"] * phase_weight[1],
        profile["phase_stats"]["endgame"]["blunder_rate"]    * phase_weight[2],
        profile["overall_win_rate"],
        min(profile["lichess_equiv"], 2500) / 2500,
    ]])

    sims    = (normalize(ref_vecs) @ normalize(user_vec).T).flatten()
    top_idx = np.argsort(sims)[::-1][:20]
    similar = [ref[i] for i in top_idx]

    improvers = [p for p in similar if (p["trend_slope"] or 0) > 0]
    decliners = [p for p in similar if (p["trend_slope"] or 0) <= 0]

    insight = {}
    if improvers and decliners:
        for metric in ["opening_blunder_rate", "middlegame_blunder_rate", "endgame_blunder_rate"]:
            imp_avg = sum(p[metric] or 0 for p in improvers) / len(improvers)
            dec_avg = sum(p[metric] or 0 for p in decliners) / len(decliners)
            insight[metric] = {
                "improvers_avg": round(imp_avg, 4),
                "decliners_avg": round(dec_avg, 4),
                "gap":           round(dec_avg - imp_avg, 4),
            }

    top_openings = []
    if improvers:
        from collections import Counter
        top_openings = [
            o for o, _ in
            Counter(p["best_opening"] for p in improvers if p["best_opening"]).most_common(3)
        ]

    return {
        "total_similar":                len(similar),
        "improver_count":               len(improvers),
        "decliner_count":               len(decliners),
        "insight":                      insight,
        "top_openings_among_improvers": top_openings,
        "avg_rating_similar":           round(
            sum(p["rating"] or 0 for p in similar) / len(similar), 1
        ) if similar else 0,
    }


# ── STEP 3: COACHING PIPELINE (Gemini + Serper, direct) ───
def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: t.rfind("```")]
    return t.strip()


def _fallback_coaching(patterns: list) -> dict:
    return {
        "coaching": [
            {
                "tactic_type": p.get("tactic_type", "positional_blunder"),
                "paragraph": (
                    f"This {p.get('tactic_label', 'mistake')} pattern showed up "
                    f"{p.get('frequency', 1)} times in your recent games, in the "
                    f"{p.get('phase', 'middlegame')}. {p.get('tactic_detail', '')}."
                ),
                "checklist": [
                    "Before every move, ask: does this leave any piece undefended or newly attacked?",
                    "Visualize your opponent's best reply before you commit to the move.",
                ],
            }
            for p in (patterns or [])
        ]
    }


class CoachPipeline:
    """
    Drop-in replacement for the old CrewAI Crew. Runs three steps with direct
    REST calls (Gemini for text, Serper for search) and exposes the same
    `.kickoff()` interface, returning the combined diagnosis + resources text.
    The coaching JSON is exposed separately as `.coaching_json`.
    """

    def __init__(self, profile: dict, collab: dict, patterns: list):
        self.profile      = profile
        self.collab       = collab
        self.patterns     = patterns
        self.coaching_json = None

    # ── step 1: diagnosis ─────────────────────────────────
    def _diagnosis(self) -> str:
        prompt = f"""You are an expert chess analyst. You give highly specific,
data-driven diagnoses based ONLY on recent game data. Every claim references a
specific number. You never give generic chess advice.

Analyze this player's RECENT game data (last {self.profile.get('games_analyzed', 150)} games).

RECENT GAME DATA:
{json.dumps(self.profile, indent=2)}

SIMILAR PLAYERS AT SAME RATING:
{json.dumps(self.collab, indent=2)}

Write a specific 3-4 paragraph diagnosis:
1. Their single worst problem RIGHT NOW (use the blunder rates).
2. How bad it is compared to improving players at the same rating.
3. What the numbers suggest about their thought process.
4. An exact study prescription: what to do, how many minutes per day, at what
   difficulty, for how long.

Be brutal and specific. Reference actual numbers. Plain prose — no headers,
no markdown bullets, no '###'."""
        try:
            return gemini_generate(prompt, temperature=0.3)
        except Exception as e:
            print(f"[pipeline] diagnosis failed: {e}")
            wp = self.profile.get("worst_phase", "middlegame")
            br = self.profile.get("phase_stats", {}).get(wp, {}).get("blunder_rate", 0)
            return (
                f"Your weakest phase is the {wp}, with a {br:.1%} blunder rate. "
                f"Focus your training there."
            )

    # ── step 2: coaching JSON ─────────────────────────────
    def _coaching(self) -> str:
        if not self.patterns:
            data = _fallback_coaching([])
            self.coaching_json = json.dumps(data)
            return self.coaching_json

        prompt = f"""You are a chess coach writing to a player directly. For EACH
tactical pattern below, write personalized coaching.

TACTICAL PATTERNS:
{json.dumps(self.patterns, indent=2)}

PLAYER CONTEXT:
- Rating: {self.profile.get('chesscom_rating')}
- Worst phase: {self.profile.get('worst_phase')}
- Trend: {self.profile.get('trend')}

For each pattern: explain WHY it keeps recurring (what they think wrong), the
position context where it happens, a concrete 2-step mental checklist to prevent
it, and how it costs rating at this level. 4-6 sentences per paragraph.

Respond with ONLY valid JSON, no markdown fences:
{{"coaching": [{{"tactic_type": "...", "paragraph": "...", "checklist": ["step 1", "step 2"]}}]}}
Use the exact tactic_type values from the patterns above."""
        try:
            raw   = gemini_generate(prompt, temperature=0.4)
            clean = _strip_code_fences(raw)
            data  = json.loads(clean)
            if isinstance(data, dict) and data.get("coaching"):
                self.coaching_json = json.dumps(data)
                return self.coaching_json
        except Exception as e:
            print(f"[pipeline] coaching failed, using fallback: {e}")
        self.coaching_json = json.dumps(_fallback_coaching(self.patterns))
        return self.coaching_json

    # ── step 3: resources (search + format) ───────────────
    def _resources(self) -> str:
        p        = self.profile
        wp       = p.get("worst_phase", "middlegame")
        rating   = p.get("chesscom_rating", 1200)
        top      = self.patterns[0] if self.patterns else None
        label    = top["tactic_label"] if top else wp
        best_op  = p.get("best_opening", "your main opening")

        searches = [
            ("youtube",  f"Daniel Naroditsky {label} chess lesson"),
            ("lichess",  f"lichess.org study {wp} tactics"),
            ("youtube",  f"{best_op} chess opening explained Hanging Pawns"),
            ("article",  f"how to stop {label} chess improvement article"),
            ("youtube",  f"{wp} chess improvement {rating} rating tips"),
        ]

        def pick(kind, results, used):
            for r in results:
                link = r.get("link", "")
                if not link.startswith("http") or link in used:
                    continue
                is_yt  = "youtube.com" in link or "youtu.be" in link
                is_li  = "lichess.org" in link
                if kind == "youtube" and not is_yt:
                    continue
                if kind == "lichess" and not is_li:
                    continue
                if kind == "article" and (is_yt or is_li):
                    continue
                return r
            # fall back to first usable result of any kind
            for r in results:
                link = r.get("link", "")
                if link.startswith("http") and link not in used:
                    return r
            return None

        used, chosen = set(), []
        for kind, query in searches:
            picked = pick(kind, serper_search(query, num=8), used)
            if picked:
                used.add(picked["link"])
                chosen.append((kind, query, picked))

        if not chosen:
            return ""

        # let Gemini write the per-resource relevance, but only over real URLs
        candidates = [
            {"title": c[2].get("title", "Resource"),
             "url":   c[2]["link"],
             "snippet": c[2].get("snippet", "")}
            for c in chosen
        ]
        prompt = f"""A chess player rated {rating} (~{p.get('lichess_equiv')} Lichess)
has a critical weakness in the {wp} ({label}). Their best opening is {best_op}.

Below are real, verified study resources (use these EXACT urls — do not change
or invent any). For each, write one sentence of relevance to THIS player's
{label} problem.

RESOURCES:
{json.dumps(candidates, indent=2)}

Output EXACTLY this markdown, one block per resource, numbered from 1:
### 1.
**Title:** <title>
**URL:** <exact url>
**Relevance:** <one sentence>

No preamble, no closing text."""
        try:
            md = gemini_generate(prompt, temperature=0.3)
            if "**URL:**" in md and "https://" in md:
                return md.strip()
        except Exception as e:
            print(f"[pipeline] resource formatting failed, using template: {e}")

        # deterministic fallback formatting
        lines = []
        for i, (kind, query, r) in enumerate(chosen, 1):
            lines.append(f"### {i}.")
            lines.append(f"**Title:** {r.get('title', 'Resource')}")
            lines.append(f"**URL:** {r['link']}")
            lines.append(f"**Relevance:** Matched to your {label} weakness in the {wp}.")
            lines.append("")
        return "\n".join(lines).strip()

    def kickoff(self) -> str:
        print("[pipeline] step 1/3 — diagnosis...")
        diagnosis = self._diagnosis()
        print("[pipeline] step 2/3 — coaching...")
        self._coaching()
        print("[pipeline] step 3/3 — researching resources...")
        resources = self._resources()
        parts = [diagnosis.strip()]
        if resources:
            parts.append(resources.strip())
        return "\n\n".join(parts)


def build_crew(profile: dict, collab: dict, patterns: list) -> CoachPipeline:
    return CoachPipeline(profile, collab, patterns)


def analyze_opening_deviations(username: str, supabase) -> list:
    """
    For each recent game, find the first move where the user deviates from
    Lichess opening theory (explorer.lichess.ovh). Logs every step so
    silence in the console means the issue is before that line.
    """
    import chess
    import chess.pgn
    import io
    import requests
    import time
    from collections import defaultdict

    print(f"[openings:{username}] fetching games from supabase...")
    games_res = supabase.table("games").select(
        "game_id, date, pgn, color, result, opening_name, opening_eco"
    ).eq("username", username).order("date", desc=True).limit(20).execute()
    games = games_res.data or []
    print(f"[openings:{username}] {len(games)} games found")

    if not games:
        print(f"[openings:{username}] no games — returning empty")
        return []

    # pre-load blunder move numbers for cross-referencing
    blunder_map = defaultdict(set)
    for g in games[:10]:
        gid = g["game_id"]
        try:
            res = supabase.table("moves").select("move_number, mistake_type").eq("game_id", gid).execute()
            for m in (res.data or []):
                if m["mistake_type"] in ("blunder", "mistake"):
                    blunder_map[gid].add(m["move_number"])
        except Exception:
            pass

    HEADERS = {"User-Agent": "Caissa/1.0 (chess analysis; contact abhi.sjaswal6@gmail.com)"}
    deviation_records = []
    api_calls_made = 0

    def query_explorer(fen):
        nonlocal api_calls_made
        url = "https://explorer.lichess.ovh/lichess"
        params = {
            "fen":         fen,
            "moves":       5,
            "topGames":    0,
            "recentGames": 0,
            "ratings":     "1200,1400,1600,1800,2000",
        }
        for attempt in range(3):
            try:
                print(f"  [lichess-explorer] GET attempt {attempt+1} — fen={fen[:40]}...")
                resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
                api_calls_made += 1
                print(f"  [lichess-explorer] status={resp.status_code} "
                      f"moves={len(resp.json().get('moves', [])) if resp.status_code == 200 else '?'}")
                time.sleep(0.6)
                if resp.status_code == 429:
                    wait = 4 * (attempt + 1)
                    print(f"  [lichess-explorer] rate-limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                print(f"  [lichess-explorer] error attempt {attempt+1}: {e}")
                time.sleep(2)
        return None

    for i, game_data in enumerate(games[:10]):
        gid     = game_data["game_id"]
        pgn_str = game_data.get("pgn") or ""
        print(f"[openings:{username}] game {i+1}/10  id={gid[:8]}  pgn_len={len(pgn_str)}  "
              f"color={game_data.get('color')}  opening={game_data.get('opening_name', '?')[:30]}")

        if not pgn_str:
            print(f"  → skipping: no PGN stored")
            continue

        try:
            pgn_game = chess.pgn.read_game(io.StringIO(pgn_str))
            if not pgn_game:
                print(f"  → skipping: PGN parse failed")
                continue

            board      = pgn_game.board()
            moves_list = list(pgn_game.mainline_moves())
            user_color = (game_data.get("color") or "white").lower()
            print(f"  {len(moves_list)} total moves, user_color={user_color}")

            found_deviation = False
            for j, move in enumerate(moves_list[:20]):
                move_color = "white" if board.turn == chess.WHITE else "black"

                if move_color != user_color:
                    board.push(move)
                    continue

                fen     = board.fen()
                move_num = j // 2 + 1

                try:
                    user_san = board.san(move)
                except Exception:
                    user_san = move.uci()

                data = query_explorer(fen)
                if data is None:
                    board.push(move)
                    continue

                theory_moves = data.get("moves", [])
                user_uci     = move.uci()

                if not theory_moves:
                    print(f"  → off-book on move {move_num} ({user_san})")
                    deviation_records.append({
                        "game_id":       gid,
                        "opening":       game_data.get("opening_name") or "Unknown",
                        "eco":           game_data.get("opening_eco") or "",
                        "move_number":   move_num,
                        "user_move":     user_uci,
                        "user_move_san": user_san,
                        "theory_move":   None,
                        "theory_san":    None,
                        "theory_games":  0,
                        "is_blunder":    move_num in blunder_map.get(gid, set()),
                        "type":          "out_of_book",
                        "user_color":    user_color,
                    })
                    found_deviation = True
                    board.push(move)
                    break

                theory_ucis = [m["uci"] for m in theory_moves]
                if user_uci not in theory_ucis:
                    best  = theory_moves[0]
                    total = sum(
                        m.get("white", 0) + m.get("draws", 0) + m.get("black", 0)
                        for m in theory_moves[:3]
                    )
                    print(f"  → deviation on move {move_num}: played {user_san}, "
                          f"theory={best.get('san', best['uci'])} ({total} games)")
                    deviation_records.append({
                        "game_id":       gid,
                        "opening":       game_data.get("opening_name") or "Unknown",
                        "eco":           game_data.get("opening_eco") or "",
                        "move_number":   move_num,
                        "user_move":     user_uci,
                        "user_move_san": user_san,
                        "theory_move":   best["uci"],
                        "theory_san":    best.get("san", best["uci"]),
                        "theory_games":  total,
                        "is_blunder":    move_num in blunder_map.get(gid, set()),
                        "type":          "deviation",
                        "user_color":    user_color,
                    })
                    found_deviation = True
                    board.push(move)
                    break

                board.push(move)

            if not found_deviation:
                print(f"  → all moves in theory (no deviation found)")

        except Exception as e:
            print(f"[openings:{username}] game {gid[:8]} error: {e}")
            continue

    print(f"[openings:{username}] done — {api_calls_made} API calls, "
          f"{len(deviation_records)} deviations found")

    deviation_by_opening = defaultdict(list)
    for rec in deviation_records:
        deviation_by_opening[rec.get("opening", "Unknown")].append(rec)

    results = []
    for opening, recs in sorted(deviation_by_opening.items(), key=lambda x: -len(x[1])):
        blunders = [r for r in recs if r["is_blunder"]]
        earliest = min(recs, key=lambda x: x["move_number"])
        results.append({
            "opening":       opening,
            "eco":           earliest.get("eco", ""),
            "frequency":     len(recs),
            "blunder_count": len(blunders),
            "avg_move_num":  round(sum(r["move_number"] for r in recs) / len(recs), 1),
            "example": {
                "move_number":   earliest["move_number"],
                "user_move":     earliest["user_move"],
                "user_move_san": earliest.get("user_move_san", earliest["user_move"]),
                "theory_move":   earliest.get("theory_move"),
                "theory_san":    earliest.get("theory_san"),
                "theory_games":  earliest.get("theory_games", 0),
                "type":          earliest["type"],
                "user_color":    earliest["user_color"],
            },
        })

    return results[:5]


# ── STANDALONE RUN ────────────────────────────────────────
if __name__ == "__main__":
    from supabase import create_client

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_KEY"),
    )

    username = sys.argv[1] if len(sys.argv) > 1 else "Chesspin_one"
    print(f"\n► Building profile for {username}...")
    profile = get_weakness_profile(username, supabase)
    if not profile:
        print("No data found.")
        exit()

    print(f"  Rating:      {profile['chesscom_rating']}")
    print(f"  Worst phase: {profile['worst_phase']} "
          f"({profile['phase_stats'][profile['worst_phase']]['blunder_rate']:.1%})")

    print("\n► Running collaborative filter...")
    collab = collaborative_filter(profile, supabase)

    print("\n► Extracting tactical patterns...")
    patterns = extract_blunder_patterns(username, supabase)
    print(f"  Found {len(patterns)} patterns:")
    for p in patterns:
        print(f"  - {p['tactic_label']} in {p['phase']} × {p['frequency']} times")

    print("\n► Launching 3 agents...")
    crew   = build_crew(profile, collab, patterns)
    result = crew.kickoff()

    # save to Supabase
    supabase.table("reports").delete().eq("username", username).execute()
    supabase.table("reports").insert({
        "username":        username,
        "weakness_phase":  profile["worst_phase"],
        "blunder_rate":    profile["phase_stats"][profile["worst_phase"]]["blunder_rate"],
        "recommendations": json.dumps(profile, default=str),
        "resources":       str(result),
        "patterns":        json.dumps(patterns, default=str),
    }).execute()
    print("✓ Report saved to Supabase")
    print(result)
