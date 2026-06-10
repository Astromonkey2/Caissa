# Based on ChessDojo 2024 Universal Rating Converter
# Chess.com Rapid to  Lichess Rapid equivalents
# Source: NoseKnowsAll September 2024 study, 28,000+ verified players

CHESSCOM_TO_LICHESS_RAPID = [
    # (chesscom_max, lichess_equivalent, confidence_range)
    (300,  700,  200),
    (400,  800,  200),
    (500,  900,  200),
    (600,  1000, 200),
    (700,  1100, 175),
    (800,  1175, 175),
    (900,  1275, 175),
    (1000, 1350, 150),
    (1100, 1450, 150),
    (1200, 1525, 150),
    (1300, 1600, 125),
    (1400, 1675, 125),
    (1500, 1750, 125),
    (1600, 1825, 100),
    (1700, 1900, 100),
    (1800, 1975, 100),
    (1900, 2050, 100),
    (2000, 2125, 100),
    (2100, 2200, 100),
    (2200, 2275, 100),
]

def chesscom_to_lichess(chesscom_rating):
    """
    Convert Chess.com rapid rating to approximate Lichess rapid equivalent.
    Returns (lichess_estimate, confidence_range, band_low, band_high)
    """
    for i, (cc_max, lichess_est, confidence) in enumerate(CHESSCOM_TO_LICHESS_RAPID):
        if chesscom_rating <= cc_max:
            band_low  = lichess_est - confidence
            band_high = lichess_est + confidence
            return lichess_est, confidence, band_low, band_high
    
    # above 2200 Chess.com
    lichess_est = int(chesscom_rating * 1.03 + 50)
    return lichess_est, 100, lichess_est - 100, lichess_est + 100

def get_lichess_query_band(chesscom_rating):
    """
    Returns the Lichess rating bands to query for
    collaborative filtering against this Chess.com player.
    Uses a wider band to account for conversion uncertainty.
    """
    lichess_est, confidence, low, high = chesscom_to_lichess(chesscom_rating)
    
    # snap to Lichess explorer supported bands
    # Lichess explorer accepts: 400, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500
    LICHESS_BANDS = [400, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500]
    
    # find which bands overlap with our confidence range
    relevant_bands = []
    for band in LICHESS_BANDS:
        if low <= band <= high:
            relevant_bands.append(band)
    
    # always include the closest band even if no overlap
    if not relevant_bands:
        closest = min(LICHESS_BANDS, key=lambda x: abs(x - lichess_est))
        relevant_bands = [closest]
    
    return relevant_bands, lichess_est, confidence

# ── TEST ──────────────────────────────────────────────────
if __name__ == "__main__":
    test_ratings = [375, 500, 750, 1000, 1200, 1500]
    
    print("Chess.com → Lichess conversion (rapid)")
    print("─" * 55)
    print(f"{'Chess.com':>10} │ {'Lichess est':>12} │ {'Range':>20} │ Query bands")
    print("─" * 55)
    
    for cc in test_ratings:
        est, conf, low, high = chesscom_to_lichess(cc)
        bands, _, _ = get_lichess_query_band(cc)
        print(f"{cc:>10} │ {est:>12} │ {low:>8} - {high:<8} │ {bands}")