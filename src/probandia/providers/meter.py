"""The free quota around one provider call that ``search`` does not make itself:
the reader step of the reading ladder (``read``).

- before the call, the hard stop (PRD Q-6): a provider whose quota left, reserve
  kept, cannot pay for the operation is not called;
- after it, the units the call used (Q-4): what the answer reports, otherwise the
  catalogue's cost;
- an answer saying that the free quota is used up marks the provider exhausted;
- a provider that takes a ceiling per call (Apify's ``maxTotalChargeUsd``,
  ``maxItems``, ``timeout``) receives ``limits``: the catalogue's ``limits``
  table, and ``max_units``, the quota left, so that no call can spend beyond it.

A provider whose key is optional, called without it (Jina's reader), draws on no
account: nothing is checked or counted for it.
"""
import time

from probandia.config import registry
from probandia.providers import catalogue

READ = "read"


class Meter:
    def __init__(self, ledger, config=None, environ=None, research=None, pass_no=None):
        self.ledger = ledger
        self.config = config
        self.environ = environ or {}
        self.research = research
        self.pass_no = pass_no

    @property
    def reserve(self):
        try:
            return self.config.get("budget.reserve_percent")
        except (AttributeError, KeyError):
            return registry.default_of("budget.reserve_percent")

    def metered(self, provider):
        """True when the call draws on the account's free tier."""
        entry = self.ledger.catalogue[provider]
        env = catalogue.key_env(entry)
        return bool(env and self.environ.get(env)) or not entry.get("key_optional", False)

    def refusal(self, provider, operation=READ, units=None):
        """None when the provider may be called; otherwise why not: a reason of
        ``catalogue.why_unusable`` (not enabled, no key…), or ``quota``. ``units``:
        what the call announces (a crawl of n pages), else the catalogue's cost."""
        why = catalogue.why_unusable(self.ledger.catalogue[provider], self.config, self.environ)
        if why or not self.metered(provider):
            return why
        left = self.ledger.left(provider, self.reserve)
        if left is not None and left < (units if units is not None else self.ledger.cost(provider, operation)):
            return "quota"
        return None

    def limits(self, provider, operation=READ):
        """The ceilings of one call: the catalogue's ``limits``, and ``max_units``,
        the units left before the reserve (lowered to ``limits.max_units`` when
        the catalogue sets it; absent for a tier without a counted amount)."""
        entry = self.ledger.catalogue[provider]
        out = dict(entry.get("limits") or {})
        left = self.ledger.left(provider, self.reserve) if self.metered(provider) else None
        if left is not None:
            left = max(0, left)
            out["max_units"] = min(left, out["max_units"]) if "max_units" in out else left
        return out

    def record(self, provider, units=None, operation=READ):
        """Counts one call: ``units`` as the answer reports them, None for the
        catalogue's cost."""
        if not self.metered(provider):
            return None
        if units is None:
            units = self.ledger.cost(provider, operation)
        return self.ledger.record(provider, operation, units, "response", self.research, self.pass_no)

    def refused(self, provider, status, body, retry_after=None):
        """An error answer. True when it says that the free quota is used up: the
        provider is then marked exhausted, until Retry-After or the end of its period."""
        from probandia.providers.adapters import exhausted_status
        from probandia.util.http import retry_after as seconds

        if not self.metered(provider) or not exhausted_status(provider, status, body):
            return False
        self.ledger.mark_exhausted(provider, seconds(retry_after, time.time()))
        return True
