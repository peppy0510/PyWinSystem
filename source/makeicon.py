# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os

from PIL import Image
from PIL import ImageDraw


MARK = (18, 24, 44, 255)
TILE_STOPS = ((40, 200, 190), (60, 130, 245), (120, 90, 240))

# three meter bars, as fractions of the tile
BARS = ((0.24, 0.52), (0.43, 0.30), (0.62, 0.42))
BAR_WIDTH = 0.14
BAR_BOTTOM = 0.76

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

SCALE = 8


def blend(stops, t):
    t = max(0.0, min(1.0, t))
    index = min(len(stops) - 2, int(t * (len(stops) - 1)))
    local = t * (len(stops) - 1) - index
    a, b = stops[index], stops[index + 1]
    return tuple(int(a[i] + (b[i] - a[i]) * local) for i in range(3)) + (255,)


def draw_gradient(canvas):
    image = Image.new('RGBA', (canvas, canvas))
    pixels = image.load()
    for y in range(canvas):
        for x in range(canvas):
            pixels[x, y] = blend(TILE_STOPS, (x * 0.55 + y * 0.45) / canvas)
    return image


def draw_mark(size):
    canvas = size * SCALE
    image = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))

    inset = canvas * 0.03
    mask = Image.new('L', (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle((inset, inset, canvas - inset - 1, canvas - inset - 1),
                                           radius=canvas * 0.23, fill=255)
    image.paste(draw_gradient(canvas), (0, 0), mask)

    draw = ImageDraw.Draw(image)
    for left, top in BARS:
        draw.rounded_rectangle((canvas * left, canvas * top, canvas * (left + BAR_WIDTH),
                                canvas * BAR_BOTTOM), radius=canvas * 0.03, fill=MARK)

    return image.resize((size, size), Image.LANCZOS)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'assets', 'icon')
    os.makedirs(path, exist_ok=True)

    frames = [draw_mark(size) for size in SIZES]
    frames[-1].save(os.path.join(path, 'icon.png'))
    frames[-1].save(os.path.join(path, 'icon.ico'), format='ICO',
                    sizes=[(size, size) for size in SIZES],
                    append_images=frames[:-1])
    print(f'[ ICON CREATED ] [ {os.path.join(path, "icon.ico")} ]')


if __name__ == '__main__':
    main()
