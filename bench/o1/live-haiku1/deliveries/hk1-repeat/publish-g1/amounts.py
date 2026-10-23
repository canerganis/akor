"""Exact decimal amounts as integer minor units (hundredths)."""


def parse_amount(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError('invalid amount')
    negative = text.startswith('-')
    body = text[1:] if negative else text
    parts = body.split('.')
    if len(parts) > 2:
        raise ValueError('invalid amount')
    whole = parts[0]
    if not whole.isdigit() or len(whole) > 9 or (whole[0] == '0' and len(whole) > 1):
        raise ValueError('invalid amount')
    cents = '0'
    if len(parts) == 2:
        cents = parts[1]
        if len(cents) < 1 or len(cents) > 2 or not cents.isdigit():
            raise ValueError('invalid amount')
        if len(cents) == 1:
            cents = cents + '0'
    value = int(whole) * 100 + int(cents)
    if negative:
        return -value
    return value


def total_amount(texts):
    total = 0
    for text in texts:
        total += parse_amount(text)
    negative = total < 0
    if negative:
        total = -total
    units, cents = divmod(total, 100)
    sign = '-' if negative else ''
    return sign + str(units) + '.' + str(cents).rjust(2, '0')
