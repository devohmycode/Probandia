"""Family trees: the graph of a family's persons, and its Mermaid form.

**Graph.** Persons and their parents (``parents.father``, ``parents.mother``);
a couple is the pair of parents of a child, or two spouses. A filiation link
rests on the child's birth (or baptism) fact, the strongest one: ``hypothesis``
makes it dotted, ``refuted`` removes it; a child with no birth fact has a link
deduced from elsewhere, dotted too (T250).

**Mermaid** (SPECS § 11.1)::

    flowchart TB
      P_leopold_hugo_1773["Léopold HUGO<br/>° 1773 † 1828"]:::record
      U_1(( )):::union
      P_leopold_hugo_1773 --> U_1
      U_1 --> P_victor_hugo_1802

- a node ``P_<slug>``, the usual given name and the surname in capitals, the years
  marked ``°`` (birth), ``x`` (marriage), ``†`` (death);
- its class is the status of the birth fact, or ``living`` for a masked person;
- a couple gets a union node ``U_<n>``: each parent points to it, it points to
  each child;
- at most 40 persons per block; a larger tree is cut by branch.
"""
from probandia.report.living import living_set

BLOCK_MAX = 40
BIRTH = ("birth", "baptism")
DEATH = ("death", "burial")
CLASSES = ("record", "index", "hypothesis", "living", "union")
STRENGTH = {"record": 0, "index": 1, "hypothesis": 2, "refuted": 3}
DOTTED = ("hypothesis", "deduced")   # T250: a filiation no record founds


def year(fact):
    value = ((fact or {}).get("date") or {}).get("value") or ""
    return value[:4].lstrip("-") if value else ""


def first(person, types):
    for t in types:
        for f in person.get("facts", []):
            if f["type"] == t and f.get("status") != "refuted":
                return f
    return None


def basis(person):
    """T250: the birth or baptism fact a person's filiation rests on, the strongest (record, index,
    hypothesis, refuted; the first of equal ones); None when the person has none."""
    births = [f for f in person.get("facts") or [] if f.get("type") in BIRTH]
    return min(births, key=lambda f: STRENGTH.get(f.get("status"), len(STRENGTH)), default=None)


class Tree:
    """The family graph, with living persons known."""

    def __init__(self, persons, living_years=100, today=None, living=None):
        self.persons = {p["id"]: p for p in persons}
        self.living = living if living is not None else living_set(persons, living_years, today)
        # a presumed-living person's id holds a name and a birth year: shared outputs use these
        self.public = {pid: f"living-{i}" for i, pid in enumerate(sorted(self.living), 1)}
        self.children = {}
        for p in persons:
            for role in ("father", "mother"):
                parent = (p.get("parents") or {}).get(role)
                if parent in self.persons and self.link(p["id"]) != "refuted":
                    self.children.setdefault(parent, []).append(p["id"])

    def pid(self, pid):
        """The id shown in shared outputs: ``living-<n>`` for a presumed-living person."""
        return self.public.get(pid, pid)

    def link(self, child):
        """``record``, ``hypothesis``, ``refuted`` or ``deduced``: what the filiation of a child rests on;
        ``deduced`` when no birth fact founds it (T250)."""
        birth = basis(self.persons[child])
        if birth is None:
            return "deduced"
        status = birth.get("status")
        if status in ("hypothesis", "refuted"):
            return status
        return "record"

    def dotted(self, child):
        """True when the filiation of a child is drawn dotted: a hypothesis, or deduced (T250)."""
        return self.link(child) in DOTTED

    def parents(self, pid):
        par = (self.persons.get(pid, {}).get("parents") or {})
        if self.link(pid) == "refuted":
            return None, None
        return (par.get("father") if par.get("father") in self.persons else None,
                par.get("mother") if par.get("mother") in self.persons else None)

    def status(self, pid):
        if pid in self.living:
            return "living"
        birth = first(self.persons[pid], BIRTH)
        return (birth or {}).get("status") or "hypothesis"

    def name(self, pid, living_label="Living person"):
        if pid in self.living:
            return living_label
        names = self.persons[pid].get("names") or {}
        given = names.get("usual") or names.get("given") or ""
        return " ".join(x for x in (given, (names.get("surname") or "").upper()) if x)

    def years(self, pid):
        if pid in self.living:
            return ""
        p = self.persons[pid]
        out = []
        b = year(first(p, BIRTH))
        if b:
            out.append(f"° {b}")
        m = year(first(p, ("marriage",)))
        if m:
            out.append(f"x {m}")
        d = year(first(p, DEATH))
        if d:
            out.append(f"† {d}")
        return " ".join(out)

    def ancestors(self, root, generations):
        """{sosa: person id}, Sosa 1 being the root."""
        out = {1: root}
        frontier = [1]
        for _gen in range(generations):  # only the known ancestors are visited
            nxt = []
            for n in frontier:
                father, mother = self.parents(out[n])
                for k, parent in ((2 * n, father), (2 * n + 1, mother)):
                    if parent:
                        out[k] = parent
                        nxt.append(k)
            frontier = nxt
            if not frontier:
                break
        return dict(sorted(out.items()))

    def descendants(self, root, generations):
        """[(person, depth)] in depth-first order."""
        out, seen = [], set()

        def walk(pid, depth):
            if pid in seen or depth > generations:
                return
            seen.add(pid)
            out.append((pid, depth))
            for c in sorted(self.children.get(pid, []), key=lambda c: (year(first(self.persons[c], BIRTH)), c)):
                walk(c, depth + 1)
        walk(root, 0)
        return out

    def simplified(self, root, up=2, down=1, limit=BLOCK_MAX):
        """The persons of a report's tree: the root, ``up`` generations up and
        ``down`` down, at most ``limit``."""
        down_ids = [pid for pid, _d in self.descendants(root, down)]
        co_parents = [p for child in down_ids[1:] for p in self.parents(child) if p]  # the spouses
        ids = list(dict.fromkeys(list(self.ancestors(root, up).values()) + co_parents + down_ids))
        return ids[:limit]


