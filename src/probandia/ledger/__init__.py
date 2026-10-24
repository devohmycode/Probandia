"""The quota ledger: what each provider's free tier has left.

- ``.probandia/ledger.jsonl``: one line per consumption, with its ``source``:
  ``estimate``, ``response``, ``sync`` or ``manual``.
- ``.probandia/quota.json``: per provider, ``period_start``, ``used``,
  ``reported_left``, ``reported_at`` and ``exhausted_until``.

Before a wave::

    needed  = Σ costs[operation] × calls
    reserve = ceil(free.amount × budget.reserve_percent / 100)   (in dollars: not rounded)
    left    = free.amount − used in the period − reserve
    left    = min(left, providers.<id>.monthly_cap − used in the month)   (when the cap is set)

Periods: ``daily`` resets at 00:00 UTC; ``monthly`` on its reset day (a day of
the month, or the billing date reported by the provider, otherwise the 1st);
``once`` never resets, but may expire: ``free.expires_months`` after the first
use (or after ``period_start`` when the provider reports it), nothing is left.
When the local count and the provider's disagree, the larger one counts; a gap
above 10 % is a warning.

An entry with ``quota = "<id>"`` draws on another entry's quota (SerpApi's Bing
engine on the SerpApi account): counts, reports and exhaustion go to that entry.

The counter of the user (cli.md § 4.4, decision D-1). A free quota belongs to an
API key, which several projects often share. Given the environment, the ledger
counts in the user's data folder (``<data>/quotas/ledger.jsonl`` and
``state.json``), each line filed under the entry that pays and the key's
fingerprint (8 hexadecimal digits of its SHA-256; ``public`` without a key):
every project with the same key sees the same count, and a project with a key of
its own its own count. The project's ledger still gets each line, with the
research and the pass, for the reports and rule V-10. The lines another copy of
the engine wrote there (an older plugin, still in a harness) are caught up each
time this one opens the project: those it wrote itself carry ``counted`` and are
skipped. Without the environment (unit tests), the ledger is the project's only.
"""
import hashlib
import datetime
import json
import math
import os

from probandia.util.fs import atomic_write_json, iso, parse_iso, utc_now

GAP_WARNING = 0.10
# The balances the providers report are read without being asked (decision T7): at the
# first new or resume of the day, then for one provider every 20 calls counted since its
# last reading; never in a hook. A reading that failed is not tried again for an hour.
SYNC_DAILY = datetime.timedelta(hours=24)
SYNC_EVERY_CALLS = 20
SYNC_RETRY = datetime.timedelta(hours=1)
DRIFT = 0.10    # the provider's drop and the ledger's count apart by this much: a drift is said
LOW = 0.20      # under this share of a quota left, agents and user are warned (T62)
FORECAST_DAYS = 7   # the pace usage --forecast extends (T63)
IMPORTED = "quota-imported.json"   # in <project>/.probandia: how many of its lines were examined
LOCK_WAIT = 10.0                   # seconds a writer waits for the counter's lock
LOCK_STALE = 30.0                  # a lock file older than this is left over from a crash


def fingerprint(value):
    """What tells keys apart without keeping them: 8 hexadecimal digits of the
    SHA-256 of the key, or ``public`` when there is none."""
    if not value:
        return "public"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


class _FileLock:
    """A lock file created exclusively; one left over from a crash is taken over."""

    def __init__(self, path):
        self.path = path + ".lock"

    def __enter__(self):
        import time

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        start = time.monotonic()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except (FileExistsError, PermissionError):   # Windows: a lock file being removed denies access
                try:
                    if time.time() - os.path.getmtime(self.path) > LOCK_STALE:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.monotonic() - start > LOCK_WAIT:
                    raise TimeoutError(f"quota counter locked: {self.path}")
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def _date(ts):
    """A timestamp of the ledger, or one a provider gave (with milliseconds or an
    offset, such as Firecrawl's ``2026-09-06T16:57:22.339Z``)."""
    if not isinstance(ts, str):
        return ts
    try:
        return parse_iso(ts)
    except ValueError:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        utc = datetime.timezone.utc
        return (dt if dt.tzinfo else dt.replace(tzinfo=utc)).astimezone(utc).replace(microsecond=0)


_LINES = {}   # path -> ((mtime_ns, size, inode), the lines read)


