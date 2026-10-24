"""Image tools that write a file and say only its size (token-economy A5): a sheet of the top
bands of several views, to find the right view in one reading; a crop; a quarter turn.

An image costs about width × height / 750 tokens to the agent that reads it, and stays in
its context: ``TOKENS_EST`` says so before it is read. Pillow is optional (``doctor`` gives the command that installs it);
without it every tool raises NoPillow, which the commands turn into ``STATUS=STOP``.
"""
import os

from probandia.errors import ProbandiaError
from probandia.i18n import _

SHEET_MAX_PX = 750_000   # a sheet costs 1,000 tokens at most: ten double pages at 660 px (T73b; 1,533 before)
TOKENS_PER_PX = 1 / 750


class NoPillow(ProbandiaError):
    """The commands answer STATUS=STOP, REASON=no-pillow, as for no-tesseract."""

    reason = "no-pillow"


def _pil():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        from probandia.doctor import install_commands

        raise NoPillow(_("Pillow is not installed: {command}").format(command=install_commands("pillow")[0]),
                       values={"REASON": "no-pillow", "ALTERNATIVE": "iiif.region"}) from None
    return Image, ImageDraw


def tokens_est(width, height):
    return round(width * height * TOKENS_PER_PX)


def views(source):
    """T247: the images of a source's act, in order, each once: its ``image``, then its ``images``."""
    return list(dict.fromkeys(v for v in [source.get("image"), *(source.get("images") or [])] if v))


# token-economy J10, the guard of J2 alone: a view saved small finds the act and never reads it, nor does
# a crop, a sheet or a turn made from one, whatever its name (``act54.jpg``). A small view and a whole one
# share a name (``ad50-<register>-<view>.jpg``): the project keeps which images are small, a whole view
# saved over a small one clears it, and ``transcribe new`` refuses them. T69: the mark is the digest of
# the image's bytes, so a copy or a rename made outside the engine (``cp``, ``mv``) stays small; a path
# is kept only for a file that cannot be read, and as projects marked before T69 kept it.
READ_MIN_PX = 2000   # a view asked smaller only finds the act; the readers of J8 read at 2,000 and 2,400 px


def _small_file(project):
    return os.path.join(project, ".probandia", "cache", "small-images.json") if project else None


def _key(path):
    return os.path.normcase(os.path.realpath(path))


def _content_key(path):
    """``sha256:<hex>`` of the file's bytes; None when it cannot be read."""
    import hashlib

    try:
        with open(path, "rb") as fh:
            return "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
    except OSError:
        return None


def _keys(path):
    return {k for k in (_key(path), _content_key(path)) if k}


def _small(project):
    import json

    try:
        with open(_small_file(project), encoding="utf-8") as fh:
            kept = json.load(fh)
        return set(kept) if isinstance(kept, list) else set()
    except (OSError, TypeError, ValueError):
        return set()


def mark_small(project, path, small=True):
    """Keeps ``path`` as a small image, or, with ``small`` false, as one that may be read."""
    from probandia.util.fs import atomic_write_json

    if not project:
        return
    kept = _small(project)
    marked = kept | {_content_key(path) or _key(path)} if small else kept - _keys(path)
    if marked == kept:
        return
    try:
        atomic_write_json(_small_file(project), sorted(marked))
    except OSError:
        pass


def is_small(project, path):
    return bool(project) and bool(_keys(path) & _small(project))


def carry_small(project, sources, out):
    """An image made from others is small when one of them is."""
    mark_small(project, out, any(is_small(project, s) for s in sources))


def size_of(path):
    """(width, height) read from the header of a PNG or JPEG file, without Pillow (token-economy I2);
    None for another kind of file or a damaged one."""
    import struct

    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] != b"\xff\xd8":
                return None
            fh.seek(2)
            while True:   # the JPEG segments, up to the frame header (SOFn) that holds the size
                if fh.read(1) != b"\xff":
                    return None
                marker = fh.read(1)
                while marker == b"\xff":   # fill bytes
                    marker = fh.read(1)
                if not marker or marker[0] in (0xD9, 0xDA):   # the end, or the image data: no frame header
                    return None
                if 0xD0 <= marker[0] <= 0xD7 or marker[0] == 0x01:   # markers without a length
                    continue
                length = struct.unpack(">H", fh.read(2))[0]
                if 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
                    height, width = struct.unpack(">xHH", fh.read(5))
                    return width, height
                fh.seek(length - 2, 1)
    except (OSError, struct.error):
        return None


