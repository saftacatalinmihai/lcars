"""Generated texture tiles for the bridge (bridge-redesign.md 8h): a
Higgsfield image made seamless, colour-matched to the palette in linear
space, and its normal and roughness maps derived from its height, as the
deck's T.* generator derives them from its own. Writes three webp per
surface into lcars-ui/deck/: bridge_<name>_{base,norm,rough}.webp.

  python3 scripts/deck-models/tiles.py SRC_DIR OUT_DIR [name ...]

SRC_DIR holds the generated images (the media store's
deck-models/bridge_tiles/, with their LICENSE.txt). Needs numpy and Pillow.
The phone loads their KTX2 (deck-remodel.md slice 1): after writing new
webps, run `scripts/deck-models/build.sh --ktx2 maps` too."""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


def lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def load(path, n):
    """The image, its outer 1.5% cut off (a generated "scan" has a light
    frame a few pixels wide, which the seamless pass would carry to the
    tile's middle), at n x n."""
    im = Image.open(path).convert("RGB")
    c = int(round(im.size[0] * 0.015))
    im = im.crop((c, c, im.size[0] - c, im.size[1] - c))
    return np.asarray(im.resize((n, n), Image.LANCZOS), np.float64) / 255


def blur(a, r):
    """A wrapped box-ish blur (three passes of a moving mean): the tile's
    edges are its neighbours'."""
    k = max(1, int(r))
    for _ in range(3):
        acc = np.zeros_like(a)
        for d in range(-k, k + 1):
            acc += np.roll(a, d, 0)
        a = acc / (2 * k + 1)
        acc = np.zeros_like(a)
        for d in range(-k, k + 1):
            acc += np.roll(a, d, 1)
        a = acc / (2 * k + 1)
    return a


def flatten(img, r):
    """Divide out the light's slow drift across the image (a generated
    "scan" is never evenly lit), keeping its mean: tiled, a gradient would
    repeat as stripes."""
    lo = blur(img, r)
    return img / np.maximum(lo, 1e-3) * lo.mean(axis=(0, 1))


