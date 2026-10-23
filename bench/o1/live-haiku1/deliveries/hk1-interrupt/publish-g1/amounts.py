"""Exact decimal amounts as integer minor units (hundredths)."""


def parse_amount(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError('invalid amount')
    sign = 1
    body = text
    if body.startswith('-'):
        sign = -1
        body = body[1:]
    whole, dot, frac = body.partition('.')
    if not whole.isdigit() or len(whole) > 9:
        raise ValueError('invalid amount')
    if whole != '0' and whole.startswith('0'):
        raise ValueError('invalid amount')
    if dot and (not frac.isdigit() or len(frac) > 2):
        raise ValueError('invalid amount')
    cents = int((frac + '00')[:2])
    return sign * (int(whole) * 100 + cents)


def total_amount(texts):
    total = 0
    for text in texts:
        total += parse_amount(text)
    if total < 0:
        prefix = '-'
        total = -total
    else:
        prefix = ''
    units, cents = divmod(total, 100)
    return prefix + str(units) + '.' + str(cents).rjust(2, '0')
