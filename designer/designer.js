/* Probandia — the report template designer (optimize.md § 4.7 to 4.11).
 *
 * One page, offline, no dependency. The settings build a template (contract 1,
 * see src/probandia/report/template.py); the preview fills it with the engine's
 * slots for the sample report, exactly as the engine fills it (fill() below
 * follows template.fill() step by step; the tests compare both with Node).
 */
"use strict";

const CONTRACT = 1;

const FONTS = {
  "system-sans": 'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif',
  "system-serif": 'Georgia, Cambria, "Times New Roman", Times, serif',
  "old-style": '"Iowan Old Style", "Palatino Linotype", "URW Palladio L", P052, serif',
  "humanist": 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "DejaVu Sans", sans-serif',
  "mono": 'ui-monospace, "Cascadia Code", Menlo, Consolas, monospace',
};

const STATUSES = ["record", "index", "hypothesis", "refuted"];

function defaults() {
  return {
    id: "my-template", name: "My template", version: "1", description: "",
    colors: { ink: "#1b1b1b", muted: "#4a4a4a", paper: "#ffffff", link: "#0b4f9c", rule: "#c8c8c8",
              heading: "#1b1b1b", note: "#fff7e0", noteRule: "#8a6100" },
    font: { body: "system-sans", headings: "same", size: 16, lineHeight: 1.55, embedded: null },
    layout: { width: 46, marginX: 1, marginTop: 2 },
    titlePage: { enabled: false, subtitle: "", logo: null },
    header: { text: "", research: false },
    footer: { generated: true, text: "" },
    toc: { position: "top", depth: 3 },
    statuses: {
      record: { color: "#1d6b3a", mark: "✓" }, index: { color: "#2a5d9f", mark: "◆" },
      hypothesis: { color: "#8a6100", mark: "?" }, refuted: { color: "#9b1c1c", mark: "✗" },
    },
    errata: { style: "box" },
    notes: "end",
    tree: { record: "#1d6b3a", index: "#2a5d9f", hypothesis: "#8a6100", line: "#555555" },
    print: { paper: "A4", margin: 18, chapterBreak: false },
  };
}

/* The templates shipped with the engine, besides default (4.11). */
const PRESETS = {
  "print": {
    id: "print", name: "Print", description: "Sober and serif, for paper: each chapter on a new page",
    colors: { ink: "#000000", muted: "#333333", paper: "#ffffff", link: "#1a1a1a", rule: "#999999",
              heading: "#000000", note: "#ffffff", noteRule: "#000000" },
    font: { body: "old-style", headings: "same", size: 15, lineHeight: 1.5, embedded: null },
    layout: { width: 40, marginX: 1, marginTop: 2 },
    toc: { position: "top", depth: 2 },
    statuses: {
      record: { color: "#1a1a1a", mark: "✓" }, index: { color: "#1a1a1a", mark: "◆" },
      hypothesis: { color: "#1a1a1a", mark: "?" }, refuted: { color: "#1a1a1a", mark: "✗" },
    },
    errata: { style: "rule" },
    tree: { record: "#000000", index: "#444444", hypothesis: "#666666", line: "#333333" },
    print: { paper: "A4", margin: 20, chapterBreak: true },
  },
  "family-book": {
    id: "family-book", name: "Family book", description: "A warm book: a title page, notes after each chapter",
    colors: { ink: "#2b2118", muted: "#5b4a3a", paper: "#fbf7ef", link: "#7a3e12", rule: "#d8c9b0",
              heading: "#5a3214", note: "#f3e6cc", noteRule: "#8a5a20" },
    font: { body: "old-style", headings: "system-serif", size: 17, lineHeight: 1.6, embedded: null },
    layout: { width: 42, marginX: 1.5, marginTop: 3 },
    titlePage: { enabled: true, subtitle: "", logo: null },
    footer: { generated: true, text: "" },
    toc: { position: "top", depth: 2 },
    statuses: {
      record: { color: "#2f5d1e", mark: "✓" }, index: { color: "#24527a", mark: "◆" },
      hypothesis: { color: "#7a5200", mark: "?" }, refuted: { color: "#8b1d1d", mark: "✗" },
    },
    errata: { style: "box" },
    notes: "chapter",
    tree: { record: "#2f5d1e", index: "#24527a", hypothesis: "#7a5200", line: "#6b5a48" },
    print: { paper: "A4", margin: 22, chapterBreak: true },
  },
  "high-contrast": {
    id: "high-contrast", name: "High contrast", description: "Black on white, large type, strong marks",
    colors: { ink: "#000000", muted: "#000000", paper: "#ffffff", link: "#0000b3", rule: "#000000",
              heading: "#000000", note: "#ffffff", noteRule: "#000000" },
    font: { body: "humanist", headings: "same", size: 19, lineHeight: 1.7, embedded: null },
    layout: { width: 44, marginX: 1, marginTop: 2 },
    statuses: {
      record: { color: "#005a00", mark: "✓" }, index: { color: "#00308f", mark: "◆" },
      hypothesis: { color: "#6b3d00", mark: "?" }, refuted: { color: "#a00000", mark: "✗" },
    },
    errata: { style: "box" },
    tree: { record: "#005a00", index: "#00308f", hypothesis: "#6b3d00", line: "#000000" },
  },
};

