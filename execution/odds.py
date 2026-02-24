def american_to_implied_probability(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def poly_price_to_american(price: float) -> int:
    """Convert Polymarket probability (0-1) to American odds."""
    if price <= 0 or price >= 1:
        return -110  # fallback for invalid input
    if price == 0.5:
        return 100
    if price > 0.5:
        return -round(price / (1 - price) * 100)
    return round((1 - price) / price * 100)


def format_price_comparison(odds_price: int, poly_price: float) -> str:
    our_prob = american_to_implied_probability(odds_price) * 100
    poly_prob = poly_price * 100
    delta = our_prob - poly_prob
    sign = "+" if delta >= 0 else ""
    return f"Our implied: {our_prob:.1f}% | Polymarket: {poly_prob:.1f}% | delta: {sign}{delta:.1f}pp"
