import requests
import chess
import sqlite3
import time
import json
import pandas as pd
from tqdm import tqdm

# ── CONFIG ───────────────────────────────────────────────
DB_PATH          = r"C:\Users\abhis\Downloads\Research\Caissa\data\caissa.db"
HEADERS          = {"User-Agent": "Caissa/1.0 personal project"}
PLAYERS_PER_BAND = 100
GAMES_PER_PLAYER = 30

# all Lichess rapid rating bands we want to cover
# any Chess.com user at any level maps into one of these
ALL_BANDS = [800, 1000, 1200, 1400, 1600, 1800, 2000]

# ── DATABASE ─────────────────────────────────────────────
def init_reference_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS reference_players (
            username                TEXT PRIMARY KEY,
            rating                  INTEGER,
            rating_band             TEXT,
            games_analyzed          INTEGER,
            opening_blunder_rate    REAL,
            middlegame_blunder_rate REAL,
            endgame_blunder_rate    REAL,
            avg_cp_loss             REAL,
            white_win_rate          REAL,
            black_win_rate          REAL,
            overall_win_rate        REAL,
            best_opening            TEXT,
            worst_opening           TEXT,
            trend_slope             REAL,
            source                  TEXT
        )
    """)
    conn.commit()
    return conn

# ── SEED PLAYERS ─────────────────────────────────────────
def fetch_seed_players(low, high, count, conn):
    """
    Seeds from players already in the reference DB for this band,
    then crawls their opponents to find new ones.
    Self-expanding — no hardcoded names.
    """
    players = set()
    print(f"  Seeding players for band {low}-{high}...")

    # use players already in DB for this specific band as seeds
    band_existing = pd.read_sql(
        "SELECT username FROM reference_players WHERE rating_band = ?",
        conn, params=(str(high),)
    )
    db_seeds = band_existing["username"].tolist()

    # also pull from adjacent bands to cross-pollinate
    if len(db_seeds) < 10:
        all_existing = pd.read_sql(
            "SELECT username FROM reference_players", conn
        )
        db_seeds = all_existing["username"].tolist()

    print(f"  {len(db_seeds)} existing players to seed from")

    if not db_seeds:
        print("  No seeds — bootstrap will handle this band")
        return []

    players.update(db_seeds)

    # crawl opponents of seeds to find new players in this band
    print(f"  Crawling opponents...")
    for seed in db_seeds:
        if len(players) >= count * 2:
            break
        try:
            r = requests.get(
                f"https://lichess.org/api/games/user/{seed}"
                f"?max=50&perfType=rapid&rated=true"
                f"&clocks=false&evals=false",
                headers={**HEADERS, "Accept": "application/x-ndjson"},
                timeout=10
            )
            if r.status_code == 200:
                for line in r.text.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        g = json.loads(line)
                        for side in ["white", "black"]:
                            p      = g.get("players", {}).get(side, {})
                            u      = p.get("user", {}).get("name", "")
                            rating = p.get("rating", 0)
                            if u and low <= rating <= high:
                                players.add(u)
                    except:
                        continue
            time.sleep(0.3)
        except:
            continue

    print(f"  Found {len(players)} candidates")
    return list(players)[:count]

# ── FETCH GAMES ───────────────────────────────────────────
def fetch_lichess_games(username, max_games=30):
    url = (
        f"https://lichess.org/api/games/user/{username}"
        f"?max={max_games}&perfType=rapid&clocks=false"
        f"&evals=true&opening=true&rated=true&analysed=true"
    )
    response = requests.get(
        url,
        headers={**HEADERS, "Accept": "application/x-ndjson"},
        timeout=15
    )
    if response.status_code != 200:
        return []
    games = []
    for line in response.text.strip().split("\n"):
        if line:
            try:
                games.append(json.loads(line))
            except:
                continue
    return games

# ── BUILD PROFILE ─────────────────────────────────────────
def build_profile_from_lichess_games(username, games_data):
    if not games_data:
        return None

    phase_stats = {
        "opening":    {"blunders": 0, "total": 0, "cp_loss": []},
        "middlegame": {"blunders": 0, "total": 0, "cp_loss": []},
        "endgame":    {"blunders": 0, "total": 0, "cp_loss": []},
    }
    results       = {"win": 0, "loss": 0, "draw": 0}
    color_results = {
        "white": {"win": 0, "total": 0},
        "black": {"win": 0, "total": 0},
    }
    opening_results   = {}
    ratings_over_time = []
    games_with_evals  = 0

    for game in games_data:
        white_name = (
            game.get("players", {})
                .get("white", {})
                .get("user", {})
                .get("name", "")
                .lower()
        )
        color = "white" if white_name == username.lower() else "black"

        winner = game.get("winner", None)
        if winner == color:
            result = "win";  results["win"] += 1
            color_results[color]["win"] += 1
        elif winner is None:
            result = "draw"; results["draw"] += 1
        else:
            result = "loss"; results["loss"] += 1
        color_results[color]["total"] += 1

        rating = game.get("players", {}).get(color, {}).get("rating", 0)
        if rating:
            ratings_over_time.append(rating)

        opening = game.get("opening", {}).get("name", "Unknown")
        if opening not in opening_results:
            opening_results[opening] = {"win": 0, "total": 0}
        opening_results[opening]["total"] += 1
        if result == "win":
            opening_results[opening]["win"] += 1

        analysis  = game.get("analysis", [])
        moves_str = game.get("moves", "").split()

        if not analysis or len(analysis) < 4:
            continue

        games_with_evals += 1

        try:
            board = chess.Board()
            for i, move_str in enumerate(moves_str):
                if i >= len(analysis):
                    break

                move_color = "white" if board.turn == chess.WHITE else "black"

                # analysis[i] = eval AFTER move i was played
                eval_before = analysis[i - 1].get("eval", None) if i > 0 else 0
                eval_after  = analysis[i].get("eval", None)

                if (
                    move_color == color
                    and eval_before is not None
                    and eval_after  is not None
                ):
                    if color == "white":
                        cp_loss = max(0, eval_before - eval_after)
                    else:
                        cp_loss = max(0, eval_after - eval_before)

                    piece_count = len(board.piece_map())
                    move_num    = i // 2 + 1
                    if move_num <= 10:
                        phase = "opening"
                    elif piece_count <= 10:
                        phase = "endgame"
                    else:
                        phase = "middlegame"

                    phase_stats[phase]["total"] += 1
                    phase_stats[phase]["cp_loss"].append(cp_loss)
                    if cp_loss >= 300:
                        phase_stats[phase]["blunders"] += 1

                try:
                    board.push(board.parse_san(move_str))
                except Exception:
                    break

        except Exception:
            continue

    def blunder_rate(p):
        t = phase_stats[p]["total"]
        return phase_stats[p]["blunders"] / t if t > 0 else 0

    def avg_cp(p):
        losses = phase_stats[p]["cp_loss"]
        return sum(losses) / len(losses) if losses else 0

    best_opening = max(
        opening_results.items(),
        key=lambda x: x[1]["win"] / x[1]["total"] if x[1]["total"] >= 3 else 0,
        default=("Unknown", {}),
    )[0]
    worst_opening = min(
        opening_results.items(),
        key=lambda x: x[1]["win"] / x[1]["total"] if x[1]["total"] >= 3 else 1,
        default=("Unknown", {}),
    )[0]

    total_games = sum(results.values())
    overall_wr  = results["win"] / total_games if total_games > 0 else 0
    white_wr    = (
        color_results["white"]["win"] / color_results["white"]["total"]
        if color_results["white"]["total"] > 0 else 0
    )
    black_wr    = (
        color_results["black"]["win"] / color_results["black"]["total"]
        if color_results["black"]["total"] > 0 else 0
    )

    if len(ratings_over_time) >= 4:
        mid   = len(ratings_over_time) // 2
        trend = (
            sum(ratings_over_time[mid:]) / len(ratings_over_time[mid:])
            - sum(ratings_over_time[:mid]) / len(ratings_over_time[:mid])
        ) / 100
    else:
        trend = 0

    avg_rating = (
        sum(ratings_over_time) / len(ratings_over_time)
        if ratings_over_time else 0
    )

    print(
        f"    {username}: {total_games} games, "
        f"{games_with_evals} with evals, "
        f"mid_blunder={blunder_rate('middlegame'):.2%}"
    )

    return {
        "username":                username,
        "rating":                  int(avg_rating),
        "games_analyzed":          total_games,
        "opening_blunder_rate":    round(blunder_rate("opening"),    4),
        "middlegame_blunder_rate": round(blunder_rate("middlegame"), 4),
        "endgame_blunder_rate":    round(blunder_rate("endgame"),    4),
        "avg_cp_loss":             round(
            (avg_cp("opening") + avg_cp("middlegame") + avg_cp("endgame")) / 3, 2
        ),
        "white_win_rate":          round(white_wr,    4),
        "black_win_rate":          round(black_wr,    4),
        "overall_win_rate":        round(overall_wr,  4),
        "best_opening":            best_opening,
        "worst_opening":           worst_opening,
        "trend_slope":             round(trend, 4),
        "source":                  "lichess",
    }

# ── INSERT HELPER ─────────────────────────────────────────
def insert_profile(c, profile, band_label):
    c.execute(
        """
        INSERT OR REPLACE INTO reference_players VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            profile["username"],
            profile["rating"],
            band_label,
            profile["games_analyzed"],
            profile["opening_blunder_rate"],
            profile["middlegame_blunder_rate"],
            profile["endgame_blunder_rate"],
            profile["avg_cp_loss"],
            profile["white_win_rate"],
            profile["black_win_rate"],
            profile["overall_win_rate"],
            profile["best_opening"],
            profile["worst_opening"],
            profile["trend_slope"],
            profile["source"],
        ),
    )

