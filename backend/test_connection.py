import os
import sys
sys.path.append(r"C:\Users\abhis\Downloads\Research\Caissa\backend")
from dotenv import load_dotenv
load_dotenv(r"C:\Users\abhis\Downloads\Research\Caissa\.env")
from supabase import create_client

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

print(f"URL: {url}")
print(f"KEY: {key[:20]}...")

supabase = create_client(url, key)

# test insert and read
result = supabase.table("users").select("*").execute()
print(f"Users table: {result.data}")
print("Connection working!")