def _read_lines(path):
    """The JSON lines of ``path``, each a dict of its own. The file is parsed again only once it has
    changed: ``status`` reads the user's counter once per account (T148)."""
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        hit = _LINES.get(path)
        if hit is None or hit[0] != stamp:
            with open(path, encoding="utf-8") as fh:
                hit = _LINES[path] = (stamp, [json.loads(line) for line in fh if line.strip()])
    except FileNotFoundError:
        return []
    return [dict(e) for e in hit[1]]


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def _append(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Ledger:
    def __init__(self, project, catalogue, clock=utc_now, environ=None, config=None):
        self.project = project
        # the settings, for providers.<id>.monthly_cap: given, or read on first need (T53)
        self._config = config
        self.dir = os.path.join(project, ".probandia") if project else None
        self.log = os.path.join(self.dir, "ledger.jsonl") if project else None
        self.state_path = os.path.join(self.dir, "quota.json") if project else None
        self.catalogue = catalogue
        self.clock = clock
        self.environ = environ
        self.user = environ is not None
        if self.user:
            from probandia.paths import user_data_dir

            folder = os.path.join(user_data_dir(environ), "quotas")
            self.user_log = os.path.join(folder, "ledger.jsonl")
            self.user_state_path = os.path.join(folder, "state.json")
            self.project_id = fingerprint(os.path.abspath(project)) if project else None
            if project:
                self._catch_up()

    # keys

    def key(self, provider):
        """The fingerprint of the key that pays for ``provider``'s quota."""
        pool = self.catalogue[self.pool(provider)]
        env = (pool.get("auth") or {}).get("env")
        return fingerprint(self.environ.get(env) if env else None)

    # files

    def state(self):
        if not self.user:
            return _read_json(self.state_path) if self.state_path else {}
        out = {}
        for name, st in _read_json(self.user_state_path).items():
            pool, _sep, fp = name.partition("@")
            if pool in self.catalogue and fp == self.key(pool):
                out[pool] = st
        return out

    def save_state(self, state):
        if not self.user:
            atomic_write_json(self.state_path, state)
            return
        with _FileLock(self.user_state_path):
            raw = _read_json(self.user_state_path)
            for pool, st in state.items():
                raw[f"{pool}@{self.key(pool)}"] = st
            atomic_write_json(self.user_state_path, raw)

    def entries(self):
        """The consumptions counted against the keys in effect."""
        if not self.user:
            return _read_lines(self.log) if self.log else []
        keys = {}   # one fingerprint per provider, not per line

        def key(provider):
            if provider not in keys:
                keys[provider] = self.key(provider)
            return keys[provider]

        return [e for e in _read_lines(self.user_log)
                if e.get("provider") in self.catalogue and e.get("key") == key(e["provider"])]

    def record(self, provider, operation, units, source="response", research=None, pass_no=None,
               note=None):
        entry = {"ts": iso(self.clock()), "provider": provider, "operation": operation,
                 "units": units, "research": research, "pass": pass_no, "source": source}
        if note:
            entry["note"] = note
        if self.log:
            _append(self.log, dict(entry, counted=True) if self.user else entry)
        if self.user:
            line = dict(entry, key=self.key(provider), project=self.project_id)
            with _FileLock(self.user_log):
                _append(self.user_log, line)
        return entry

    def projects_sharing(self, provider):
        """How many projects counted against the key in effect for ``provider``'s quota."""
        if not self.user:
            return 1
        pool, fp = self.pool(provider), self.key(provider)
        return len({e.get("project") for e in _read_lines(self.user_log)
                    if e.get("provider") in self.catalogue and self.pool(e["provider"]) == pool
                    and e.get("key") == fp and e.get("project")})

    def _catch_up(self):
        """The project's lines the user's counter has not seen yet go to it: all of
        them the first time, then those an older engine appended since. A line this
        engine wrote carries ``counted``; estimates and syncs count nothing."""
        marker = os.path.join(self.dir, IMPORTED)
        all_lines = _read_lines(self.log) if self.log else []
        if not all_lines and not os.path.isfile(self.state_path):
            return   # nothing to bring over: a reading writes nothing (version-1.0.0 T109)
        seen = _read_json(marker)
        if seen and "examined" not in seen:   # a marker of the first version: everything was taken then
            seen = {"examined": len(all_lines)}
        start = seen.get("examined", 0) if seen else 0
        if seen and start >= len(all_lines):
            return
        new = [e for e in all_lines[start:]
               if e.get("provider") in self.catalogue and e.get("source") not in ("estimate", "sync")
               and not e.get("counted")]
        if new:
            with _FileLock(self.user_log):
                for e in new:
                    _append(self.user_log, dict(e, key=self.key(e["provider"]), project=self.project_id,
                                                imported=True))
        if not seen:   # the first time: the project's state as well
            old = _read_json(self.state_path)
            if old:
                with _FileLock(self.user_state_path):
                    raw = _read_json(self.user_state_path)
                    for pool, st in old.items():
                        if pool in self.catalogue:
                            raw.setdefault(f"{pool}@{self.key(pool)}", st)
                    atomic_write_json(self.user_state_path, raw)
        os.makedirs(self.dir, exist_ok=True)
        atomic_write_json(marker, {"ts": iso(self.clock()), "examined": len(all_lines)})

    def pool(self, provider):
        """The entry whose quota ``provider`` draws on."""
        return self.catalogue[provider].get("quota") or provider

    # periods

    def period_start(self, provider):
        provider = self.pool(provider)
        entry = self.catalogue[provider]
        free = entry.get("free") or {}
        period = free.get("period", "monthly")
        now = self.clock()
        if period == "daily":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "once":
            if free.get("expires_months"):
                state = self.state().get(provider, {})
                if state.get("period_start"):
                    return _date(state["period_start"])
                first = self.first_use(provider)
                if first is not None:
                    return first
            return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        reset = free.get("reset", "billing")
        state = self.state().get(provider, {})
        if reset == "billing" and state.get("period_start"):
            start = _date(state["period_start"])
            while start + _one_month(start) <= now:  # the reported period has ended
                start = start + _one_month(start)
            return start
        day = reset if isinstance(reset, int) else 1
        start = now.replace(day=min(day, 28), hour=0, minute=0, second=0, microsecond=0)
        if start > now:
            prev = (start.replace(day=1) - datetime.timedelta(days=1))
            start = prev.replace(day=min(day, 28), hour=0, minute=0, second=0, microsecond=0)
        return start

    def first_use(self, provider):
        """The time of the first unit counted for ``provider``'s quota, or None."""
        times = [_date(e["ts"]) for e in self.entries()
                 if e["provider"] in self.catalogue and self.pool(e["provider"]) == provider
                 and e.get("units") and e.get("source") not in ("estimate", "sync")]
        return min(times) if times else None

    def expired(self, provider):
        """True when a one-off free tier has passed its expiry date."""
        provider = self.pool(provider)
        months = (self.catalogue[provider].get("free") or {}).get("expires_months")
        if not months:
            return False
        start = self.period_start(provider)
        if start.year == 1970:
            return False
        return self.clock() >= _add_months(start, months)

    def local_used(self, provider):
        provider = self.pool(provider)
        start = self.period_start(provider)
        return sum(e["units"] for e in self.entries()
                   if e["provider"] in self.catalogue and self.pool(e["provider"]) == provider
                   and e.get("source") != "estimate"
                   and e.get("source") != "sync" and _date(e["ts"]) >= start)

    def used(self, provider):
        """(units used in the period, warning or None)."""
        provider = self.pool(provider)
        local = self.local_used(provider)
        st = self.state().get(provider, {})
        amount = (self.catalogue[provider].get("free") or {}).get("amount")
        reported = None
        if st.get("reported_left") is not None and amount is not None and st.get("reported_at"):
            if _date(st["reported_at"]) >= self.period_start(provider):
                reported = amount - st["reported_left"]
        if reported is None:
            return local, None
        warning = None
        biggest = max(local, reported)
        if biggest and abs(local - reported) / biggest > GAP_WARNING:
            warning = f"{provider}: local count {local:g}, provider count {reported:g}"
        return max(local, reported), warning

    def source(self, provider):
        """``provider`` when the provider's own count of this period is used,
        otherwise ``local`` (the ledger's count)."""
        provider = self.pool(provider)
        st = self.state().get(provider, {})
        if st.get("reported_left") is not None and st.get("reported_at") \
                and _date(st["reported_at"]) >= self.period_start(provider):
            return "provider"
        return "local"

    def operations(self, provider, reserve_percent):
        """{operation: how many the quota left still pays for}, for each operation
        the catalogue prices (search, read); None for a tier without a counted amount."""
        left = self.left(provider, reserve_percent)
        costs = self.catalogue[provider].get("costs") or {}
        out = {}
        for op in ("search", "read"):
            if op in costs:
                unit = self.cost(provider, op)
                out[op] = None if left is None else (whole(left, unit) if unit else None)
        return out

    def reserve(self, provider, reserve_percent):
        provider = self.pool(provider)
        amount = (self.catalogue[provider].get("free") or {}).get("amount")
        if amount is None:
            return 0
        share = amount * reserve_percent / 100
        # whole units are rounded up; dollars are not (10 % of 5 $ is 0.50 $, not 1 $)
        if self.catalogue[provider].get("unit") == "dollar":
            return round(share, 6)
        return math.ceil(share)

    def left(self, provider, reserve_percent):
        """Units left before the reserve, or None for a tier without a counted amount."""
        provider = self.pool(provider)
        if self.exhausted(provider) or self.expired(provider):
            return 0
        amount = (self.catalogue[provider].get("free") or {}).get("amount")
        cap = self.monthly_cap(provider)
        left = None
        if amount is not None:
            used, _w = self.used(provider)
            left = amount - used - self.reserve(provider, reserve_percent)
        if cap is not None:   # T53: the user's cap, never above the free tier
            in_month = cap - self.month_used(provider)
            left = in_month if left is None else min(left, in_month)
        return left

    def _settings(self):
        if self._config is None:
            self._config = False
            if self.project and self.environ is not None:
                try:
                    from probandia import config

                    self._config = config.load(self.project, self.environ, strict=False)
                except Exception:   # noqa: BLE001 — a bad settings file: the command that reads it says so
                    pass
        return self._config or None

    def monthly_cap(self, provider):
        """``providers.<id>.monthly_cap`` of the entry that pays, or None."""
        cfg = self._settings()
        if cfg is None:
            return None
        try:
            return cfg.get(f"providers.{self.pool(provider)}.monthly_cap")
        except KeyError:
            return None

    def month_used(self, provider):
        """Units used in the month the cap counts: the tier's period when it is monthly,
        else the calendar month (UTC)."""
        provider = self.pool(provider)
        if (self.catalogue[provider].get("free") or {}).get("period", "monthly") == "monthly":
            return self.used(provider)[0]
        start = self.clock().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return sum(e.get("units") or 0 for e in self.entries()
                   if e.get("provider") in self.catalogue and self.pool(e["provider"]) == provider
                   and e.get("source") not in ("estimate", "sync") and _date(e["ts"]) >= start)

    def fraction_left(self, provider, reserve_percent):
        """The share of the quota left, reserve kept, or None for a tier without a counted amount."""
        top = self.ceiling(provider)
        left = self.left(provider, reserve_percent)
        if not top or left is None:
            return None
        return max(0.0, left) / top

    def low(self, providers, reserve_percent, threshold=LOW):
        """[(entry that pays, whole percent left)] of ``providers`` under ``threshold``, one per quota."""
        out, pools = [], set()
        for p in providers:
            pool = self.pool(p)
            if pool in pools:
                continue
            pools.add(pool)
            share = self.fraction_left(pool, reserve_percent)
            if share is not None and share < threshold:
                out.append((pool, math.floor(share * 100)))
        return out

    def forecast(self, provider, reserve_percent, days=FORECAST_DAYS):
        """T63: when the quota runs out at the pace of the last ``days`` days. A dict:
        ``left``, ``rate`` (units a day), ``verdict`` — ``out`` (on ``date``), ``renews``
        or ``expires`` (first, on ``date``), ``idle`` (no use), ``spent`` — or None for
        a tier without a counted amount. Out means the engine stops: the reserve is kept."""
        pool = self.pool(provider)
        left = self.left(pool, reserve_percent)
        if left is None:
            return None
        now = self.clock()
        since = now - datetime.timedelta(days=days)
        units = sum(e.get("units") or 0 for e in self._counted(self.entries(), pool, since, now))
        rate = units / days
        out = {"left": left, "rate": rate, "verdict": None, "date": None}
        if left <= 0 or self.exhausted(pool) or self.expired(pool):
            out["verdict"] = "spent"
            return out
        if rate <= 0:
            out["verdict"] = "idle"
            return out
        when = now + datetime.timedelta(days=left / rate)
        free = self.catalogue[pool].get("free") or {}
        end = None if free.get("period") == "once" and not free.get("expires_months") else self.period_end(pool)
        if end is not None and when >= end:
            out["verdict"], out["date"] = ("expires" if free.get("period") == "once" else "renews"), end
        else:
            out["verdict"], out["date"] = "out", when
        return out

    def ceiling(self, provider):
        """The most the quota pays in its period: the free tier, or the monthly cap when lower."""
        provider = self.pool(provider)
        amount = (self.catalogue[provider].get("free") or {}).get("amount")
        cap = self.monthly_cap(provider)
        if cap is None:
            return amount
        return cap if amount is None else min(amount, cap)

    def exhausted(self, provider):
        provider = self.pool(provider)
        until = self.state().get(provider, {}).get("exhausted_until")
        return bool(until) and _date(until) > self.clock()

    def cost(self, provider, operation="search", calls=1):
        """The catalogue's cost of ``calls`` operations. A reading tier the entry
        does not price costs what the tier below it costs (``read_js`` → ``read``)."""
        from probandia.providers.catalogue import TIER_BELOW

        costs = self.catalogue[provider].get("costs") or {}
        op = operation
        while op not in costs and op in TIER_BELOW:
            op = TIER_BELOW[op]
        return costs.get(op, costs.get("search", 1)) * calls

    def mark_exhausted(self, provider, retry_after=None):
        """After a 429 from a provider without introspection: until Retry-After,
        or until the end of the period."""
        provider = self.pool(provider)
        state = self.state()
        st = state.setdefault(provider, {})
        if retry_after:
            until = self.clock() + datetime.timedelta(seconds=int(retry_after))
        else:
            until = self.period_end(provider)
        st["exhausted_until"] = iso(until)
        self.save_state(state)
        return until

    def period_end(self, provider):
        provider = self.pool(provider)
        free = self.catalogue[provider].get("free") or {}
        if free.get("period") == "once" and free.get("expires_months"):
            start = self.period_start(provider)
            if start.year != 1970:
                return _add_months(start, free["expires_months"])
        period = (self.catalogue[provider].get("free") or {}).get("period", "monthly")
        start = self.period_start(provider)
        if period == "daily":
            return start + datetime.timedelta(days=1)
        if period == "once":
            return self.clock() + datetime.timedelta(days=36500)
        return start + _one_month(start)

    def update_reported(self, provider, left=None, period_start=None, used=None):
        provider = self.pool(provider)
        state = self.state()
        st = state.setdefault(provider, {})
        if left is not None:
            st["reported_left"] = left
            st["reported_at"] = iso(self.clock())
        if period_start:
            st["period_start"] = iso(_date(period_start))
        if used is not None:
            st["used"] = used
        if left is not None and left > 0 and st.get("exhausted_until"):
            st.pop("exhausted_until")
        self.save_state(state)
        self.record(provider, "sync", 0, source="sync")

    # readings of the balances (T52)

    def _counted(self, entries, pool, since, until=None):
        """The lines of ``entries`` that use ``pool``'s quota after ``since``."""
        return [e for e in entries
                if e.get("provider") in self.catalogue and self.pool(e["provider"]) == pool
                and e.get("source") not in ("estimate", "sync") and _date(e["ts"]) > since
                and (until is None or _date(e["ts"]) <= until)]

    def sync_due(self, providers, daily=False):
        """The providers of ``providers`` whose balance is due to be read, one per quota:
        never read, or read more than a day ago (with ``daily``), or with 20 calls
        counted since their last reading. One whose reading failed waits an hour."""
        now, state, entries = self.clock(), self.state(), None
        out, pools = [], set()
        for p in providers:
            pool = self.pool(p)
            if pool in pools:
                continue
            pools.add(pool)
            st = state.get(pool, {})
            if st.get("sync_failed_at") and now - _date(st["sync_failed_at"]) < SYNC_RETRY:
                continue
            last = _date(st["synced_at"]) if st.get("synced_at") else None
            if daily and (last is None or now - last >= SYNC_DAILY):
                out.append(p)
                continue
            if last is not None:   # never read: the first new or resume of the day reads it
                entries = self.entries() if entries is None else entries
                if len(self._counted(entries, pool, last)) >= SYNC_EVERY_CALLS:
                    out.append(p)
        return out

    def reading(self, provider):
        """The balance last reported for ``provider``'s quota, before a new reading."""
        st = self.state().get(self.pool(provider), {})
        return {"left": st.get("reported_left"), "at": st.get("reported_at")}

    def synced(self, provider, before, ok=True):
        """Notes a reading of the balance, and returns the drift it shows, or None:
        the provider's balance dropped by ``drop`` since ``before`` while the ledger
        counted ``counted`` units; 10 % apart or more is a drift (another project, a
        connector the hooks do not see, the provider's site)."""
        pool = self.pool(provider)
        now = self.clock()
        state = self.state()
        st = state.setdefault(pool, {})
        if not ok:
            st["sync_failed_at"] = iso(now)
            self.save_state(state)
            return None
        st["synced_at"] = iso(now)
        st.pop("sync_failed_at", None)
        st.pop("drift", None)
        drift = None
        left, at, new = before.get("left"), before.get("at"), st.get("reported_left")
        if left is not None and at and new is not None and _date(at) >= self.period_start(pool):
            drop = left - new
            counted = sum(e.get("units") or 0 for e in self._counted(self.entries(), pool, _date(at), now))
            biggest = max(drop, counted)
            if drop >= 0 and biggest > 0 and abs(drop - counted) / biggest >= DRIFT:
                drift = {"percent": round(100 * abs(drop - counted) / biggest), "provider": round(drop, 6),
                         "counted": round(counted, 6), "since": at, "at": iso(now)}
                st["drift"] = drift
        self.save_state(state)
        return drift

    def drift(self, provider):
        """The drift the last reading of ``provider``'s balance showed, or None."""
        return self.state().get(self.pool(provider), {}).get("drift")


def whole(left, unit):
    """How many ``unit`` fit in ``left``, whole: in floating point 900 // 0.2 is 4499, here 4500."""
    if left == math.inf:
        return math.inf
    return math.floor(round(max(0, left) / unit, 6))


def _add_months(d, months):
    for _ in range(months):
        d = d + _one_month(d)
    return d


def _one_month(d):
    month = d.month % 12 + 1
    year = d.year + (1 if d.month == 12 else 0)
    try:
        nxt = d.replace(year=year, month=month)
    except ValueError:
        nxt = d.replace(year=year, month=month, day=28)
    return nxt - d


class Allocation:
    """The outcome of ``fit``: calls kept per provider, calls moved, and a stop."""

    def __init__(self):
        self.kept = {}      # provider -> calls
        self.moved = []     # (from, to, calls)
        self.dropped = {}   # provider -> calls that fit nowhere
        self.stop = None    # (provider, alternative or None)


def fit(ledger, wanted, order, reserve_percent, usable_ids, operation="search"):
    """Fits ``wanted`` ({provider: calls}) into the free quotas left. Calls that
    do not fit move to the next usable provider of ``order``; when nothing at
    all fits, ``stop`` names the first provider and the next free one."""
    alloc = Allocation()
    remaining = {}
    for p in usable_ids:
        left = ledger.left(p, reserve_percent)
        remaining[p] = math.inf if left is None else max(0.0, left)
    for provider, calls in wanted.items():
        queue = [provider] + [p for p in order if p != provider and p in remaining]
        todo = calls
        for p in queue:
            if todo <= 0:
                break
            unit = ledger.cost(p, operation)
            fits = todo if unit == 0 else int(min(todo, whole(remaining.get(p, 0), unit)))
            if fits > 0:
                alloc.kept[p] = alloc.kept.get(p, 0) + fits
                remaining[p] -= fits * unit
                if p != provider:
                    alloc.moved.append((provider, p, fits))
                todo -= fits
        if todo > 0:
            alloc.dropped[provider] = todo
    if not alloc.kept and wanted:
        first = next(iter(wanted))
        alt = next((p for p in order if p != first and remaining.get(p, 0) >= ledger.cost(p, operation)
                    and remaining.get(p, 0) > 0), None)
        alloc.stop = (first, alt)
    return alloc
