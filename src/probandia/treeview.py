"""``tree.html`` and ``tree.md`` of a family (SPECS § 11.3).

``tree.html`` is one file that opens offline: family-chart and d3, at the
versions pinned in ``vendor-js/``, are inlined, and the data is embedded as JSON
(``<script type="application/json" id="tree-data">``). Pan, zoom and click to
re-centre come from family-chart; the page adds the legend of statuses, dotted
hypotheses and masked living persons. Without JavaScript, the SVG ancestor chart
shows inside ``<noscript>``.

``tree.md`` holds one Mermaid block per branch; the root's branches are cut at
the grandparents.
"""
import html
import json
import re

from probandia import svg, trees
from probandia import paths
from probandia.report import labels as L

PAGE_CSS = """
:root { --record: #1d6b3a; --index: #2a5d9f; --hypothesis: #8a6100; --living: #666666; }
body { margin: 0; font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: #1b1b1b;
  background: #ffffff; }
header { padding: .6rem 1rem; border-bottom: 1px solid #ccc; }
h1 { font-size: 1.3rem; margin: .2rem 0; }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 1rem; padding: 0; margin: .3rem 0; }
.legend li::before { content: ""; display: inline-block; width: 1.4em; height: .9em; margin-right: .4em;
  border: 2px solid currentColor; vertical-align: middle; }
.legend .record { color: var(--record); } .legend .index { color: var(--index); }
.legend .hypothesis { color: var(--hypothesis); } .legend .hypothesis::before { border-style: dashed; }
.legend .living { color: var(--living); }
#FamilyChart { width: 100%; height: calc(100vh - 6rem); background: #fafafa; color: #1b1b1b; }
.pb-card { padding: 6px 10px; border: 2px solid var(--line, #555); border-radius: 6px; background: #fff;
  min-width: 150px; font-size: 13px; color: #1b1b1b; }
.pb-card.record { --line: var(--record); } .pb-card.index { --line: var(--index); }
.pb-card.hypothesis { --line: var(--hypothesis); border-style: dashed; }
.pb-card.living { --line: var(--living); background: #eee; }
.pb-card .years { font-size: 11px; color: #444; }
noscript svg { max-width: 100%; height: auto; }
#FamilyChart .link { stroke: #777777; }
.help { margin: .2rem 0; font-size: .85rem; color: #444; }
#FamilyChart [data-pb-card]:focus { outline: none; }
#FamilyChart [data-pb-card]:focus-visible .pb-card { outline: 3px solid #0b57d0; outline-offset: 2px; }
"""

INIT = """
(function () {
  var data = JSON.parse(document.getElementById("tree-data").textContent);
  var chart = f3.createChart("#FamilyChart", data.people)
    .setTransitionTime(300).setCardXSpacing(230).setCardYSpacing(130)
    .setSingleParentEmptyCard(false);
  chart.setCardHtml()
    .setCardInnerHtmlCreator(function (d) {
      var p = d.data.data;
      var div = document.createElement("div");
      div.className = "pb-card " + p.status;
      var name = document.createElement("div");
      name.textContent = p.label;
      var years = document.createElement("div");
      years.className = "years";
      years.textContent = p.years;
      div.appendChild(name);
      div.appendChild(years);
      return div.outerHTML;
    });
  chart.updateMainId(data.root);
  chart.updateTree({initial: true});

  // T123: every person reachable by Tab, the arrows to the nearest card that way, Enter or Space to re-centre
  var box = document.getElementById("FamilyChart");
  function cards() {
    return Array.prototype.filter.call(box.querySelectorAll(".pb-card"), function (c) {
      return c.getBoundingClientRect().width > 0;
    }).map(function (c) { return c.closest(".card") || c.parentNode; });
  }
  function label() {
    cards().forEach(function (card) {
      if (card.hasAttribute("data-pb-card")) return;
      var inner = card.querySelector(".pb-card");
      card.setAttribute("data-pb-card", "");
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", Array.prototype.map.call(inner.children, function (c) {
        return c.textContent.trim();
      }).filter(Boolean).join(", "));
    });
  }
  function nearest(from, key) {
    var a = from.getBoundingClientRect(), best = null, score = Infinity;
    cards().forEach(function (card) {
      if (card === from) return;
      var b = card.getBoundingClientRect();
      var dx = (b.left + b.width / 2) - (a.left + a.width / 2), dy = (b.top + b.height / 2) - (a.top + a.height / 2);
      var ahead = {ArrowRight: dx > 1, ArrowLeft: dx < -1, ArrowDown: dy > 1, ArrowUp: dy < -1}[key];
      var along = key === "ArrowRight" || key === "ArrowLeft" ? Math.abs(dx) : Math.abs(dy);
      var across = key === "ArrowRight" || key === "ArrowLeft" ? Math.abs(dy) : Math.abs(dx);
      if (ahead && along + 2 * across < score) { best = card; score = along + 2 * across; }
    });
    return best;
  }
  box.addEventListener("keydown", function (e) {
    var card = e.target.closest ? e.target.closest("[data-pb-card]") : null;
    if (!card) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      card.querySelector(".pb-card").click();
    } else if (e.key.indexOf("Arrow") === 0) {
      var next = nearest(card, e.key);
      if (next) { e.preventDefault(); next.focus(); }
    }
  });
  new MutationObserver(label).observe(box, {childList: true, subtree: true});
  label();
})();
"""