def _node(pid):
    return "P_" + pid.replace("-", "_")


def _shown(tree, pid):
    return _node(tree.pid(pid))


def _label(text):
    return text.replace('"', "'").replace("<", "&lt;")


def mermaid_block(tree, ids, living_label="Living person"):
    """One Mermaid flowchart for the persons ``ids`` (at most 40)."""
    ids = [pid for pid in ids if pid in tree.persons][:BLOCK_MAX]
    keep = set(ids)
    lines = ["flowchart TB"]
    for pid in ids:
        years = tree.years(pid)
        label = _label(tree.name(pid, living_label)) + (f"<br/>{years}" if years else "")
        lines.append(f'  {_shown(tree, pid)}["{label}"]:::{tree.status(pid)}')
    unions = {}
    for pid in ids:
        father, mother = tree.parents(pid)
        couple = tuple(x for x in (father, mother) if x in keep)
        if not couple:
            continue
        if couple not in unions:
            unions[couple] = f"U_{len(unions) + 1}"
            lines.append(f"  {unions[couple]}(( )):::union")
            for parent in couple:
                lines.append(f"  {_shown(tree, parent)} --> {unions[couple]}")
        arrow = "-.->" if tree.dotted(pid) else "-->"
        lines.append(f"  {unions[couple]} {arrow} {_shown(tree, pid)}")
    lines += ["  classDef record stroke-width:2px", "  classDef index stroke-width:1px",
              "  classDef hypothesis stroke-dasharray:5 5", "  classDef living fill:#eee,color:#555",
              "  classDef union width:6px,height:6px"]
    return "\n".join(lines)


def blocks(tree, root, limit=BLOCK_MAX):
    """Blocks of at most ``limit`` persons, cut by branch: the root's side, then
    each grandparent's branch upwards."""
    anc = tree.ancestors(root, 30)
    if len(anc) <= limit:
        return [tree.simplified(root, up=30, down=1, limit=limit)]
    out = [[anc[n] for n in sorted(anc) if n < 8]]  # the root, its parents and grandparents
    for g in range(4, 8):
        if g not in anc:
            continue
        branch = [pid for n, pid in sorted(anc.items()) if n >= g and _under(n, g)]
        while branch:
            out.append(branch[:limit])
            branch = branch[limit:]
    return out


def _under(n, g):
    while n > g:
        n //= 2
    return n == g


def markdown(tree, root, living_label="Living person", title=None):
    """``tree.md``: one Mermaid block per branch."""
    out = [f"# {title or tree.name(root, living_label)}", ""]
    for i, ids in enumerate(blocks(tree, root), start=1):
        if i > 1:
            out += [f"## {tree.name(ids[0], living_label)}", ""]
        out += ["```mermaid", mermaid_block(tree, ids, living_label), "```", ""]
    return "\n".join(out)


def data(tree, ids, living_label="Living person"):
    """Nodes and edges of a tree, masked where a person is presumed living."""
    keep = [pid for pid in ids if pid in tree.persons]
    nodes = [{"id": tree.pid(pid), "label": tree.name(pid, living_label), "years": tree.years(pid),
              "status": tree.status(pid), "living": pid in tree.living} for pid in keep]
    edges = []
    for pid in keep:
        father, mother = tree.parents(pid)
        for role, parent in (("father", father), ("mother", mother)):
            if parent in keep:
                edges.append({"from": tree.pid(parent), "to": tree.pid(pid), "role": role,
                              "link": tree.link(pid)})
    return {"nodes": nodes, "edges": edges}
