"""Render the X (Twitter) GIFs into docs/social/: 1200x675, dark terminal palette, one green accent.

Run with any Python that has Pillow (not in .venv):  python docs/social/make_social.py
Writes x_hero.gif, x_packet.gif, x_results.gif, x_reply.gif, x_debate.gif, x_language.gif, x_akor.gif and first/last
frame PNGs into docs/social/preview/. No network, no model calls.
"""
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
W, H = 1200, 675
DT = 0.07          # seconds per animation frame (about 14 fps)
HOLD = 1600        # ms the final frame stays on screen

# Same dark terminal palette as docs/assets/make_demo_gif.py, with green as the single accent.
BG, BAR, TEXT, DIM, ACCENT = '#0d1117', '#161b22', '#e6edf3', '#7d8590', '#3fb950'
LINE_C, BAR_GREY, GHOST_DIM = '#30363d', '#4b535c', '#4a525b'
FONT_PATHS = ['C:/Windows/Fonts/CascadiaMono.ttf', 'C:/Windows/Fonts/consola.ttf',
              '/System/Library/Fonts/Menlo.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
FONT_PATH = next(p for p in FONT_PATHS if Path(p).exists())


@lru_cache(maxsize=None)
def font(size, bold=False):
    f = ImageFont.truetype(FONT_PATH, size)
    if bold:
        try:
            f.set_variation_by_name('Bold')
        except Exception:  # static font without variations
            pass
    return f


def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    """Blend colour a toward b by t in [0, 1]; returns a tuple."""
    t = max(0.0, min(1.0, t))
    ca, cb = rgb(a), rgb(b)
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def fade(color, a):
    """Colour at opacity a over the flat background."""
    return mix(BG, color, a)


def clamp(x):
    return max(0.0, min(1.0, x))


def ease_out(x):
    return 1 - (1 - clamp(x)) ** 3


def ease_io(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def new():
    img = Image.new('RGB', (W, H), BG)
    return img, ImageDraw.Draw(img)


def text(d, xy, s, size, color, bold=False, anchor='ls'):
    d.text(xy, s, fill=color, font=font(size, bold), anchor=anchor)


def centered(d, y, s, size, color, bold=False):
    text(d, (W // 2, y), s, size, color, bold, anchor='ms')


# ---------------------------------------------------------------- 1. hero
def hero(t):
    img, d = new()
    n = round(42 * ease_out((t - 0.3) / 2.0))
    big = font(300, True)
    right = W // 2 + big.getlength('-42%') / 2
    d.text((right, 300), f'-{n}%', fill=ACCENT, font=big, anchor='rs')
    centered(d, 385, 'tokens per verified job', 52, fade(TEXT, ease_out((t - 2.4) / 0.4)))
    centered(d, 465, 'Same jobs. Same answers. Faster.', 52, fade(TEXT, ease_out((t - 2.9) / 0.4)), True)
    a = ease_out((t - 3.4) / 0.4)
    centered(d, 575, 'AKOR · Claude Opus 5.5 · 64 jobs per call', 34, fade(DIM, a))
    centered(d, 620, 'github.com/canerganis/akor', 34, fade(DIM, a))
    return img


def hero_frames():
    return [hero(i * DT) for i in range(int(3.9 / DT) + 1)]


# ---------------------------------------------------------------- 2. packet
STACK_ROWS = [f'{{"id":"e{i}","op":"extract","goal":"read mm","ref":"r0"}}' for i in list(range(1, 19))] \
    + ['...', '{"id":"e63","op":"extract","goal":"read mm","ref":"r0"}',
       '{"id":"e64","op":"extract","goal":"read mm","ref":"r0"}']
RIGHT_LINES = [('"goal":"read mm",', ACCENT), ('"ops":["extract"],', ACCENT), ('"refs":["r0"],', ACCENT),
               ('"jobs":[', DIM), ('  [0,["e1",0],["e2",1],…]', TEXT), (']', DIM)]
ROW_Y0, ROW_DY, RX, LX = 168, 19, 640, 40
RIGHT_Y0, RIGHT_DY = 200, 46


def packet(t):
    img, d = new()
    d.line([(600, 40), (600, 590)], fill=LINE_C, width=2)
    text(d, (LX, 70), 'Plain JSON', 44, TEXT, True)
    text(d, (RX, 70), 'AKOR', 44, ACCENT, True)
    q_done = clamp((t - 3.1) / 0.4)
    text(d, (LX, 118), '3,268 tokens', 36, mix(TEXT, DIM, q_done))
    text(d, (RX, 118), '1,471 tokens', 36, fade(ACCENT, q_done))
    f_row = font(17)
    # left stack: rows appear top to bottom, then dim as the content flows right
    for i, row in enumerate(STACK_ROWS):
        if t < 0.05 + 0.035 * i:
            continue
        flow = clamp((t - 1.2) / 2.2)
        col = mix('#aab2bb', GHOST_DIM, flow)
        d.text((LX, ROW_Y0 + i * ROW_DY), row, fill=col, font=f_row, anchor='ls')
    # ghosts: copies of each row fly right and merge into the index block
    for i, row in enumerate(STACK_ROWS):
        q = ease_io((t - 1.2 - 0.04 * i) / 1.3)
        if q <= 0 or q >= 1:
            continue
        ty = RIGHT_Y0 + (i % len(RIGHT_LINES)) * RIGHT_DY - 12
        x = LX + (RX - LX) * q
        y = (ROW_Y0 + i * ROW_DY) * (1 - q) + ty * q
        d.text((x, y), row, fill=fade(ACCENT, 1 - q * q), font=f_row, anchor='ls')
    # right block: written once, then short index rows
    for j, (line, color) in enumerate(RIGHT_LINES):
        a = clamp((t - (2.5 + 0.15 * j)) / 0.3)
        if a > 0:
            text(d, (RX, RIGHT_Y0 + j * RIGHT_DY), line, 34, fade(color, a))
    a = ease_out((t - 3.7) / 0.5)
    centered(d, 640, 'Write it once. Point to it by index.', 40, fade(ACCENT, a), True)
    return img


def packet_frames():
    return [packet(i * DT) for i in range(int(4.4 / DT) + 1)]


# ---------------------------------------------------------------- 3. results
BAR_X, BAR_MAX = 490, 330


def results_screen(d, title, groups, unit, scale_max, t, deltas, ga):
    text(d, (40, 70), title, 46, fade(TEXT, ga), True)
    for g, (name, base, new_v, delta) in enumerate(groups):
        y0 = 104 + g * 112
        text(d, (40, y0 + 57), name, 34, fade(TEXT, ga), True)
        for k, (tag, v, color, tcol) in enumerate((('Plain JSON', base, BAR_GREY, DIM),
                                                   ('AKOR', new_v, ACCENT, TEXT))):
            top = y0 + k * 48
            start = 0.25 + 0.12 * (g * 2 + k)
            p = ease_out((t - start) / 0.9)
            text(d, (270, top + 33), tag, 34, fade(tcol, ga), k == 1)
            w = max(0, round(BAR_MAX * v / scale_max * p))
            if w:
                d.rectangle([BAR_X, top, BAR_X + w, top + 42], fill=fade(color, ga))
            shown = v * p
            label = f'{shown:.1f}{unit}'
            if p > 0.01:
                text(d, (BAR_X + w + 14, top + 33), label, 34, fade(TEXT if k else DIM, ga))
            if k == 1 and deltas and delta:
                a = ease_out((t - start - 0.8) / 0.4)
                if a > 0:
                    d.text((W - 40, top + 36), delta, fill=fade(ACCENT, a * ga), font=font(48, True), anchor='rs')


def results(t):
    img, d = new()
    s1 = [('Sonnet 5.5', 146.7, 87.0, '-40.7%'), ('Opus 5.5', 144.3, 82.6, '-42.8%'),
          ('Fable 5.1', 146.3, 86.9, '-40.6%'), ('Haiku 5.5', 205.3, 142.1, '-30.8%')]
    s2 = [('Sonnet 5.5', 13.8, 12.5, ''), ('Opus 5.5', 17.9, 14.0, ''), ('Fable 5.1', 23.4, 18.7, ''), ('Haiku 5.5', 21.0, 18.5, '')]
    if t < 3.1:
        ga = 1 - clamp((t - 2.85) / 0.25)
        results_screen(d, 'Tokens per verified job', s1, '', 205.3, t, True, ga)
    else:
        results_screen(d, 'Median seconds per 64-job call', s2, ' s', 23.4, t - 3.1, False, 1.0)
    centered(d, 590, 'Billed tokens, hidden reasoning', 34, fade(DIM, ease_out(t / 0.5)))
    centered(d, 632, 'and failed calls included.', 34, fade(DIM, ease_out(t / 0.5)))
    return img


def results_frames():
    return [results(i * DT) for i in range(int(5.4 / DT) + 1)]


# ---------------------------------------------------------------- 4. reply
REPLY = [('OZ/1g', ACCENT),
         ('{"e1":["12.53 mm","0.01 mm","4","micrometer",\n  "unknown","not_claimed"]}', TEXT),
         ('{"e2":[...]}', TEXT), ('{"v1":"outside"}', TEXT), ('{"v2":"outside"}', TEXT)]
LH, TOP = 54, 142


def reply_schedule():
    times, t = [], 0.4
    for line, _ in REPLY:
        row = []
        for _ch in line.replace('\n', ''):
            t += 1 / 60
            row.append(t)
        times.append(row)
        t += 0.3
    return times, t + 0.1


def reply(t, times, t_check):
    img, d = new()
    d.rectangle([0, 0, W, 60], fill=BAR)
    for i, c in enumerate(('#ff5f57', '#febc2e', '#28c840')):
        d.ellipse([24 + i * 30, 20, 42 + i * 30, 38], fill=c)
    centered(d, 42, 'akor · model reply', 34, DIM)
    y, cursor = TOP, None
    for (line, color), row in zip(REPLY, times):
        nvis = sum(1 for x in row if x <= t)
        if nvis == 0:
            continue
        used = 0
        for full in line.split('\n'):
            chunk = full[:max(0, nvis - used)]
            used += len(full)
            if chunk:
                text(d, (36, y), chunk, 34, color)
                cursor = (36 + font(34).getlength(chunk), y)
            y += LH
    if t >= t_check:
        text(d, (36, y + 36), '✓', 34, ACCENT, True)
        text(d, (36 + 2 * 19.6, y + 36), '91/91 replies accepted on the first try.', 34, ACCENT, True)
        text(d, (36 + 2 * 19.6, y + 36 + 48), 'Nothing repaired.', 34, ACCENT, True)
    elif cursor and int(t * 3) % 2 == 0:
        x, cy = cursor
        d.rectangle([x + 2, cy - 30, x + 17, cy + 4], fill=TEXT)
    return img


def reply_frames():
    times, t_check = reply_schedule()
    n = int((t_check + 0.5) / DT) + 1
    return [reply(i * DT, times, t_check) for i in range(n)]


# ---------------------------------------------------------------- 5. debate
CARDS = ['GPT-6 Astra designs the language', 'Claude Fable reviews and proposes fixes',
         'Claude Opus builds and measures']
CLOSING = [('When a test fails, two models argue from', TEXT), ('the same evidence until they agree.', TEXT),
           ('Every round is public.', ACCENT)]


def debate(t):
    img, d = new()
    for i, label in enumerate(CARDS):
        e = ease_out((t - (-0.3 + 1.0 * i)) / 0.5)
        if e <= 0:
            continue
        x0, y0 = 50 + (1 - e) * 70, 36 + i * 124
        d.rounded_rectangle([x0, y0, x0 + 1100, y0 + 104], radius=14, fill=fade(BAR, e), outline=fade(LINE_C, e), width=2)
        d.rounded_rectangle([x0, y0, x0 + 10, y0 + 104], radius=4, fill=fade(ACCENT, e))
        text(d, (x0 + 55, y0 + 68), str(i + 1), 52, fade(ACCENT, e), True, anchor='ms')
        text(d, (x0 + 110, y0 + 66), label, 40, fade(TEXT, e), i == 0 and False)
    for m, (line, color) in enumerate(CLOSING):
        start = 3.4 + (0.0 if m < 2 else 0.8)
        a = ease_out((t - start) / 0.5)
        text(d, (50, 470 + m * 62), line, 42, fade(color, a), m == 2)
    return img


def debate_frames():
    return [debate(i * DT) for i in range(int(4.9 / DT) + 1)]


# ---------------------------------------------------------------- 6. language
AG_W, AG_H, AG_Y = 200, 130, 335          # agent box size and vertical centre
AG_A, AG_B = 30, W - 30 - 200             # left x of agent A and agent B
LANG_ROWS = STACK_ROWS[:17] + ['...'] + STACK_ROWS[-1:]
AKOR_MSG = [('goal, ops, refs: once', DIM), ('[0,["e1",0],["e2",1]]', TEXT), ('OZ/1g', ACCENT),
            ('{"e1":["12.53 mm","0.01 mm"]}', TEXT), ('{"e2":["12.54 mm","0.02 mm"]}', TEXT)]
AKOR_REQ = [('goal, ops, refs: once', DIM), ('[0,["e1",0],["e2",1],...]', TEXT)]
SCENE = 3.0        # seconds, plain JSON scene
SCENE2 = 3.5       # seconds, AKOR scene (request, then reply)
CARD_IN = 0.5      # seconds for the final card to fade in
CARD_HOLD = 2000   # ms the final card stays on screen


def agents(d, arrive_b, color, arrive_a=0.0):
    for x, name in ((AG_A, 'Agent A'), (AG_B, 'Agent B')):
        edge = mix(LINE_C, color, arrive_b if x == AG_B else arrive_a)
        d.rounded_rectangle([x, AG_Y - AG_H // 2, x + AG_W, AG_Y + AG_H // 2], radius=18, fill=BAR, outline=edge, width=3)
        text(d, (x + AG_W // 2, AG_Y + 12), name, 34, TEXT, True, anchor='ms')


def draw_packet(d, rows, size, lh, pad, left, cy, outline, t0, per, t):
    """Rounded message box with rows typed in from t0; returns its width."""
    f = font(size)
    pw = round(max(f.getlength(r) for r, _ in rows)) + 2 * pad + 6
    ph = lh * (len(rows) - 1) + size + 2 * pad
    top = cy - ph / 2
    d.rounded_rectangle([left, top, left + pw, top + ph], radius=16, fill=BAR, outline=outline, width=3)
    for i, (row, color) in enumerate(rows):
        a = clamp((t - t0 - per * i) / 0.12)
        if a > 0:
            d.text((left + pad, top + pad + i * lh + size * 0.85), row, fill=fade(color, a), font=f, anchor='ls')
    return pw, top


def lang_scene(t, akor):
    """One scene. Plain JSON: one long message A to B. AKOR: short request A to B, then a checked reply B to A."""
    img, d = new()
    d.line([(AG_A + AG_W, AG_Y), (AG_B, AG_Y)], fill=LINE_C, width=3)
    arrive_b = arrive_a = 0.0
    if not akor:
        rows = [(r, '#aab2bb') for r in LANG_ROWS]
        start, travel, count_end, final = 0.15, (1.0, 2.4), 2.4, 3268
        pw = round(max(font(15).getlength(r) for r, _ in rows)) + 42
        x0, x1 = AG_A + 120, AG_B - 10 - pw        # tucked under A at the start, next to B at the end
        left = x0 + (x1 - x0) * ease_io((t - travel[0]) / (travel[1] - travel[0]))
        draw_packet(d, rows, 15, 20, 18, left, AG_Y, GHOST_DIM, start, 0.8 / len(rows), t)
        arrive_b = ease_out((t - travel[1]) / 0.3)
        label, color = 'Plain JSON', TEXT
    else:
        start, travel, count_end, final = 0.1, (0.55, 1.4), 1.4, 1471
        label, color = 'AKOR', ACCENT
        if t < 1.7:        # request A to B
            rows = [AKOR_REQ[0], AKOR_REQ[1]]
            pw = round(max(font(30).getlength(r) for r, _ in rows)) + 58
            x0, x1 = AG_A + 120, AG_B - 10 - pw
            left = x0 + (x1 - x0) * ease_io((t - travel[0]) / (travel[1] - travel[0]))
            draw_packet(d, rows, 30, 44, 26, left, AG_Y, ACCENT, start, 0.3, t)
            arrive_b = ease_out((t - travel[1]) / 0.3)
        else:              # checked reply B to A
            r0, r1 = 1.7, (1.9, 2.8)
            rows = AKOR_MSG[2:]
            pw = round(max(font(30).getlength(r) for r, _ in rows)) + 58
            x0, x1 = AG_B + 80 - pw, AG_A + AG_W + 10
            left = x0 + (x1 - x0) * ease_io((t - r1[0]) / (r1[1] - r1[0]))
            _, top = draw_packet(d, rows, 30, 44, 26, left, AG_Y, ACCENT, r0, 0.15, t)
            text(d, (left + pw / 2, top - 16), 'checked reply', 34, fade(ACCENT, ease_out((t - r0) / 0.3)), True, anchor='ms')
            arrive_a = ease_out((t - r1[1]) / 0.3)
    agents(d, arrive_b, color, arrive_a)
    text(d, (W // 2, 78), label, 52, color, True, anchor='ms')
    n = round(final * ease_io((t - start) / (count_end - start)))
    cf = font(56, True)
    cx = W // 2 - cf.getlength(f'{final:,} tokens') / 2
    if akor:
        old = font(44)
        w_old = old.getlength('3,268')
        cx -= (w_old + 36) / 2
        a = ease_out((t - count_end) / 0.3)
        if a > 0:
            d.text((cx, 625), '3,268', fill=fade(DIM, a), font=old, anchor='ls')
            d.line([(cx - 6, 607), (cx + w_old + 6, 607)], fill=fade(DIM, a), width=3)
        cx += w_old + 36
    d.text((cx, 625), f'{n:,} tokens', fill=ACCENT if akor else TEXT, font=cf, anchor='ls')
    return img


def lang_card(t):
    img, d = new()
    a = lambda s: ease_out((t - s) / 0.35)
    centered(d, 160, 'A compact language', 76, fade(TEXT, a(0.0)), True)
    centered(d, 250, 'for AI agents', 76, fade(TEXT, a(0.0)), True)
    centered(d, 356, '-55% tokens per packet', 46, fade(ACCENT, a(0.1)), True)
    centered(d, 418, '~40% fewer billed tokens per job', 46, fade(ACCENT, a(0.2)), True)
    centered(d, 480, 'faster replies', 46, fade(ACCENT, a(0.3)), True)
    centered(d, 626, 'github.com/canerganis/akor', 34, fade(DIM, a(0.4)))
    return img


def language_frames():
    n = int(SCENE / DT)
    return ([lang_scene(i * DT, False) for i in range(n)] + [lang_scene(i * DT, True) for i in range(int(SCENE2 / DT))]
            + [lang_card(i * DT) for i in range(int(CARD_IN / DT) + 1)])


# ---------------------------------------------------------------- 7. one call (pilot, 64 jobs, Sonnet 5.5, 3 seeds)
PER_JOB, ONE_CALL = 2834, 91.6     # tokens per verified job: one plain JSON call per job vs one AKOR call
N_CALLS = 64
CALL_EVERY, CALL_TRAVEL = 0.036, 0.6
DOC_W, DOC_H = 34, 46              # one small call packet


def doc(d, x, y, color):
    """A small call packet (prompt plus one job) centred at x, y."""
    d.rounded_rectangle([x - DOC_W / 2, y - DOC_H / 2, x + DOC_W / 2, y + DOC_H / 2], radius=6, fill=BAR,
                        outline=color, width=2)
    for k in range(4):
        yy = y - DOC_H / 2 + 10 + k * 8
        d.line([(x - DOC_W / 2 + 7, yy), (x + DOC_W / 2 - (7 if k < 3 else 15), yy)], fill=color, width=2)


def tokens_counter(d, t, start, end, final, color, strike=None):
    """Bottom counter in the x_language style; decimals only once the count has finished."""
    k = ease_io((t - start) / (end - start))
    shown = f'{final:,} tokens' if k >= 1 else f'{round(final * k):,} tokens'
    cf = font(56, True)
    cx = W // 2 - cf.getlength(f'{final:,} tokens') / 2
    if strike:
        old = font(44)
        w_old = old.getlength(f'{strike:,}')
        cx -= (w_old + 36) / 2
        a = ease_out((t - end) / 0.3)
        if a > 0:
            d.text((cx, 612), f'{strike:,}', fill=fade(DIM, a), font=old, anchor='ls')
            d.line([(cx - 6, 594), (cx + w_old + 6, 594)], fill=fade(DIM, a), width=3)
        cx += w_old + 36
    d.text((cx, 612), shown, fill=color, font=cf, anchor='ls')
    centered(d, 652, 'per verified job', 26, DIM)


def calls_scene(t, akor):
    """Scene 1: agent A sends the 64 jobs as 64 calls, each with its own prompt. Scene 2: one AKOR call with
    shared parts written once, then one checked reply."""
    img, d = new()
    d.line([(AG_A + AG_W, AG_Y), (AG_B, AG_Y)], fill=LINE_C, width=3)
    arrive_b = arrive_a = 0.0
    if not akor:
        x0, x1 = AG_A + AG_W + DOC_W, AG_B - DOC_W
        sent = 0
        for i in range(N_CALLS):
            s = 0.15 + CALL_EVERY * i
            if t < s:
                break
            sent = i + 1
            k = (t - s) / CALL_TRAVEL
            if k < 1:
                doc(d, x0 + (x1 - x0) * k, AG_Y + (6 if i % 2 else -6), '#aab2bb')
            else:
                arrive_b = 1.0
        text(d, (W // 2, 78), 'One call per job', 52, TEXT, True, anchor='ms')
        text(d, (W // 2, 470), 'each call resends the prompt', 30, DIM, anchor='ms')
        text(d, (W // 2, 530), f'{sent} call' + ('' if sent == 1 else 's'), 38, TEXT, True, anchor='ms')
        tokens_counter(d, t, 0.15, 2.6, PER_JOB, TEXT)
    else:
        if t < 1.7:        # one request A to B, shared parts once
            rows = [AKOR_REQ[0], AKOR_REQ[1]]
            pw = round(max(font(30).getlength(r) for r, _ in rows)) + 58
            x0, x1 = AG_A + 120, AG_B - 10 - pw
            left = x0 + (x1 - x0) * ease_io((t - 0.55) / 0.85)
            _, top = draw_packet(d, rows, 30, 44, 26, left, AG_Y, ACCENT, 0.1, 0.3, t)
            text(d, (left + pw / 2, top - 16), '64 jobs, one call', 34, fade(ACCENT, ease_out((t - 0.1) / 0.3)), True,
                 anchor='ms')
            arrive_b = ease_out((t - 1.4) / 0.3)
        else:              # checked reply B to A
            rows = AKOR_MSG[2:]
            pw = round(max(font(30).getlength(r) for r, _ in rows)) + 58
            x0, x1 = AG_B + 80 - pw, AG_A + AG_W + 10
            left = x0 + (x1 - x0) * ease_io((t - 1.9) / 0.9)
            _, top = draw_packet(d, rows, 30, 44, 26, left, AG_Y, ACCENT, 1.7, 0.15, t)
            text(d, (left + pw / 2, top - 16), 'checked reply', 34, fade(ACCENT, ease_out((t - 1.7) / 0.3)), True,
                 anchor='ms')
            arrive_a = ease_out((t - 2.8) / 0.3)
        text(d, (W // 2, 78), 'One AKOR call', 52, ACCENT, True, anchor='ms')
        text(d, (W // 2, 530), '1 call, every answer checked', 38, fade(ACCENT, ease_out((t - 2.8) / 0.3)), True,
             anchor='ms')
        tokens_counter(d, t, 0.1, 1.4, ONE_CALL, ACCENT, strike=PER_JOB)
    agents(d, arrive_b, ACCENT if akor else TEXT, arrive_a)
    return img


def calls_card(t):
    img, d = new()
    a = lambda s: ease_out((t - s) / 0.35)
    centered(d, 160, 'Many agent jobs,', 76, fade(TEXT, a(0.0)), True)
    centered(d, 250, 'one checked call', 76, fade(TEXT, a(0.0)), True)
    centered(d, 356, '31x fewer tokens than one call per job', 44, fade(ACCENT, a(0.1)), True)
    centered(d, 418, 'shared parts written once', 44, fade(ACCENT, a(0.2)), True)
    centered(d, 480, 'every answer checked', 44, fade(ACCENT, a(0.3)), True)
    centered(d, 550, 'Claude Sonnet 5.5, 64 jobs, 3 seeds, billed tokens', 28, fade(DIM, a(0.35)))
    centered(d, 626, 'github.com/canerganis/akor', 34, fade(DIM, a(0.4)))
    return img


def calls_frames():
    return ([calls_scene(i * DT, False) for i in range(int(SCENE / DT))]
            + [calls_scene(i * DT, True) for i in range(int(SCENE2 / DT))]
            + [calls_card(i * DT) for i in range(int(CARD_IN / DT) + 1)])


# ---------------------------------------------------------------- output
def save_gif(name, frames, colors, hold=HOLD):
    sample = frames[::4] + [frames[-1]]
    mosaic = Image.new('RGB', (W, H * len(sample)))
    for i, f in enumerate(sample):
        mosaic.paste(f, (0, i * H))
    pal = mosaic.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    durations = [round(DT * 1000)] * len(q)
    durations[-1] = hold
    path = OUT / name
    q[0].save(path, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True)
    secs = sum(durations) / 1000
    print(f'{name}: {len(q)} frames, {secs:.1f} s, {path.stat().st_size / 1e6:.2f} MB, {colors} colours')
    prev = OUT / 'preview'
    prev.mkdir(exist_ok=True)
    with Image.open(path) as im:
        im.seek(0)
        im.convert('RGB').save(prev / f'{path.stem}_first.png')
        im.seek(im.n_frames - 1)
        im.convert('RGB').save(prev / f'{path.stem}_last.png')


if __name__ == '__main__':
    save_gif('x_hero.gif', hero_frames(), 32)
    save_gif('x_packet.gif', packet_frames(), 40)
    save_gif('x_results.gif', results_frames(), 32)
    save_gif('x_reply.gif', reply_frames(), 24)
    save_gif('x_debate.gif', debate_frames(), 32)
    save_gif('x_language.gif', language_frames(), 32, hold=CARD_HOLD)
    save_gif('x_akor.gif', calls_frames(), 32, hold=CARD_HOLD)
    for stem in ('x_language', 'x_akor'):
        with Image.open(OUT / f'{stem}.gif') as im:
            for secs, tag in ((SCENE * 0.8, 'scene1_arrive'), (SCENE + 1.5, 'request'), (SCENE + 2.5, 'reply')):
                at = 0.0   # frames with equal pixels are merged on save, so find the frame by elapsed time
                for k in range(im.n_frames):
                    im.seek(k)
                    at += im.info['duration'] / 1000
                    if at > secs:
                        break
                im.convert('RGB').save(OUT / 'preview' / f'{stem}_{tag}.png')
