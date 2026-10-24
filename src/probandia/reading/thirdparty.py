"""One call of a third party for ``read --map``, ``--crawl`` or ``--extract``: the
providers tried in order, each one only when its free quota pays for what the
call announces (PRD Q-6), and every call made counted.

- A local or private URL (``ladder.is_local``, T58), or a host whose archive
  forbids third-party readers (``third_party: forbidden``, G-3), is never sent:
  ``Outcome.refused`` says why.
- A provider not enabled, without its key, or that does not make the operation
  is passed over without a word; one whose quota cannot pay is noted ``quota``.
- An answer saying the free quota is used up marks the provider exhausted, and
  the next one is tried; any other error ends the attempt (``Outcome.error``).
"""
import urllib.parse

from probandia.reading.ladder import is_local


class Outcome:
    def __init__(self):
        self.provider = None    # the provider that answered
        self.value = None       # what its adapter returned
        self.units = 0.0
        self.tried = []         # (step, status), for TRIED
        self.quota = []         # providers held back by their free quota
        self.refused = None     # "local-url" or "forbidden-host": nothing was sent
        self.error = None       # the ProviderError that ended the attempt

    @property
    def ok(self):
        return self.provider is not None


def call(reader, operation, url, order, run, units=None, reuse=True):
    """Tries the providers of ``order`` for ``operation`` on ``url``. ``run(adapter)``
    makes the call and returns ``(value, Usage)``; ``units(adapter)`` is what the
    call announces (by default the catalogue's cost of one operation). With
    ``reuse`` False (a living person named), a provider that may reuse what it is
    sent (``content_reuse``) is not asked, noted ``living-person-name``."""
    from probandia.providers import adapters, catalogue
    from probandia.providers.base import ProviderError

    out = Outcome()
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if is_local(url):
        out.refused = "local-url"
    elif host in reader.forbidden or host.removeprefix("www.") in reader.forbidden:
        out.refused = "forbidden-host"
    if out.refused:
        out.tried.append(("third-party", out.refused))
        return out
    meter = reader.meter
    cat = meter.ledger.catalogue if meter is not None else catalogue.load()
    for pid in order:
        entry = cat.get(pid)
        if entry is None or not catalogue.does(entry, operation):
            continue
        label = f"{operation}:{pid}"
        if not reuse and entry.get("content_reuse"):
            out.tried.append((label, "living-person-name"))
            continue
        ad = adapters.make(pid, reader.client, entry, reader.environ)
        announced = units(ad) if units else ad.cost(operation)
        if meter is not None:
            why = meter.refusal(pid, operation, announced)
            if why == "quota":
                out.tried.append((label, "quota"))
                out.quota.append(pid)
            if why:
                continue
        elif not catalogue.has_key(entry, reader.environ):
            continue
        try:
            value, usage = run(ad)
        except ProviderError as err:
            if meter is not None and err.status and meter.refused(pid, err.status, err.excerpt, err.retry_after):
                out.tried.append((label, "quota"))
                out.quota.append(pid)
                continue
            out.tried.append((label, "error"))
            out.error = err
            return out
        if meter is not None:
            meter.record(pid, usage.units, operation)
        out.provider, out.value, out.units = pid, value, usage.units
        out.tried.append((label, "ok"))
        return out
    return out
