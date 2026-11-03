def fee(amount: int) -> int:
    """Simulation fee: 0.015% per side, rounded up to whole KRW; no tax/slippage."""
    return (amount * 15 + 99_999) // 100_000


def reserve(amount: int) -> int:
    return amount + fee(amount)
