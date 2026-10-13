"""Render docs/assets/demo.gif: a terminal session replaying real CLI output (trimmed with "…").

Run with any Python that has Pillow (not in .venv):  python docs/assets/make_demo_gif.py
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
    ('oz init team --goal "Review the patch" --kind patch --source fix.diff --procedure checks.txt', [
        ('dim', '{ "workspace": "team", "channels": ["worker", "reviewer"], "adapter_executed": false }'),
    ]),
    ('oz send V --id review --workspace team', [
        ('dim', '{ "id": "review", "inserted": true, "kind": "work" }'),
        ('note', '# V = read + audit + test; read and test run on the host'),
    ]),
    ('oz plan --show-prompt --workspace team', [
        ('dim', '{ "ids": ["review"], "mode": "named", "input_tokens": [464], …'),
        ('dim', '  "system": "You execute OZ/1g. … Reply with the line OZ/1g, then one compact JSON'),
        ('dim', '             record per job on its own line. … Any malformed nonblank line … rejects'),
        ('dim', '             the whole reply. Stop after the last job.",'),
        ('dim', '  "prompt": {'),
        ('json', '    "v": "1g", "goal": "Review the patch",'),
        ('json', '    "ops":  ["Review the supplied patch for defects …"],'),
        ('json', '    "refs": ["--- a/retry.py … +TIMEOUT = 30"],'),
        ('key',  '    "jobs": [[0, ["review", 0]]]'),
        ('dim', '  } }'),
        ('note', '# goal, ops and refs written once; jobs point at them by index'),
    ]),
    ('oz demo ./demo', [
        ('dim', '{ "actual_model_calls": 0, "reviewer_initially_waited": true,'),
        ('dim', '  "worker":   { "wire": "stage-1g", "mode": "named", "adapter_calls": 1,'),
        ('dim', '                "outcomes": { "read": "ok", "propose": "ok" } },'),
        ('dim', '  "reviewer": { "mode": "host", "adapter_calls": 0, "outcomes": { "review": "ok" } },'),
        ('dim', '  "states": { "done": 4 } }'),
        ('note', '# one stdio adapter call for the whole batch; no model was called'),
    ]),
    ('oz status --workspace ./demo', [
        ('ok', 'Status: done=4'),
        ('dim', 'ID       Channel   State  Attempts  Waiting for'),
        ('text', 'read     worker    done   1/2       -'),
        ('text', 'propose  worker    done   1/2       -'),
        ('text', 'review   reviewer  done   1/2       -'),
        ('text', 'notice   worker    done   1/2       -'),
    ]),
]
COLOURS = {'dim': DIM, 'json': TEXT, 'key': BLUE, 'note': AMBER, 'ok': GREEN, 'text': TEXT}


def frame(lines, cursor=None):
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 40], fill=BAR)
    for i, c in enumerate(('#ff5f57', '#febc2e', '#28c840')):
        d.ellipse([18 + i * 22, 14, 30 + i * 22, 26], fill=c)
    d.text((W // 2, 20), 'akor  ·  OZ/1g worker protocol', fill=DIM, font=FONT, anchor='mm')
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
