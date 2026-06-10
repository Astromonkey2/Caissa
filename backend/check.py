import os, json
from dotenv import load_dotenv
load_dotenv(r"C:\Users\abhis\Downloads\Research\Caissa\.env")
from supabase import create_client

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
r = sb.table("reports").select("patterns").eq("username", "Chesspin_one").order("created_at", desc=True).limit(1).execute()
patterns = json.loads(r.data[0]["patterns"])
for p in patterns:
    print("Label:", p["tactic_label"])
    print("FEN:", p["example"].get("fen"))
    print("Move:", p["example"].get("move_played"))
    print()