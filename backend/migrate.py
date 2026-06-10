import os
import sqlite3
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sys.path.append(r"C:\Users\abhis\Downloads\Research\Caissa\backend")

SQLITE_PATH = r"C:\Users\abhis\Downloads\Research\Caissa\data\caissa.db"

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

conn = sqlite3.connect(SQLITE_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# ── migrate users ─────────────────────────────────────────
print("Migrating user...")
supabase.table("users").upsert({
    "username":        "Chesspin_one",
    "status":          "ready",
    "rating_current":  375,
    "rating_start":    642,
}).execute()

# ── migrate games ─────────────────────────────────────────
print("Migrating games...")
c.execute("SELECT * FROM games")
games = [dict(r) for r in c.fetchall()]
BATCH = 500
for i in range(0, len(games), BATCH):
    batch = games[i:i+BATCH]
    # add username field
    for g in batch:
        g["username"] = "Chesspin_one"
        g.pop("id", None)
    supabase.table("games").upsert(batch).execute()
    print(f"  Games: {min(i+BATCH, len(games))}/{len(games)}")

# ── migrate moves ─────────────────────────────────────────
print("Migrating moves...")
c.execute("SELECT * FROM moves")
moves = [dict(r) for r in c.fetchall()]
for i in range(0, len(moves), BATCH):
    batch = moves[i:i+BATCH]
    for m in batch:
        m["username"] = "Chesspin_one"
        m.pop("id", None)
    supabase.table("moves").upsert(batch).execute()
    print(f"  Moves: {min(i+BATCH, len(moves))}/{len(moves)}")

# ── migrate reference players ─────────────────────────────
print("Migrating reference players...")
c.execute("SELECT * FROM reference_players")
refs = [dict(r) for r in c.fetchall()]
for i in range(0, len(refs), BATCH):
    batch = refs[i:i+BATCH]
    supabase.table("reference_players").upsert(batch).execute()
    print(f"  Refs: {min(i+BATCH, len(refs))}/{len(refs)}")

conn.close()
print("\n✓ Migration complete")