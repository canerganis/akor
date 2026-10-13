"""Join the X GIFs into one short MP4 (1280x720, H.264, crossfades) with a closing card.

Run with the system python (Pillow) from this folder; needs ffmpeg on PATH:
    python make_video.py      -> akor.mp4
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from make_social import ACCENT, BG, DIM, TEXT, font

HERE = Path(__file__).parent
CLIPS = ['x_hero', 'x_packet', 'x_results', 'x_reply', 'x_debate']
FADE = 0.5
CARD_SECONDS = 3.0


def card(path):
    im = Image.new('RGB', (1200, 675), BG)
    d = ImageDraw.Draw(im)

    def centered(y, text, size, fill, bold=False):
        f = font(size, bold)
        w = d.textlength(text, font=f)
        d.text(((1200 - w) / 2, y), text, font=f, fill=fill)

    centered(170, 'AKOR', 120, ACCENT, True)
    centered(330, 'Fewer tokens per finished job', 44, TEXT)
    centered(392, 'when AI agents hand work to each other', 44, TEXT)
    centered(500, 'github.com/canerganis/akor', 40, ACCENT, True)
    centered(570, 'open source · MIT', 30, DIM)
    im.save(path)


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


def main():
    card_png = HERE / 'png' / 'akor_card.png'
    card_png.parent.mkdir(exist_ok=True)
    card(card_png)
    inputs, lengths = [], []
    for name in CLIPS:
        inputs += ['-i', str(HERE / f'{name}.gif')]
        lengths.append(duration(HERE / f'{name}.gif'))
    inputs += ['-loop', '1', '-t', str(CARD_SECONDS), '-i', str(card_png)]
    lengths.append(CARD_SECONDS)
    norm = ('fps=30,scale=1280:720:force_original_aspect_ratio=decrease,'
            'pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0d1117,setsar=1,format=yuv420p')
    parts = [f'[{i}:v]{norm}[v{i}]' for i in range(len(lengths))]
    prev, offset = 'v0', 0.0
    for i in range(1, len(lengths)):
        offset += lengths[i - 1] - FADE
        out = f'x{i}'
        parts.append(f'[{prev}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[{out}]')
        prev = out
    cmd = ['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', ';'.join(parts), '-map', f'[{prev}]',
           '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
           str(HERE / 'akor.mp4')]
    subprocess.run(cmd, check=True)
    print('akor.mp4', round(duration(HERE / 'akor.mp4'), 1), 's')


if __name__ == '__main__':
    main()