def described(path, image):
    """What a tool answers: the file, its size and the tokens it costs once read."""
    w, h = image.size
    return {"FILE": path, "PX": f"{w}x{h}", "TOKENS_EST": tokens_est(w, h)}


def _save(image, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=80)
    return described(path, image)


def sheet(paths, out, band=0.25, labels=None, max_px=SHEET_MAX_PX):
    """The top ``band`` (a fraction of the height) of each image (a path or an open file), numbered, one
    under the other, scaled so that the sheet holds at most ``max_px`` pixels."""
    Image, ImageDraw = _pil()
    if not paths:
        raise ProbandiaError(_("no image to put on the sheet"), values={"REASON": "no-image"})
    bands = []
    for p in paths:
        with Image.open(p) as im:
            w, h = im.size
            bands.append(im.crop((0, 0, w, max(1, round(h * band)))).convert("RGB"))
    width = min(b.size[0] for b in bands)
    scaled = [b.resize((width, max(1, round(b.size[1] * width / b.size[0])))) for b in bands]
    total = sum(b.size[1] for b in scaled)
    factor = min(1.0, (max_px / (width * total)) ** 0.5)
    if factor < 1:
        scaled = [b.resize((max(1, round(b.size[0] * factor)), max(1, round(b.size[1] * factor)))) for b in scaled]
    out_w, out_h = scaled[0].size[0], sum(b.size[1] for b in scaled)
    page = Image.new("RGB", (out_w, out_h), "white")
    draw, y = ImageDraw.Draw(page), 0
    for i, b in enumerate(scaled):
        page.paste(b, (0, y))
        label = str(labels[i] if labels else i + 1)
        draw.rectangle((0, y, 8 + 9 * len(label), y + 16), fill="yellow")
        draw.text((4, y + 2), label, fill="black")
        y += b.size[1]
    return _save(page, out)


REGION_MAX_TOKENS = 2500   # one act; a page of a double view is 3,600 or more (bench of 11 Oct. 2026)


def crop(path, out, region, whole=False, seen=None):
    """``region`` as ``x,y,w,h``: fractions of the page (0 to 1), or pixels; with ``seen``, pixels of the
    image seen at ``seen`` px on its long side, cut from this one at full size (T73c). A region holds one act:
    above ``REGION_MAX_TOKENS`` it is refused, unless ``whole`` says the act fills it (token-economy J7:
    readers cropped whole pages of 1,349 × 2,000 px, where an act took 880 × 720)."""
    Image, _d = _pil()
    try:
        x, y, w, h = (float(v) for v in str(region).split(","))
    except ValueError:
        raise ProbandiaError(_("a region is x,y,w,h, not {region}").format(region=region),
                             values={"REASON": "region"}) from None
    with Image.open(path) as im:
        W, H = im.size
        if max(x, y, w, h) <= 1:
            x, y, w, h = x * W, y * H, w * W, h * H
        elif seen:
            k = max(1.0, max(W, H) / seen)   # an image smaller than asked was seen at its own size
            x, y, w, h = x * k, y * k, w * k, h * k
        box = (round(x), round(y), min(W, round(x + w)), min(H, round(y + h)))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ProbandiaError(_("the region {region} is outside the image").format(region=region),
                                 values={"REASON": "region"})
        cost = tokens_est(box[2] - box[0], box[3] - box[1])
        if cost > REGION_MAX_TOKENS and not whole:
            raise ProbandiaError(_("the region is {w}x{h} px, {tokens} tokens: a page, not an act; crop the act "
                                   "alone (at most {max} tokens), or give --whole if it fills the region").format(
                w=box[2] - box[0], h=box[3] - box[1], tokens=cost, max=REGION_MAX_TOKENS),
                values={"REASON": "region-large", "TOKENS_EST": cost})
        # REGION: where the act is on this image, in its pixels, what a reader returns as region= (T247, T73c)
        return dict(_save(im.crop(box), out), REGION=f"{box[0]},{box[1]},{box[2] - box[0]},{box[3] - box[1]}")


def rotate(path, out, turn):
    """A quarter turn clockwise: ``turn`` is 90, 180 or 270."""
    Image, _d = _pil()
    if int(turn) not in (90, 180, 270):
        raise ProbandiaError(_("a turn is 90, 180 or 270"), values={"REASON": "turn"})
    with Image.open(path) as im:
        return _save(im.rotate(-int(turn), expand=True), out)
