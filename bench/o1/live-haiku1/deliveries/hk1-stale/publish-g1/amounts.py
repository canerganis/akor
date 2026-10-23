"""Exact decimal amounts as integer minor units (thousandths)."""


def parse_amount(text):
    if not isinstance(text, str):
        raise ValueError
    if not text.isascii():
        raise ValueError
    sign = 1
    body = text
    if body.startswith('-'):
        sign = -1
        body = body[1:]
    parts = body.split('.')
    if len(parts) > 2:
        raise ValueError
    whole = parts[0]
    if len(whole) == 0 or not whole.isdigit():
        raise ValueError
    if len(whole) > 9 or (len(whole) > 1 and whole[0] == '0'):
        raise ValueError
    fraction = 0
    if len(parts) == 2:
        frac = parts[1]
        if len(frac) == 0 or len(frac) > 3 or not frac.isdigit():
            raise ValueError
        fraction = int(frac) * 10 ** (3 - len(frac))
    amount = int(whole) * 1000 + fraction
    return sign * amount


def total_amount(texts):
    total = 0
    for text in texts:
        total += parse_amount(text)
    if total < 0:
        sign = '-'
        total = -total
    else:
        sign = ''
    units, frac = divmod(total, 1000)
    return sign + str(units) + '.' + str(frac).rjust(3, '0')
