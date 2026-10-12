"""Render docs/assets/demo.gif: a terminal session replaying real CLI output (trimmed with "…").

Run with any Python that has Pillow:  python docs/assets/make_demo_gif.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, PAD, LINE = 1000, 600, 28, 23
BG, BAR, TEXT, DIM, GREEN, BLUE, AMBER, PROMPT = ('#0d1117', '#161b22', '#e6edf3', '#7d8590', '#3fb950',
                                                  '#79c0ff', '#d29922', '#a5d6ff')
FONT_PATHS = ['C:/Windows/Fonts/CascadiaMono.ttf', 'C:/Windows/Fonts/consola.ttf',
              '/System/Library/Fonts/Menlo.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
FONT = next(ImageFont.truetype(p, 15) for p in FONT_PATHS if Path(p).exists())
BOLD = FONT

# Each scene: a command typed at the prompt, then output lines with a colour tag.
SCENES = [
    ('oz init team --kind patch --source fix.diff --procedure checks.txt', [
        ('dim', '{ "workspace": "team", "channels": ["worker", "reviewer"], "adapter_executed": false }'),
    ]),
    ('oz send V --id review --workspace team', [
        ('dim', '{ "id": "review", "inserted": true, "kind": "work" }'),
        ('note', '# V = read + audit + test; read and test run on the host'),
    ]),
    ('oz plan --show-prompt --workspace team', [
        ('dim', '{ "mode": "named", "input_tokens": [400], …'),
        ('dim', '  "prompt": {'),
        ('json', '    "goal": "Review the timeout patch; keep the public API.",'),
        ('json', '    "d": { "audit": "Review the supplied patch for defects …" },'),
        ('json', '    "c": { "0": { "input": "--- a/retry.py … TIMEOUT = 5" } },'),
        ('key',  '    "j": ["audit 0"]'),
        ('dim', '  } }'),
        ('note', '# 3 steps requested, 1 job reaches the model'),
    ]),
    ('oz demo ./demo', [
        ('dim', '{ "actual_model_calls": 0, "reviewer_initially_waited": true,'),
        ('dim', '  "worker":   { "mode": "named", "reply_mode": "jsonl", "outcomes": { "read": "ok", "propose": "ok" } },'),
        ('dim', '  "reviewer": { "mode": "host", "adapter_calls": 0, … } }'),
    ]),
    ('oz status --workspace ./demo', [
        ('ok', 'Durum: done=4'),
        ('dim', 'ID       Kanal     Durum  Deneme  Beklediği'),
        ('text', 'read     worker    done   1/2     -'),
        ('text', 'propose  worker    done   1/2     -'),
        ('text', 'review   reviewer  done   1/2     -'),
        ('text', 'notice   worker    done   1/2     -'),
    ]),
]
COLOURS = {'dim': DIM, 'json': TEXT, 'key': BLUE, 'note': AMBER, 'ok': GREEN, 'text': TEXT}


def frame(lines, cursor=None):
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 40], fill=BAR)
    for i, c in enumerate(('#ff5f57', '#febc2e', '#28c840')):
        d.ellipse([18 + i * 22, 14, 30 + i * 22, 26], fill=c)
    d.text((W // 2, 20), 'akor  ·  ÖZ worker protocol', fill=DIM, font=FONT, anchor='mm')
    visible = lines[-((H - 60) // LINE):]
    y = 56
    for kind, text in visible:
        if kind == 'cmd':
            d.text((PAD, y), '$', fill=GREEN, font=BOLD)
            d.text((PAD + 18, y), text, fill=PROMPT, font=FONT)
        else:
            d.text((PAD, y), text, fill=COLOURS[kind], font=FONT)
        y += LINE
    if cursor is not None:
        x = PAD + 18 + int(FONT.getlength(cursor))
        d.rectangle([x + 1, y - LINE + 3, x + 9, y - 3], fill=TEXT)
    return img


def build():
    frames, durations, lines = [], [], []
    for command, output in SCENES:
        for k in range(0, len(command) + 1, 3):
            typed = command[:k]
            frames.append(frame(lines + [('cmd', typed)], cursor=typed))
            durations.append(45)
        lines.append(('cmd', command))
        frames.append(frame(lines))
        durations.append(350)
        for item in output:
            lines.append(item)
            frames.append(frame(lines))
            durations.append(120)
        durations[-1] = 1700
        lines.append(('dim', ''))
    durations[-1] = 3500
    palette = frames[-1].quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    out = Path(__file__).with_name('demo.gif')
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(out, len(frames), 'frames', out.stat().st_size // 1024, 'KiB')


if __name__ == '__main__':
    build()