# ── BOOTSTRAP ────────────────────────────────────────────
def bootstrap_band(conn, c, target_low, target_high):
    """
    Bootstrap a band that has no players yet.
    Crawls Lichess TV participants to find opponents
    in the target rating range, inserts initial batch.
    """
    band_label = str(target_high)
    print(f"  Bootstrapping band {target_low}-{target_high} from Lichess TV...")

    tv_players = []
    try:
        r = requests.get(
            "https://lichess.org/api/tv/channels",
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            for channel, data in r.json().items():
                u = data.get("user", {}).get("name", "")
                if u:
                    tv_players.append(u)
    except Exception as e:
        print(f"  TV fetch failed: {e}")
        return

    candidates = set()
    for seed in tv_players[:10]:
        try:
            r = requests.get(
                f"https://lichess.org/api/games/user/{seed}"
                f"?max=100&perfType=rapid&rated=true"
                f"&clocks=false&evals=false",
                headers={**HEADERS, "Accept": "application/x-ndjson"},
                timeout=10
            )
            if r.status_code == 200:
                for line in r.text.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        g = json.loads(line)
                        for side in ["white", "black"]:
                            p      = g.get("players", {}).get(side, {})
                            u      = p.get("user", {}).get("name", "")
                            rating = p.get("rating", 0)
                            if u and target_low <= rating <= target_high:
                                candidates.add(u)
                    except:
                        continue
            time.sleep(0.3)
        except:
            continue

    print(f"  Found {len(candidates)} candidates — inserting initial batch...")

    inserted = 0
    for u in list(candidates)[:15]:
        try:
            games = fetch_lichess_games(u, 15)
            if len(games) < 3:
                continue
            profile = build_profile_from_lichess_games(u, games)
            if not profile:
                continue
            insert_profile(c, profile, band_label)
            conn.commit()
            inserted += 1
        except:
            continue

    print(f"  Bootstrapped {inserted} profiles for band {band_label}")

# ── MAIN ─────────────────────────────────────────────────
def main():
    conn = init_reference_db()
    c    = conn.cursor()

    # user-agnostic — build ALL bands regardless of who is using the system
    print(f"Building reference population for bands: {ALL_BANDS}")
    print("This runs nightly and is shared across all users.\n")

    total_new = 0

    for band in ALL_BANDS:
        low  = band - 200
        high = band

        # check how many profiles exist for this band
        band_count = pd.read_sql(
            "SELECT COUNT(*) as n FROM reference_players WHERE rating_band = ?",
            conn, params=(str(band),)
        )["n"].iloc[0]

        print(f"\n── Band {low}-{high} ({band_count} profiles already) ──")

        # bootstrap if this band is empty
        if band_count == 0:
            bootstrap_band(conn, c, low, high)

        # now expand using DB seeds
        players = fetch_seed_players(low, high, PLAYERS_PER_BAND, conn)
        print(f"  Candidate pool: {len(players)}")

        added_this_band = 0
        for username in tqdm(players, desc=f"Band {band}"):
            c.execute(
                "SELECT username FROM reference_players WHERE username = ?",
                (username,),
            )
            if c.fetchone():
                continue

            try:
                games = fetch_lichess_games(username, GAMES_PER_PLAYER)
                if len(games) < 5:
                    continue

                profile = build_profile_from_lichess_games(username, games)
                if not profile or profile["games_analyzed"] < 5:
                    continue

                insert_profile(c, profile, str(band))
                conn.commit()
                total_new      += 1
                added_this_band += 1

            except Exception as e:
                print(f"    Skipped {username}: {e}")
                continue

            time.sleep(0.3)

        print(f"  Added {added_this_band} new profiles to band {band}")

    print(f"\n✓ Run complete — {total_new} new profiles added")

    summary = pd.read_sql(
        """
        SELECT rating_band,
               COUNT(*)                                   AS players,
               ROUND(AVG(middlegame_blunder_rate)*100, 1) AS avg_mid_blunder_pct,
               ROUND(AVG(overall_win_rate)*100, 1)        AS avg_win_rate
        FROM reference_players
        GROUP BY rating_band
        ORDER BY CAST(rating_band AS INTEGER)
        """,
        conn,
    )
    print("\nFull reference population summary:")
    print(summary.to_string())
    conn.close()


if __name__ == "__main__":
    main()
