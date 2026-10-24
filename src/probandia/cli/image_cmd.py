"""``image sheet|crop|rotate``: image tools that write a file and print only its size (token-economy A5)."""
import os

from probandia.cli.output import Result
from probandia.errors import ProbandiaError, UsageError
from probandia.i18n import _


def image_args(p, common):
    p.add_argument("action", choices=("sheet", "crop", "rotate"))
    p.add_argument("files", nargs="+", help=_("the images: several for a sheet, one otherwise"))
    p.add_argument("--band", type=float, default=0.25, help=_("sheet: the top part of each view kept, 0 to 1"))
    p.add_argument("--labels", help=_("sheet: the number of each view, comma-separated (default: 1, 2, 3…)"))
    p.add_argument("--region", help=_("crop: x,y,w,h, as fractions of the page or in pixels"))
    p.add_argument("--whole", action="store_true",
                   help=_("crop: the act fills a region larger than one act usually is"))
    p.add_argument("--turn", type=int, choices=(90, 180, 270), help=_("rotate: a turn clockwise"))
    p.add_argument("--out", help=_("the file written (default: next to the first image)"))


def _out(ctx, suffix):
    if ctx.args.out:
        return ctx.args.out
    stem, _ext = os.path.splitext(ctx.args.files[0])
    return f"{stem}-{suffix}.jpg"


def image(ctx):
    from probandia import images

    a = ctx.args
    missing = [f for f in a.files if not os.path.isfile(f)]
    if missing:
        raise UsageError(_("no image {path}").format(path=missing[0]))
    try:
        if a.action == "sheet":
            labels = [x.strip() for x in a.labels.split(",")] if a.labels else None
            if labels and len(labels) != len(a.files):
                raise UsageError(_("give one label per image"))
            out = _out(ctx, "sheet")
            values = images.sheet(a.files, out, a.band, labels)
        elif len(a.files) != 1:
            raise UsageError(_("{action} takes one image").format(action=a.action))
        elif a.action == "crop":
            if not a.region:
                raise UsageError(_("crop needs --region x,y,w,h"))
            out = _out(ctx, "crop")
            values = images.crop(a.files[0], out, a.region, a.whole)
        else:
            if not a.turn:
                raise UsageError(_("rotate needs --turn 90, 180 or 270"))
            out = _out(ctx, f"r{a.turn}")
            values = images.rotate(a.files[0], out, a.turn)
    except images.NoPillow:
        return Result.stop("no-pillow", "iiif.region", values={"INSTALL": "python -m pip install Pillow"})
    try:
        project = ctx.project
    except ProbandiaError:
        project = None
    images.carry_small(project, [os.path.join(ctx.cwd, f) for f in a.files], os.path.join(ctx.cwd, out))   # J10
    r = Result("OK", values)
    r.line(_("TOKENS_EST is what reading the image costs: read it only if it is worth that"))
    return r
