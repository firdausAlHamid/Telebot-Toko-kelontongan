"""Test script untuk horizontal bar visualization"""

def generate_stock_bar(stock: int, min_stock: int, max_width: int = 20) -> str:
    """Generate horizontal bar chart for stock visualization."""
    if stock == 0:
        return "-" * max_width + " [HABIS]"

    # Calculate bar width based on min_stock threshold
    threshold = max(min_stock, 10)
    percentage = min(stock / (threshold * 3), 1.0)  # 3x min_stock = 100%
    filled = int(percentage * max_width)
    empty = max_width - filled

    # Color indicators
    if stock <= min_stock:
        icon = "[RED]"  # Critical
    elif stock <= min_stock * 2:
        icon = "[YEL]"  # Warning
    else:
        icon = "[GRN]"  # Good

    bar = "#" * filled + "-" * empty
    return f"{bar} {icon} {stock}"


if __name__ == "__main__":
    print("="*60)
    print("HORIZONTAL STOCK BAR VISUALIZATION TEST")
    print("="*60)
    print()

    test_cases = [
        (0, 10, "HABIS - No stock"),
        (5, 10, "CRITICAL - Below minimum"),
        (10, 10, "CRITICAL - At minimum"),
        (15, 10, "WARNING - Between min and 2x min"),
        (25, 10, "GOOD - Above 2x minimum"),
        (50, 10, "GOOD - Well stocked"),
        (100, 10, "EXCELLENT - Overstocked"),
    ]

    for stock, min_stock, label in test_cases:
        bar = generate_stock_bar(stock, min_stock, 20)
        print(f"{label}")
        print(f"  Stock: {stock:3d} | Min: {min_stock:2d}")
        print(f"  {bar}")
        print()
