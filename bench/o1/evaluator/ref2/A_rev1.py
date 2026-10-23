"""Reference 2 for ticket A revision 1 (evaluator only), written apart from reference 1."""


def parse_amount(text):
    if not isinstance(text, str):
        raise ValueError('amount must be text')
    digits = '0123456789'
    i = 0
    sign = 1
    if text[:1] == '-':
        sign = -1
        i = 1
    start = i
    while i < len(text) and text[i] in digits:
        i += 1
    whole = text[start:i]
    if whole == '' or len(whole) > 9 or (whole[0] == '0' and len(whole) > 1):
        raise ValueError('bad integer part')
    frac = ''
    if i < len(text):
        if text[i] != '.':
            raise ValueError('unexpected character')
        j = i + 1
        while j < len(text) and text[j] in digits:
            j += 1
        frac = text[i + 1:j]
        if j != len(text) or not 1 <= len(frac) <= 2:
            raise ValueError('bad fraction')
    value = 0
    for ch in whole + frac + '0' * (2 - len(frac)):
        value = value * 10 + digits.index(ch)
    return sign * value


def total_amount(texts):
    total = sum([parse_amount(text) for text in texts])
    magnitude = -total if total < 0 else total
    text = str(magnitude).rjust(3, '0')
    out = text[:-2] + '.' + text[-2:]
    return ('-' + out) if total < 0 else out
