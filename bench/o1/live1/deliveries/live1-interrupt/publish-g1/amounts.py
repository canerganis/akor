"""Exact decimal amounts as integer minor units (hundredths)."""


def parse_amount(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError('bad amount')
    s = text
    neg = s.startswith('-')
    if neg:
        s = s[1:]
    ip, dot, fp = s.partition('.')
    if not ip or not ip.isdecimal() or len(ip) > 9:
        raise ValueError('bad amount')
    if len(ip) > 1 and ip[0] == '0':
        raise ValueError('bad amount')
    if dot:
        if not fp or not fp.isdecimal() or len(fp) > 2:
            raise ValueError('bad amount')
    value = int(ip) * 100
    if fp:
        value += int(fp.ljust(2, '0'))
    return -value if neg else value


def total_amount(texts):
    total = 0
    for t in texts:
        total += parse_amount(t)
    sign = '-' if total < 0 else ''
    units, cents = divmod(abs(total), 100)
    return sign + str(units) + '.' + str(cents).zfill(2)
