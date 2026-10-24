"""Inserting into ``commun/personnes.yaml`` without rewriting it (WS2-T4 to T6).

Each insertion adds lines at a place the scan finds; no existing line changes but
``meta.mis_a_jour``. The safety contract (WS2-T5): the data read before, plus the
additions planned, must be exactly the data read back from the new text, or
nothing is written (``Malformed``, status FAIL); the file must still be the one
read at the start, or nothing is written (``Changed``, status STOP). The write is
atomic and keeps the file's line endings.
"""
import copy
import datetime
import hashlib

from probandia.util import yamlio
from probandia.util.fs import atomic_write_text
from probandia.workshop.prototype import render, scan

BANNER = "  # Ajouts de Probandia — à reclasser"
LIST_KEYS = ("recherches", "evenements", "événements", "recensements")
PERSON_ORDER = ("id", "nom", "prenoms", "sexe", "generation", "statut", "volet", "chapitre", "rapport", "pere",
                "mere", "conjoint")


class Malformed(ValueError):
    """An insertion that cannot be made, or whose result would not read back as planned."""


class Changed(RuntimeError):
    """The file changed between its reading and its writing."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Writer:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as fh:
            raw = fh.read()
        self.sha = sha256(raw)
        self.text = raw.decode("utf-8")
        self.layout = scan.Layout(self.text)
        self.nl = self.layout.newline
        self.data = yamlio.loads(self.text) or {}
        self.expected = copy.deepcopy(self.data)
        self.inserts = []    # (line index, [lines without endings], late), in the order made
        self.replaced = {}   # line index -> new line without ending
        self.count = 0

    # where things are

    def _person(self, wid):
        p = self.layout.person(wid)
        data = next((x for x in self.expected.get("personnes") or [] if isinstance(x, dict) and x.get("id") == wid),
                    None)
        if p is None or data is None:
            raise Malformed(f"no person {wid} in personnes.yaml")
        return p, data

    def _new_key_at(self, p):
        from probandia.workshop import FACT_KEYS

        facts = [span for key, span in p.keys.items() if key in FACT_KEYS]
        if facts:
            return max(end for _, end in facts)
        if "note" in p.keys:
            return p.keys["note"][0]
        return p.end

    def _add(self, at, lines, late=False):
        self.inserts.append((at, lines, late))
        self.count += 1

    # the insertions

    def add_fact(self, wid, key, fact):
        """A fact of a person: a key it does not have yet, or an item of one of its lists."""
        p, data = self._person(wid)
        fact = dict(fact)
        if key in LIST_KEYS or isinstance(data.get(key), list):
            if key in p.items:
                self._add(p.items[key][-1][1], render.flow(fact, "      - "))
            elif key in data:
                raise Malformed(f"{wid}.{key} is not a list of flow maps")
            else:
                self._add(self._new_key_at(p), [f"    {key}:"] + render.flow(fact, "      - "))
            data.setdefault(key, []).append(fact)
            return len(data[key]) - 1
        if key in data:
            raise Malformed(f"{wid} already has {key}: a second one is a divergence, never an insertion")
        self._add(self._new_key_at(p), render.flow(fact, f"    {key}: "))
        data[key] = fact
        return None

    def add_union(self, union):
        union = dict(union)
        unions = self.layout.unions
        if unions:
            self._add(unions[-1][1], [""] + render.block(union))
        elif "unions" in self.layout.top:
            self._add(self.layout.top["unions"][0] + 1, [""] + render.block(union))
        else:
            self._add(len(self.layout.lines), ["", "unions:", ""] + render.block(union))
        if not isinstance(self.expected.get("unions"), list):
            self.expected["unions"] = []
        self.expected["unions"].append(union)
        return len(self.expected["unions"]) - 1

    def add_person(self, person, facts=()):
        """A person the workshop does not have, under the banner of additions to file
        by hand (WS-D10); ``facts``: [(key, fact)]."""
        person = dict(person)
        if any(isinstance(x, dict) and x.get("id") == person.get("id") for x in self.expected.get("personnes") or []):
            raise Malformed(f"{person.get('id')} is already in personnes.yaml")
        lines = [""] + render.block(person, order=PERSON_ORDER)
        whole = dict(person)
        for key, fact in facts:
            if key in LIST_KEYS:
                lines += [f"    {key}:"] + render.flow(fact, "      - ")
                whole.setdefault(key, []).append(dict(fact))
            else:
                lines += render.flow(fact, f"    {key}: ")
                whole[key] = dict(fact)
        if not any(text == BANNER for _, text in self.layout.banners) and \
                not any(BANNER in ls for _, ls, _ in self.inserts):
            lines = ["", BANNER] + lines
        if "personnes" not in self.layout.top:
            raise Malformed("personnes.yaml has no personnes")
        self._add(self.layout.persons_end, lines, late=True)   # after the last person's own new keys
        if not isinstance(self.expected.get("personnes"), list):
            self.expected["personnes"] = []
        self.expected["personnes"].append(whole)

    def add_refutation(self, wid, key, index, volet):
        """``volet_refute`` on a fact of the workshop, which stays (WS-D6): a line of its
        own, inside a flow map over several lines or in a union."""
        if key == "unions":
            target = (self.expected.get("unions") or [None] * (index + 1))[index]
            a, b = self.layout.unions[index]
            if not isinstance(target, dict) or "volet_refute" in target:
                raise Malformed(f"union {index}: nothing to refute, or refuted already")
            at = next((i + 1 for i in range(a, b) if self.layout.lines[i].startswith("    chapitre:")), b)
            self._add(at, [f"    volet_refute: {volet}"])
            target["volet_refute"] = volet
            return
        p, data = self._person(wid)
        target = data.get(key)
        if index is not None:
            target = target[index] if isinstance(target, list) and index < len(target) else None
            spans = p.items.get(key) or []
            a, b = spans[index] if index < len(spans) else (None, None)
        else:
            a, b = p.keys.get(key, (None, None))
        if not isinstance(target, dict) or a is None or "volet_refute" in target:
            raise Malformed(f"{wid}.{key}: no fact to refute there, or refuted already")
        if b - a < 2:
            raise Malformed(f"{wid}.{key}: a flow map on one line takes volet_refute only by rewriting it; "
                            "add it by hand")
        lines = [x.rstrip("\r\n") for x in self.layout.lines[a:b]]
        after = next((n for n in range(len(lines) - 1) if "chapitre:" in lines[n]), 0)
        if not lines[after].rstrip().endswith(","):
            raise Malformed(f"{wid}.{key}: not a flow map the scan knows")
        pad = " " * (lines[0].index("{") + 1)
        self._add(a + after + 1, [f"{pad}volet_refute: {volet},"])
        target["volet_refute"] = volet

    def replace_fact(self, wid, key, index, fact):
        """A fact of the workshop rewritten, on the user's express choice only (``push --accept``):
        the one insertion that changes lines."""
        fact = dict(fact)
        if key == "unions":
            a, b = self.layout.unions[index]
            self.expected["unions"][index] = fact
            new = render.block(fact)
        else:
            p, data = self._person(wid)
            a, b = p.items[key][index] if index is not None else p.keys[key]
            first = self.layout.lines[a]
            prefix = first[:first.index("{")]
            if index is None:
                data[key] = fact
            else:
                data[key][index] = fact
            new = render.flow(fact, prefix)
        for i in range(a, b):
            self.replaced[i] = None
        self.replaced[a] = new
        self.count += 1

    def touch(self, today=None):
        """``meta.mis_a_jour``: the one value of the workshop a push rewrites (WS2-T6)."""
        today = today or datetime.date.today()
        at = self.layout.updated
        if at is None:
            return
        self.replaced[at] = f"  mis_a_jour: {today.isoformat()}"
        self.expected.setdefault("meta", {})["mis_a_jour"] = yamlio.loads(f"k: {today.isoformat()}")["k"]

    # the result

    def result(self):
        lines = self.layout.lines
        at_line = {}
        for at, new, _ in sorted(self.inserts, key=lambda x: x[2]):   # stable: the order made, late ones last
            at_line.setdefault(at, []).extend(new)
        out = []
        for i in range(len(lines) + 1):
            if i in at_line:
                if out and not out[-1].endswith("\n"):
                    out[-1] += self.nl
                out += [x + self.nl for x in at_line[i]]
            if i < len(lines):
                line = lines[i]
                if i in self.replaced:
                    ending = line[len(line.rstrip("\r\n")):] or self.nl
                    new = self.replaced[i]
                    line = "" if new is None else "".join(x + self.nl for x in new) if isinstance(new, list) \
                        else new + ending
                out.append(line)
        return "".join(out)

    def check(self):
        """The new text, once the contract holds; raises Malformed otherwise."""
        text = self.result()
        try:
            after = yamlio.loads(text)
        except Exception as exc:  # noqa: BLE001 — any reading error is a malformed insertion
            raise Malformed(f"personnes.yaml would no longer read: {exc}") from exc
        if after != self.expected:
            raise Malformed("personnes.yaml would not read back as the insertions planned")
        return text

    def write(self):
        """Writes the insertions; returns the new sha256. Malformed (FAIL) or Changed
        (STOP) leave the file as it was."""
        text = self.check()
        with open(self.path, "rb") as fh:
            if sha256(fh.read()) != self.sha:
                raise Changed("personnes.yaml changed since it was read")
        atomic_write_text(self.path, text, newline=None)
        return sha256(text.encode("utf-8"))
