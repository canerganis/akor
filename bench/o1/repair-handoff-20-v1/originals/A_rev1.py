"""Exact decimal amounts as integer minor units (hundredths)."""


def parse_amount(text):
    """Return the amount in minor units, for example "12.30" -> 1230."""
    value = round(float(text), 2)
    return int(value * 100)


def total_amount(texts):
    """Return the exact sum of the amounts as fixed-precision text."""
    total = 0
    for text in texts:
        total += parse_amount(text)
    units, cents = divmod(total, 100)
    return '%d.%02d' % (units, cents)