def seamless(img, feather):
    """The offset-and-blend pass: the image and itself rolled by half,
    mixed with a weight that is the image's own in the middle and the
    rolled copy's at the edges, so every edge meets its opposite. The mix
    is variance-preserving (divided by the weights' norm about the mean),
    so the blended band keeps the texture's contrast instead of greying."""
    n = img.shape[0]
    b = np.roll(np.roll(img, n // 2, 0), n // 2, 1)
    i = np.arange(n)
    d = np.minimum(i, n - 1 - i) / (n * feather)
    w1 = np.clip(d, 0, 1)
    w1 = w1 * w1 * (3 - 2 * w1)
    w = np.minimum.outer(w1, w1)[..., None]
    m = img.mean(axis=(0, 1))
    out = (img - m) * w + (b - m) * (1 - w)
    return out / np.sqrt(w * w + (1 - w) ** 2) + m


def match(img, hexv, tone):
    """Per-channel gain in linear space so the mean is what the procedural
    gives: the palette's colour times its tone map's mean (the canvas tone
    is a linear multiplier). The deck then divides the material's colour by
    the palette's, so a clone tinted from it (the well, the wainscot's
    x0.82) keeps its tint over the same map."""
    t = lin(np.array([(hexv >> 16) & 255, (hexv >> 8) & 255, hexv & 255], np.float64) / 255) * tone
    L = lin(img)
    L = L * (t / L.mean(axis=(0, 1)))
    return srgb(L)


def normals(h, strength):
    """Tangent-space normals from a height field, wrapping, as normalTex in
    deck.html (the texture is not flipped: three's TextureLoader flips a
    webp, so the canvas convention holds: dn - up)."""
    nx = (np.roll(h, 1, 1) - np.roll(h, -1, 1)) * strength
    ny = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    k = 1 / np.sqrt(nx * nx + ny * ny + 1)
    return np.stack([nx * k * 0.5 + 0.5, ny * k * 0.5 + 0.5, k * 0.5 + 0.5], -1)


def save(a, path, q):
    a = np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
    (Image.fromarray(a) if a.ndim == 3 else Image.fromarray(a, "L")).save(path, "WEBP", quality=q, method=6)
    return os.path.getsize(path)


def lum(img):
    return img @ np.array([0.2126, 0.7152, 0.0722])


def carpet(src, n):
    img = seamless(flatten(load(os.path.join(src, "carpet.png"), n), n / 16), 0.18)
    # the relief from a blurred height: the loops at one texel are noise
    # webp cannot pack (129 kB at 512) and a phone never resolves; the
    # blur keeps the fleck's dimples and the pile's soft rows
    h = blur(lum(img), 1.5)
    h = (h - h.mean()) / (h.std() + 1e-6)
    rough = np.clip(0.92 + 0.04 * np.tanh(h), 0, 1)
    return img, h * 0.12, rough, 2.5


def wall(src, n):
    """The set's padded panel, one per 1.2 m column, its top and bottom rims
    on the reveal: the tile is the 2.4 m square of T.panelBridge (u across
    two columns, v up 2.4 m, the reveal at 0.7 of it from the top), so the
    reveal stays at 3.02 m and the seams where they were."""
    p = Image.open(os.path.join(src, "wall.png")).convert("RGB")
    p = np.asarray(p.resize((n // 2, n), Image.LANCZOS), np.float64) / 255
    p = flatten(p, n / 6)
    img = np.concatenate([p, p], 1)
    # the panel's top on the reveal's lower lip: roll its top edge down to it
    r = int(round(n * 0.7))
    img = np.roll(img, r, 0)
    h = lum(img)
    h = blur(h, 1)
    h = (h - h.mean()) / (h.std() + 1e-6)
    # the reveal: a channel 6 cm of the 2.4 m tall, sunk deeper and darker
    # than the panels' own rims, as panelSet(true) draws it
    w = max(2, int(round(n * 0.06 / 2.4)))
    img[r - w // 2:r + w - w // 2] *= 0.55
    h[r - w // 2:r + w - w // 2] = h.min() - 1.0
    rough = np.clip(0.62 - 0.08 * np.tanh(h), 0, 1)
    return img, h * 0.25, rough, 3.0


def wainscot(src, n):
    """The walnut cut into the procedural's layout (T.grooves: a groove
    every quarter of the 1.2 m tile): the generated image's board seams
    are irregular, so one clean board (rows 1342-1831 of the 2048) is
    taken, made seamless along its grain, and stacked four times, each
    shifted along so no knot repeats in a column, a groove at each joint."""
    a = Image.open(os.path.join(src, "wainscot.png")).convert("RGB")
    a = np.asarray(a, np.float64)[1342:1832] / 255
    q = n // 4
    b = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((n, q), Image.LANCZOS), np.float64) / 255
    b = flatten(b, n / 8)
    # seamless along u only: blend the board with itself rolled by half
    r = np.roll(b, n // 2, 1)
    i = np.arange(n)
    w = np.clip(np.minimum(i, n - 1 - i) / (n * 0.15), 0, 1)
    w = (w * w * (3 - 2 * w))[None, :, None]
    m = b.mean(axis=(0, 1))
    b = ((b - m) * w + (r - m) * (1 - w)) / np.sqrt(w * w + (1 - w) ** 2) + m
    img = np.concatenate([np.roll(b, k * n * 3 // 8, 1) for k in range(4)], 0)
    h = blur(lum(img), 1)
    h = (h - h.mean()) / (h.std() + 1e-6) * 0.08
    # the grooves, as T.grooves draws them (4 px of 512, blurred)
    gw = max(2, n // 128)
    g = np.ones(n)
    for k in range(4):
        y = k * q
        for d in range(-gw // 2, gw - gw // 2):
            g[(y + d) % n] = 0
    g = blur(np.tile(g[:, None], (1, 8)), 1)[:, 0]
    img = img * (0.65 + 0.35 * g)[:, None, None]
    h = h + g[:, None]
    rough = np.clip(0.42 + 0.1 * np.tanh(-h), 0, 1)
    return img, h, rough, 5.0


RECIPES = {
    # name: (recipe, palette colour, its tone map's mean, size, normal size, base quality)
    # the tone means: T.carpet's 0.6+0.28*.5+0.14*.5+0.04 (~0.82),
    # T.panelBridge's and T.grooves' about 0.92 and 0.9
    "carpet": (carpet, 0x4e4548, 0.82, 512, 256, 72),
    "wall": (wall, 0xd6c4a6, 0.92, 512, 512, 80),
    # made, not shipped: on the phone it tied with T.grooves (bridge-redesign.md 8h)
    "wainscot": (wainscot, 0x6a5646, 0.9, 512, 512, 78),
}
SHIPPED = ["carpet", "wall"]


def proof(path, out):
    """A 2x2 repeat of a base map, to see its seams."""
    a = Image.open(path)
    w, h = a.size
    c = Image.new("RGB", (w * 2, h * 2))
    for x in (0, w):
        for y in (0, h):
            c.paste(a, (x, y))
    c.save(out)


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    for name in sys.argv[3:] or SHIPPED:
        fn, col, tone, n, nn, q = RECIPES[name]
        img, h, rough, k = fn(src, n)
        img = match(np.clip(img, 0, 1), col, tone)
        b = save(img, os.path.join(out, f"bridge_{name}_base.webp"), q)
        nmap = normals(h, k)
        if nn != n:
            nmap = np.asarray(Image.fromarray((nmap * 255).astype(np.uint8)).resize((nn, nn), Image.LANCZOS), np.float64) / 255
        nm = save(nmap, os.path.join(out, f"bridge_{name}_norm.webp"), 80)
        r = save(np.asarray(Image.fromarray((rough * 255).astype(np.uint8), "L").resize((n // 4, n // 4), Image.BILINEAR), np.float64) / 255,
                 os.path.join(out, f"bridge_{name}_rough.webp"), 80)
        print(f"[tiles] {name}: {n}², base {b // 1024} kB, normal {nn}² {nm // 1024} kB, roughness {r // 1024} kB")
