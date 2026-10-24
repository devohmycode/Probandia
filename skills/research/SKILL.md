---
name: research
description: The method of a Probandia research pass, from what is known to its close. Use it after `new`, `resume` or `fork` opened a pass, or for any step of one.
---

# Running a research pass

`new`, `resume` and `fork` open a pass; this skill runs the rest. Write the report's prose in the
research's language (`LANG=`), not the user's.

**Who runs it** (`RUN_MODE=`): `session`, you run every step but reading
views; `subagent`, start
one `orchestrator` subagent with the run's model and effort, the research id and
this skill; `team`, you are the orchestrator: read `team.md`. Every brief
follows `${CLAUDE_PLUGIN_ROOT}/skills/research/brief.md`, a `reader`'s
`reader.md` only. The other `.md` files
named here sit next to it.
On `STATUS=ASK`: the `ask` skill, then the command again.

## Steps

1. **Known.** `new` ran `known` and `plan`: their keys, `names=`, `places=`,
   `record_types=` are in its answer; never open its `DETAILS=`, nor
   `resume`'s on `DIGEST=changes`. Run them again only to change the
   target. Never open the report or an index. `NEGATIVES_DUE`,
   `LEADS` first. Never search again what a fact or valid negative settles;
   once the question is proven, no more search: a lead for `pass end --summary`.
   Before calling a finding new or a thing unknown: `known.md`.
2. **Plan.** After `resume`, `plan [--focus "<text>"]` aims at the last open
   hypothesis (`FOCUS=`), else at the question (`question list`); give the
   digest's lead as `--focus` when it points elsewhere. No search before it;
   `matrix=` types to do first. `WINDOW=` is the event sought's, from the
   fact given (`ANCHOR=`); correct it with `plan --window <from>-<to>`.
   `PLACES_UNKNOWN=`: `places "<name>"`, or `places guide "<name> (<department>)"`.
   `STATUS=STOP`: a free quota is spent; say so, use `ALTERNATIVE=`.
   `QUOTA_LOW=`: under 20 % left; spare it.
   `LOGIN_NEEDED=`: the `browser` skill, before any agent.
3. **Search.** **One salvo per turn**: independent calls (searches, reads,
   `variants`, `dates`, `places --as-of`) in one message; wait only for a call
   whose answer the next needs. `places guide <place>`: where its records of a
   date are. Before a script: `scripts.md`. **First salvo, free sources
   only**: archive runs (`archive find "<need>"`, `archive run
   <archive>.<operation> --args '<json>'`) and one `searcher` for the
   `NATIVE_PARALLEL` native web searches, one variant or place each, at most
   `NATIVE_LEFT` in the pass. **Later salvos**, where it fell short:
   `search "<query>"` (a free quota; after the first native search,
   `REASON=native-first`; `EXHAUSTED=`: spent, the next one took over),
   `--negative` to prove an absence. **One engine per question**: a second
   only after the first returned zero. Outside Claude Code, log each native
   search: `search --log-native --query "…" --urls-file <file>`. A pass with
   no web call is incomplete.
4. **Evidence.** `read <url> --question "…"`: a page that did not load is never
   "nothing found". Never read a list or results page whole: `--links
   "<word>"`, `--grep "<word>"`, `--select <block>`. A site's pages: `--map`,
   one by one `--crawl <n> --question`; a table as JSON:
   `--extract "<what>"`. **A register's views go to a
   `reader`** (one per register or act, brief: `reader.md`) once the
   register is known: cite the lines it returns; open its
   transcription, or a view (`TOKENS_EST=`), only for a `doubt=`. Never
   page views. An index or a tree is a lead (`index`). Before a
   negative: `negatives.md`. `login_required`: the `browser` skill.
5. **Propose, apply.** One proposal per pass in session mode: `propose
   --draft <research>` writes it (`DRAFT=`: sources transcribed, a search
   per register read, the subject); in the same salvo `propose --example
   facts,persons,sections`. Add at its end, never rewriting it, the facts,
   new persons and sections, then `propose <file> --apply`. Other parts:
   `--example hypotheses` (`errata`, `refutations`), copied, never the
   schema; `analyses`: `correlate`. A source carries its
   type and its fields, layers[] (`cite --form --type <type>`). A `record` fact needs
   an image or a transcription, a source, and the search that found it
   (archive, call number, views read, result, the negative for the other
   views; else `missing_search=`), an act's views all in `images`; one that
   concludes a question cites its `excerpt`, `{source: <src>, lines: a-b}` of
   its transcription and the reader's `region` (propose copies them) or
   `read <url> --quote <n>`: apply refuses a passage not found word for word. An `index` fact needs a source; a negative, a witness
   passed within `witness.max_age_hours`, its variants and its window. A fact
   found wrong goes in `refutations`: `refuted`, dated, never deleted.
   Read its 10-line summary, not the file. It applies, whole, only on
   `verdict=would-apply` (`APPLIED=true`); a refused file gives the line and
   column, a rejection its reasons: fix and propose again, or set it aside (a
   duplicate, a finding merged into yours): `apply <proposal> --drop
   "<reason>"`. Only you apply;
   field agents only propose, their `plan` only reads yours. `pass end`
   refuses a proposal neither applied nor dropped (`REASON=pending-proposals`).
6. **Report.** Write those sections with the `report` skill: no second proposal.
7. **Close.** `pass end --summary "<found>; <open lead>; …"` renders and runs
   `verify --light`; on `VERIFY=FAIL`, fix the listed rules, run it again. Its
   `;`-split leads open the next digest. `LEARN_CANDIDATES`, `MEMORY_CANDIDATES`:
   `learning.md`. Tell the user, in their
   language, what was found (each fact's status; a `doubtful=` name with
   its `[?]`), what is open, where the
   report is, `/probandia:resume`. Settle each decided question per
   `proofs.md`; all settled, ask the user about `close <research>`. After a pass that sums up,
   when the research restarts or changes subject: `volet open <research> --title …`.

`QUESTION=interrupted_pass` after `resume`: ask the user, `continue` or
`close` (ends the pass `interrupted`).

## Rules

- Never pay; never print an API key.
- A negative counts only with its witness: "not found in <source> for
  <window>", never "does not exist".
- Never write into `report/`, `index/` or `events.jsonl`: the engine does.
