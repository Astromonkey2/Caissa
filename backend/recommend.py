import sqlite3
import pandas as pd
import json

DB_PATH = r"C:\Users\abhis\Downloads\Research\Caissa\data\caissa.db"
conn = sqlite3.connect(DB_PATH)

games = pd.read_sql("SELECT * FROM games", conn)
moves = pd.read_sql("SELECT * FROM moves", conn)

recommendations = []

# ── 1. PHASE WEAKNESS ────────────────────────────────────
phase_blunder_rates = {}
for phase in ["opening", "middlegame", "endgame"]:
    phase_moves = moves[moves["game_phase"] == phase]
    if len(phase_moves) > 0:
        rate = (phase_moves["mistake_type"] == "blunder").sum() / len(phase_moves)
        phase_blunder_rates[phase] = round(rate * 100, 1)

worst_phase = max(phase_blunder_rates, key=phase_blunder_rates.get)
recommendations.append({
    "priority": 1,
    "category": "weakness",
    "finding": f"Your {worst_phase} blunder rate is {phase_blunder_rates[worst_phase]}%",
    "action": f"Do 20 {worst_phase} tactics puzzles daily on Lichess"
})

# ── 2. OPENING RECOMMENDATIONS ───────────────────────────
opening_stats = games.groupby(["color", "opening_name"]).agg(
    games=("result", "count"),
    wins=("result", lambda x: (x == "win").sum()),
).reset_index()
opening_stats["win_rate"] = opening_stats["wins"] / opening_stats["games"]
opening_stats = opening_stats[opening_stats["games"] >= 5]

# openings to drop (below 35% win rate)
bad_openings = opening_stats[opening_stats["win_rate"] < 0.35]
for _, row in bad_openings.iterrows():
    recommendations.append({
        "priority": 2,
        "category": "opening_drop",
        "finding": f"As {row['color']}: {row['opening_name']} — {row['win_rate']*100:.0f}% win rate over {row['games']} games",
        "action": f"Stop playing this opening"
    })

# openings to keep (above 55% win rate, enough games)
good_openings = opening_stats[opening_stats["win_rate"] > 0.55]
for _, row in good_openings.iterrows():
    recommendations.append({
        "priority": 3,
        "category": "opening_keep",
        "finding": f"As {row['color']}: {row['opening_name']} — {row['win_rate']*100:.0f}% win rate over {row['games']} games",
        "action": f"Study this opening deeper — it works for you"
    })

# ── 3. RATING TRAJECTORY ─────────────────────────────────
games["date"] = pd.to_datetime(games["date"])
games_sorted = games.sort_values("date")

# split into first half and second half
midpoint = len(games_sorted) // 2
first_half = games_sorted.iloc[:midpoint]
second_half = games_sorted.iloc[midpoint:]

first_win_rate = (first_half["result"] == "win").sum() / len(first_half)
second_win_rate = (second_half["result"] == "win").sum() / len(second_half)

trend = "improving" if second_win_rate > first_win_rate else "declining"
recommendations.append({
    "priority": 4,
    "category": "trend",
    "finding": f"Win rate trend: {first_win_rate*100:.0f}% → {second_win_rate*100:.0f}% ({trend})",
    "action": "Track this monthly — ground truth for whether training is working"
})

# ── 4. COLOR PERFORMANCE ─────────────────────────────────
for color in ["white", "black"]:
    color_games = games[games["color"] == color]
    win_rate = (color_games["result"] == "win").sum() / len(color_games)
    recommendations.append({
        "priority": 5,
        "category": "color",
        "finding": f"As {color}: {win_rate*100:.0f}% win rate over {len(color_games)} games",
        "action": "" 
    })

# ── OUTPUT ───────────────────────────────────────────────
recommendations.sort(key=lambda x: x["priority"])

print("\n═══════════════════════════════════════")
print("         CAISSA RECOMMENDATIONS         ")
print("═══════════════════════════════════════\n")

for r in recommendations:
    print(f"[{r['category'].upper()}]")
    print(f"  Finding: {r['finding']}")
    if r['action']:
        print(f"  Action:  {r['action']}")
    print()

# save to json for later use
with open("data/recommendations.json", "w") as f:
    json.dump(recommendations, f, indent=2)

print("Saved to data/recommendations.json")
conn.close()