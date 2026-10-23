"""Exact decimal amounts as integer minor units (thousandths)."""


def parse_amount(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError("invalid amount")
    s = text
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    ip, sep, fp = s.partition(".")
    if not ip.isdigit() or len(ip) > 9:
        raise ValueError("invalid amount")
    if len(ip) > 1 and ip.startswith("0"):
        raise ValueError("invalid amount")
    if sep:
        if not fp.isdigit() or len(fp) > 3:
            raise ValueError("invalid amount")
    fp = fp.ljust(3, "0")
    v = int(ip) * 1000 + int(fp)
    if neg:
        return -v
    return v


def total_amount(texts):
    total = 0
    for text in texts:
        total += parse_amount(text)
    units, frac = divmod(abs(total), 1000)
    out = str(units) + "." + str(frac).zfill(3)
    if total < 0:
        out = "-" + out
    return out
