from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    username        = Column(String, primary_key=True)
    joined_date     = Column(DateTime, server_default=func.now())
    last_sync       = Column(DateTime, nullable=True)
    rating_current  = Column(Integer, nullable=True)
    rating_start    = Column(Integer, nullable=True)
    status          = Column(String, default="pending")  # pending/analyzing/ready

class Game(Base):
    __tablename__ = "games"
    game_id         = Column(String, primary_key=True)
    username        = Column(String, ForeignKey("users.username"))
    date            = Column(String)
    time_class      = Column(String)
    color           = Column(String)
    opponent_rating = Column(Integer)
    your_rating     = Column(Integer)
    result          = Column(String)
    opening_name    = Column(String)
    opening_eco     = Column(String)
    pgn             = Column(Text)

class Move(Base):
    __tablename__ = "moves"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    game_id         = Column(String, ForeignKey("games.game_id"))
    username        = Column(String)
    move_number     = Column(Integer)
    color           = Column(String)
    move            = Column(String)
    best_move       = Column(String, nullable=True)
    eval_before     = Column(Float, nullable=True)
    eval_after      = Column(Float, nullable=True)
    centipawn_loss  = Column(Float, nullable=True)
    mistake_type    = Column(String, nullable=True)
    game_phase      = Column(String, nullable=True)

class ReferencePlayer(Base):
    __tablename__ = "reference_players"
    username                = Column(String, primary_key=True)
    rating                  = Column(Integer)
    rating_band             = Column(String)
    games_analyzed          = Column(Integer)
    opening_blunder_rate    = Column(Float)
    middlegame_blunder_rate = Column(Float)
    endgame_blunder_rate    = Column(Float)
    avg_cp_loss             = Column(Float)
    white_win_rate          = Column(Float)
    black_win_rate          = Column(Float)
    overall_win_rate        = Column(Float)
    best_opening            = Column(String)
    worst_opening           = Column(String)
    trend_slope             = Column(Float)
    source                  = Column(String)

class Report(Base):
    __tablename__ = "reports"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String, ForeignKey("users.username"))
    created_at      = Column(DateTime, server_default=func.now())
    weakness_phase  = Column(String)
    blunder_rate    = Column(Float)
    recommendations = Column(Text)  # JSON string
    resources       = Column(Text)  # JSON string from agents