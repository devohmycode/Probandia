# Report templates

The HTML report is a template filled by the engine: style, title page, header,
footer, where the notes go. Probandia ships `default`, `print`,
`family-book`, `high-contrast` and `habillage`; the project (`templates/`) and the user
(`templates.dir`) can add their own.

Which one: `render --template <id>`, else the research's `template`, the
family's, the setting `report.template` (project, then user), else `default`.
`render` says `TEMPLATE=` and `TEMPLATE_ORIGIN=`.

| Command | Does |
|---|---|
| `template list` | the templates; `*` marks the one in effect |
| `template show <id>` | its version, slots, notes, check |
| `template check <id or file>` | refuses scripts, external resources, missing slots |
| `template import <file> [--scope user]` | checks, then installs it |
| `template export <id> <file>` | a copy to share |
| `template use <id> [--level research\|family\|project\|user]` | chooses it |
| `template designer` | opens the designer, offline, for the user |
| `render --all [--family <slug>]` | renders every report again |

Never write a template yourself: the user makes it in the designer, or brings
it. After `template use`, run `render --all`. `verify` rule V-13 fails when a
report's template was removed or changed: render again.

Timelines are `figure.timeline`: a template colours them by setting `--record`,
`--index`, `--hypothesis` and `--line` on `figure.timeline svg`.
