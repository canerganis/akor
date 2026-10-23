"""Fixture answers for ticket A revision 1: a third valid implementation the zero-token adapter returns."""


def parse_amount(text):
    if not isinstance(text, str) or text == '' or not text.isascii():
        raise ValueError('invalid amount')
    negative = text[0] == '-'
    rest = text[1:] if negative else text
    parts = rest.split('.')
    if len(parts) > 2:
        raise ValueError('invalid amount')
    whole = parts[0]
    frac = parts[1] if len(parts) == 2 else ''
    if not whole.isdigit() or len(whole) > 9 or (whole.startswith('0') and whole != '0'):
        raise ValueError('invalid amount')
    if len(parts) == 2 and (not frac.isdigit() or len(frac) > 2):
        raise ValueError('invalid amount')
    value = int(whole + frac.ljust(2, '0'))
    return -value if negative else value


def total_amount(texts):
    total = 0
    for item in texts:
        total = total + parse_amount(item)
    digits = str(abs(total)).zfill(3)
    result = digits[:-2] + '.' + digits[-2:]
    if total < 0:
        result = '-' + result
    return result