def _vendor(*parts):
    with open(paths.data("vendor-js", *parts), encoding="utf-8") as fh:
        return fh.read()


def _script(text):
    """A script's text that cannot close its block: ``</script`` in any case (the HTML parser's)."""
    return re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)


def _json(data):
    """JSON for a ``<script>`` block: every ``<`` escaped, so no name closes the block or opens a comment."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")


def people(tree, ids, living_label):
    """family-chart's data: ``{id, data, rels: {parents, spouses, children}}``."""
    keep = set(ids)
    out = []
    for pid in ids:
        p = tree.persons[pid]
        father, mother = tree.parents(pid)
        parents = [x for x in (father, mother) if x in keep]
        spouses = sorted({s["person"] for s in p.get("spouses", []) if s.get("person") in keep})
        for c in tree.children.get(pid, []):
            other = [x for x in tree.parents(c) if x and x != pid and x in keep]
            spouses = sorted(set(spouses) | set(other))
        children = sorted(c for c in tree.children.get(pid, []) if c in keep)
        sex = p.get("sex")
        shown = tree.pid
        out.append({"id": shown(pid), "data": {"label": tree.name(pid, living_label), "years": tree.years(pid),
                                               "status": tree.status(pid),
                                               "gender": "U" if pid in tree.living else (sex if sex in ("M", "F") else "U")},
                    "rels": {"parents": [shown(x) for x in parents], "spouses": [shown(x) for x in spouses],
                             "children": [shown(x) for x in children]}})
    return out


def html_page(tree, root, t, lang="en", title=None):
    """The whole ``tree.html``."""
    living_label = t(L.LIVING_PERSON)
    ids = tree.simplified(root, up=30, down=3, limit=10 ** 6)
    title = title or f"{t(L.TREE)} — {tree.name(root, living_label)}"
    data = {"root": tree.pid(root), "people": people(tree, ids, living_label)}
    legend = "".join(f'<li class="{k}">{html.escape(t(L.LEGEND[k]))}</li>'
                     for k in ("record", "index", "hypothesis", "living"))
    fallback = svg.ancestors(tree, root, 5, living_label, t(L.ANCESTORS_OF))
    return "\n".join([
        "<!DOCTYPE html>", f'<html lang="{html.escape(lang)}">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        f"<style>\n{_vendor('family-chart', 'family-chart.css')}\n{PAGE_CSS}\n</style>", "</head>", "<body>",
        f"<header><h1>{html.escape(title)}</h1><ul class=\"legend\">{legend}</ul>",
        f'<p class="help" id="tree-help">{html.escape(t(L.TREE_HELP))}</p></header>',
        f'<main><div id="FamilyChart" class="f3" role="group" aria-label="{html.escape(title)}" '
        'aria-describedby="tree-help"></div></main>',
        f"<noscript>{fallback}</noscript>",
        '<script type="application/json" id="tree-data">'
        + _json(data) + "</script>",
        f"<script>{_script(_vendor('d3', 'd3.min.js'))}</script>",
        f"<script>{_script(_vendor('family-chart', 'family-chart.min.js'))}</script>",
        f"<script>{INIT}</script>", "</body>", "</html>", ""])


def default_root(persons, events=()):
    """The root of the last ``branch.added``, else the person with the most known ancestors."""
    for e in reversed(list(events)):
        if e.get("type") == "branch.added" and (e.get("payload") or {}).get("root"):
            return e["payload"]["root"]
    tree = trees.Tree(persons, living=set())
    return max(sorted(tree.persons), key=lambda pid: len(tree.ancestors(pid, 10)))