function merge(base, extra) {
  const out = JSON.parse(JSON.stringify(base));
  for (const [k, v] of Object.entries(extra || {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object") {
      out[k] = merge(out[k], v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function preset(id) {
  return merge(defaults(), PRESETS[id]);
}

/* escaping, as Python's html.escape */

function esc(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

function unesc(text) {
  return String(text).replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

/* colours (4.8: WCAG AA) */

function luminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

function contrast(a, b) {
  const la = luminance(a), lb = luminance(b);
  if (la === null || lb === null) return null;
  const hi = Math.max(la, lb), lo = Math.min(la, lb);
  return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
}

/* [pair name, foreground, background, minimum] */
function contrastPairs(s) {
  const c = s.colors;
  const out = [["text", c.ink, c.paper, 4.5], ["secondary text", c.muted, c.paper, 4.5],
               ["links", c.link, c.paper, 4.5], ["headings", c.heading, c.paper, 4.5],
               ["errata", c.ink, c.note, 4.5]];
  for (const k of STATUSES) out.push([`status ${k}`, s.statuses[k].color, c.paper, 4.5]);
  return out.map(([name, fg, bg, min]) => {
    const ratio = contrast(fg, bg);
    return { name, fg, bg, ratio, ok: ratio !== null && ratio >= min };
  });
}

/* the template (decision 4.1) */

function cssString(text) {
  return '"' + String(text).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, " ") + '"';
}

function stack(s, which) {
  const key = which === "headings" && s.font.headings !== "same" ? s.font.headings : s.font.body;
  const base = FONTS[key] || FONTS["system-sans"];
  return s.font.embedded && which === "body" ? `"${s.font.embedded.name}", ${base}` : base;
}

function css(s) {
  const c = s.colors, t = s.tree, L = s.layout;
  const lines = [];
  if (s.font.embedded) {
    lines.push(`@font-face { font-family: "${s.font.embedded.name}"; src: url(${s.font.embedded.dataUrl}); ` +
               "font-display: swap; }");
  }
  lines.push(
    `body { --ink: ${c.ink}; --muted: ${c.muted}; --paper: ${c.paper}; --link: ${c.link}; --rule: ${c.rule};`,
    `  --heading: ${c.heading}; --note: ${c.note}; --note-rule: ${c.noteRule};`,
    `  margin: 0; background: var(--paper); color: var(--ink);`,
    `  font: ${s.font.size}px/${s.font.lineHeight} ${stack(s, "body")}; }`,
    `article { max-width: ${L.width}rem; margin: 0 auto; padding: ${L.marginTop}rem ${L.marginX}rem 4rem; }`,
    `h1, h2, h3, h4 { font-family: ${stack(s, "headings")}; color: var(--heading); }`,
    "h1 { font-size: 1.8rem; line-height: 1.25; }",
    "h2 { font-size: 1.4rem; margin-top: 2.2rem; border-bottom: 1px solid var(--rule); }",
    "h3 { font-size: 1.15rem; margin-top: 1.6rem; }",
    "h4 { font-size: 1rem; margin-top: 1.2rem; }",
    "a { color: var(--link); }",
    "a:focus { outline: 2px solid var(--link); outline-offset: 2px; }",
    "nav ol { list-style: none; padding-left: 1rem; }",
    "nav > ol { padding-left: 0; }");
  if (s.toc.depth < 3) lines.push(`nav ${"ol ".repeat(s.toc.depth + 1).trim()} { display: none; }`);
  lines.push(
    "table { border-collapse: collapse; margin: 1rem 0; }",
    "th, td { border: 1px solid var(--rule); padding: .3rem .6rem; text-align: left; vertical-align: top; }",
    "pre { background: rgba(127, 127, 127, .12); padding: .8rem; overflow-x: auto; }");
  if (s.errata.style === "box") {
    lines.push("aside.erratum { background: var(--note); border-left: 4px solid var(--note-rule); " +
               "padding: .5rem 1rem; margin: 1rem 0; }");
  } else if (s.errata.style === "rule") {
    lines.push("aside.erratum { border-top: 1px solid var(--note-rule); border-bottom: 1px solid var(--note-rule); " +
               "padding: .4rem 0; margin: 1rem 0; font-style: italic; }");
  } else {
    lines.push("aside.erratum { margin: 1rem 0; font-style: italic; }");
  }
  lines.push(
    "figure.tree { margin: 1rem 0; overflow-x: auto; }",
    "figure.tree svg { max-width: 100%; height: auto; " +
      `--record: ${t.record}; --index: ${t.index}; --hypothesis: ${t.hypothesis}; --line: ${t.line}; ` +
      `--ink: ${c.ink}; --paper: ${c.paper}; }`,
    ".notes { font-size: .9rem; color: var(--muted); border-top: 1px solid var(--rule); margin-top: 3rem; }",
    ".chapter-notes { margin-top: 1.5rem; }");
  for (const k of STATUSES) {
    const st = s.statuses[k];
    // colour and mark together: never the colour alone (4.8)
    lines.push(`.status-${k}::before { content: ${cssString(st.mark + " ")}; color: ${st.color}; font-weight: bold; }`);
    lines.push(`sup.status-${k} a, li.status-${k}::marker { color: ${st.color}; }`);
  }
  lines.push(
    ".report-header, .report-footer { max-width: " + L.width + "rem; margin: 0 auto; padding: .6rem " +
      L.marginX + "rem; color: var(--muted); font-size: .85rem; }",
    ".report-header { border-bottom: 1px solid var(--rule); }",
    ".report-footer { border-top: 1px solid var(--rule); }");
  if (s.titlePage.enabled) {
    lines.push(".title-page { min-height: 70vh; display: flex; flex-direction: column; justify-content: center; " +
               "align-items: center; text-align: center; }",
               ".title-page .logo { max-width: 10rem; max-height: 10rem; margin-bottom: 1.5rem; }",
               ".title-page h1 { font-size: 2.4rem; }",
               ".title-page .subtitle { color: var(--muted); font-size: 1.2rem; }");
  }
  lines.push(
    `@page { size: ${s.print.paper}; margin: ${s.print.margin}mm; }`,
    "@media print {",
    "  body { font-size: 11pt; }",
    "  article { max-width: none; padding: 0; }",
    "  nav { break-after: page; }",
    "  a { color: var(--ink); text-decoration: none; }",
    "  h2, h3, h4 { break-after: avoid; }",
    "  aside.erratum { border: 1px solid var(--note-rule); }");
  if (s.titlePage.enabled) lines.push("  .title-page { min-height: auto; break-after: page; padding-top: 30%; }");
  if (s.print.chapterBreak) lines.push("  article > section { break-before: page; }");
  lines.push("}");
  return lines.join("\n");
}

/* The designer's settings, kept in the template so that it can be opened again
 * (4.9); the logo and the font stay in the page only once, where they are used. */
function settingsMeta(s) {
  const copy = JSON.parse(JSON.stringify(s));
  if (copy.titlePage.logo) copy.titlePage.logo = "embedded";
  if (copy.font.embedded) copy.font.embedded = { name: copy.font.embedded.name, dataUrl: "embedded" };
  return esc(JSON.stringify(copy));
}

const SAMPLE = {
  title: "Who were the parents of Louis Marchand?",
  toc: '<nav aria-labelledby="toc-title"><h2 id="toc-title">Contents</h2>\n<ol>\n' +
       '<li><a href="#s-1">1 Pass 1</a></li>\n</ol>\n</nav>',
  body: '<section id="s-1">\n<h2>1 Pass 1</h2>\n<p>Louis MARCHAND, birth, 1898, Bourg-Vert' +
        '<sup class="status-record"><a href="#fn-1">1</a></sup>.</p>\n</section>',
  notes: '<section class="notes" aria-label="Notes"><ol>\n<li id="fn-1" class="status-record">Record. ' +
         "Departmental archives of Valombre, civil registers, Bourg-Vert, birth 57.</li>\n</ol></section>",
};

function slot(name, sample) {
  return `<!-- probandia:slot ${name} -->${sample}<!-- /probandia:slot -->`;
}

function label(msgid) {
  return `<!-- probandia:label ${msgid} -->${esc(msgid)}<!-- /probandia:label -->`;
}

function build(s) {
  const out = [
    "<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<meta name="probandia:id" content="${esc(s.id)}">`,
    `<meta name="probandia:name" content="${esc(s.name)}">`,
    `<meta name="probandia:version" content="${esc(s.version)}">`,
    `<meta name="probandia:contract" content="${CONTRACT}">`,
  ];
  if (s.description) out.push(`<meta name="probandia:description" content="${esc(s.description)}">`);
  out.push(`<meta name="probandia:notes" content="${s.notes === "chapter" ? "chapter" : "end"}">`,
           `<meta name="probandia:designer" content="${settingsMeta(s)}">`,
           "<!-- probandia:slot head -->", '<meta name="generator" content="Probandia">',
           `<title>${esc(SAMPLE.title)}</title>`, "<!-- /probandia:slot -->",
           "<style>", css(s), "</style>", "</head>", "<body>");
  if (s.header.text || s.header.research) {
    let h = '<header class="report-header">' + esc(s.header.text);
    if (s.header.research) {
      h += (s.header.text ? " · " : "") + '<span class="research">' +
           slot("research", "2026-09-01-ancestors-of-louis-marchand") + "</span>";
    }
    out.push(h + "</header>");
  }
  out.push("<article>");
  if (s.titlePage.enabled) {
    out.push('<div class="title-page">');
    if (s.titlePage.logo) out.push(`<img class="logo" src="${s.titlePage.logo}" alt="">`);
    out.push(slot("title", `<h1>${esc(SAMPLE.title)}</h1>`));
    if (s.titlePage.subtitle) out.push(`<p class="subtitle">${esc(s.titlePage.subtitle)}</p>`);
    out.push("</div>");
  } else {
    out.push(slot("title", `<h1>${esc(SAMPLE.title)}</h1>`));
  }
  if (s.toc.position === "top") out.push("<!-- probandia:slot toc -->", SAMPLE.toc, "<!-- /probandia:slot -->");
  out.push("<!-- probandia:slot body -->", SAMPLE.body, "<!-- /probandia:slot -->",
           "<!-- probandia:slot notes -->", SAMPLE.notes, "<!-- /probandia:slot -->",
           slot("manual", ""), "</article>");
  if (s.footer.generated || s.footer.text) {
    let f = '<footer class="report-footer">';
    if (s.footer.generated) f += label("Generated") + " " + slot("generated", "3 September 2026");
    if (s.footer.text) f += (s.footer.generated ? " · " : "") + esc(s.footer.text);
    out.push(f + "</footer>");
  }
  out.push("</body>", "</html>");
  return out.join("\n") + "\n";
}

/* reading a template (4.9) */

function metas(text) {
  const out = {};
  const rx = /<meta name="probandia:([a-z-]+)" content="([^"]*)">/g;
  let m;
  while ((m = rx.exec(text))) if (!(m[1] in out)) out[m[1]] = unesc(m[2]);
  return out;
}

/* The settings of a template the designer wrote, or null for a hand-made one. */
function read(text) {
  const meta = metas(text);
  if (!meta.designer) return null;
  let s;
  try {
    s = merge(defaults(), JSON.parse(meta.designer));
  } catch (e) {
    return null;
  }
  if (s.titlePage.logo === "embedded") {
    const m = /<img class="logo" src="([^"]*)"/.exec(text);
    s.titlePage.logo = m ? m[1] : null;
  }
  if (s.font.embedded && s.font.embedded.dataUrl === "embedded") {
    const m = /@font-face \{ font-family: "[^"]*"; src: url\(([^)]*)\)/.exec(text);
    s.font.embedded = m ? { name: s.font.embedded.name, dataUrl: m[1] } : null;
  }
  return s;
}

/* filling: the same steps as template.fill() in the engine */

function fill(text, slots, labels, lang) {
  text = text.replace(/^[ \t]*<meta name="probandia:[a-z-]+" content="[^"]*">[ \t]*\n/gm, "");
  const tag = /<html\b[^>]*>/i.exec(text);
  if (tag) {
    const value = ` lang="${esc(lang)}"`;
    const t = tag[0];
    const nt = /\slang="[^"]*"/.test(t) ? t.replace(/\slang="[^"]*"/, value) : t.slice(0, -1) + value + ">";
    text = text.slice(0, tag.index) + nt + text.slice(tag.index + t.length);
  }
  text = text.replace(/<!-- probandia:label ([\s\S]+?) -->([\s\S]*?)<!-- \/probandia:label -->/g, (m, id) => {
    const key = id.trim();
    const entry = labels[key];
    return esc(entry && entry[lang] ? entry[lang] : key);
  });
  const rx = /<!-- probandia:slot ([a-z-]+) -->([\s\S]*?)<!-- \/probandia:slot -->/g;
  const out = [];
  let pos = 0, m;
  while ((m = rx.exec(text))) {
    const value = slots[m[1]] || "";
    let start = m.index, end = m.index + m[0].length;
    if (!value) {
      const lineStart = text.lastIndexOf("\n", start - 1) + 1;
      if (!text.slice(lineStart, start).trim() && text.startsWith("\n", end)) {
        start = lineStart;
        end = end + 1;
      }
    }
    out.push(text.slice(pos, start), value);
    pos = end;
  }
  out.push(text.slice(pos));
  return out.join("");
}

const Designer = { CONTRACT, FONTS, STATUSES, PRESETS, defaults, preset, merge, esc, contrast, contrastPairs,
                   css, build, read, metas, fill };

if (typeof module !== "undefined" && module.exports) {
  module.exports = Designer;
} else if (typeof window !== "undefined") {
  window.Designer = Designer;
}
