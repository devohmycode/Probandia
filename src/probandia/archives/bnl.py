"""Bibliothèque nationale du Luxembourg: the open data of historical newspapers.

``download`` fetches one open-data package into the data folder, a chunk at a time (the packages
weigh 125 MB to 257 GB), once the person saw its size; ``search`` then looks for a word in the
downloaded texts, locally, with no network.
"""
import os
import re
import shutil
import urllib.parse
import zipfile

from probandia.archives import ConnectorError, Operation, OperationResult
from probandia.errors import NetworkError, ProbandiaError
from probandia.i18n import _

ARCHIVE = "bnl"
HOSTS = ["data.bnl.lu", "open-data.bnl.lu"]
OPERATIONS = {
    "download": Operation(doc="download one open-data package of Luxembourg newspapers (BnL)",
                          params={"url": str}, required=("url",)),
    "search": Operation(doc="search the downloaded Luxembourg newspapers (BnL open data), locally",
                        params={"query": str, "max": int}, required=("query",)),
}
WITNESS = {"operation": "search", "args": {"query": "Luxembourg"}, "expect": {"min_results": 1}}


def folder(ctx):
    base = ctx.data_dir or os.path.join(ctx.project or ".", ".probandia")
    return os.path.join(base, "bnl")


def question(operation, args, ctx):
    """What ``archive run`` asks before ``download``: the size the server announces (a ``HEAD``)."""
    if operation != "download":
        return None
    from probandia.i18n import formats

    try:
        size = int(ctx.client.request("HEAD", args["url"], api=True).headers.get("content-length"))
        size = formats.number(size / 1e6, 1) + " MB"
    except (ProbandiaError, TypeError, ValueError):
        size = _("a package of unknown size")
    return _("Download {size} from {host} into {folder}?").format(
        size=size, host=urllib.parse.urlsplit(args["url"]).netloc, folder=folder(ctx))


def run(operation, args, ctx):
    target = folder(ctx)
    if operation == "download":
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, os.path.basename(args["url"].split("?")[0]) or "download.txt")
        try:
            ctx.client.download(args["url"], path, api=True)
        except NetworkError as err:
            raise ConnectorError(f"bnl: {err.message}", values={"URL": args["url"]}) from None
        written = 1
        if zipfile.is_zipfile(path):
            written = 0
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.filename.endswith((".txt", ".xml")) and not info.filename.startswith(("/", "..")):
                        with z.open(info) as src, open(os.path.join(target, os.path.basename(info.filename)),
                                                       "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        written += 1
            os.unlink(path)
        return OperationResult(count=written, path=target, url=args["url"])
    if not os.path.isdir(target):
        raise ConnectorError("bnl: no newspaper downloaded yet (archive run bnl.download)")
    pattern = re.compile(re.escape(args["query"]), re.I)
    rows, total = [], 0
    for name in sorted(os.listdir(target)):
        with open(os.path.join(target, name), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        hits = list(pattern.finditer(text))
        total += len(hits)
        for m in hits[:3]:
            start = max(0, m.start() - 120)
            rows.append({"title": name, "snippet": " ".join(text[start:m.end() + 120].split()),
                         "url": f"file://{os.path.join(target, name)}"})
            if len(rows) >= args.get("max", 20):
                break
    return OperationResult(rows=rows, count=total)
