"""Helpers shared by the connectors."""
import os
import re
import xml.etree.ElementTree as ET

from probandia.archives import ConnectorError
from probandia.i18n import _
from probandia.util.fs import atomic_write_bytes


def xml(resp, archive):
    if resp.status != 200:
        raise ConnectorError(_("{archive}: HTTP {status}").format(archive=archive, status=resp.status),
                             values={"HTTP": resp.status, "URL": resp.url})
    try:
        return ET.fromstring(resp.body)
    except ET.ParseError:
        raise ConnectorError(_("{archive}: the answer is not XML").format(archive=archive),
                             values={"URL": resp.url})


def local(tag):
    return tag.rsplit("}", 1)[-1]


def find_all(node, name):
    return [e for e in node.iter() if local(e.tag) == name]


def first_text(node, name):
    for e in node.iter():
        if local(e.tag) == name and e.text:
            return e.text.strip()
    return None


def strip_tags(text):
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def save(ctx, folder, name, data):
    """The file's path, and the file written with ``data``; with None, the path only (the caller writes it)."""
    base = ctx.work or (os.path.join(ctx.project, ".probandia") if ctx.project else ".")
    path = os.path.join(base, folder, name)
    if data is not None:
        atomic_write_bytes(path, data)
    return path


def year_range(args):
    return args.get("from"), args.get("to")
