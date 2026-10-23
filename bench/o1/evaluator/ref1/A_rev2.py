"""Reference 1 for ticket A revision 2 (evaluator only)."""


def parse_amount(text):
    if not isinstance(text, str) or not text.isascii() or len(text) == 0:
        raise ValueError('not an amount')
    negative = text.startswith('-')
    body = text[1:] if negative else text
    whole, dot, frac = body.partition('.')
    if dot and (len(frac) < 1 or len(frac) > 3):
        raise ValueError('bad fraction')
    if not whole or not whole.isdigit() or len(whole) > 9 or (len(whole) > 1 and whole[0] == '0'):
        raise ValueError('bad integer part')
    if dot and not frac.isdigit():
        raise ValueError('bad fraction digits')
    units = int(whole) * 1000 + int((frac + '000')[:3])
    return -units if negative else units


def total_amount(texts):
    total = 0
    for text in texts:
        total += parse_amount(text)
    sign = '-' if total < 0 else ''
    whole, frac = divmod(abs(total), 1000)
    return sign + str(whole) + '.' + str(frac).zfill(3)
