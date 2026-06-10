import sys
sys.path.append(r"C:\Users\abhis\Downloads\Research\Caissa\backend")

from database import engine, Base
import models  # noqa — registers all models

def init():
    print("Creating tables in Supabase...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

if __name__ == "__main__":
    init()