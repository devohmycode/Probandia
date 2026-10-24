# Settling a question: the proof standard

A conclusion stands only when the five elements of the Genealogical Proof
Standard are met, against what the question says will answer it (`question
edit <Q> --standard "<…>"`, set it first). Before answering:

1. **Reasonably exhaustive search** (V-18). `places guide <place>`:
   jurisdictions and repositories. `matrix`: search each type to do, justify
   each gap, or `matrix justify <Q> <type> --reason "<why>"`; V-18 refuses a hole.
2. **Complete and accurate citations** (V-2, V-17, V-19). `cite --type <type>`:
   a typed source with the fields its model requires; a record fact that
   answers quotes its passage (`{source, lines}`, `read --quote`), checked word
   for word; one kept only in `work/` gets a warning.
3. **Analysis and correlation** (V-15, V-14), 4. **conflicts resolved**
   (V-15). `correlate` lists the facts that disagree, and the timeline the
   dates that clash. `correlate open`, `apply`; give each piece of evidence
   its three axes and informant, a copy its original (`derived_from`): the same
   informant or a copy is no second source; `correlate resolve <id> --value …
   --reasoning …`, `apply`.
   Two sources that disagree with no third to decide: `correlate diverge <id>
   --reason …`; both stay side by side, and the question cannot be answered
   while it stands.
5. **Soundly reasoned conclusion** (V-16). A question that `proof list` says
   needs an argument (identity, indirect or negative evidence, conflict):
   1. `proof draft <Q>`; write the analysis, the conflicts and the conclusion
      in the file it names, plain and short. `proof submit <id>`.
   2. Review. In a team or with a subagent: start the `contradictor` on `proof
      show <id>`, save its return as it is to a file in `work/`, then `proof
      review <id> --objections <file> --by contradictor`. In session mode,
      alone: in a later turn, read your argument as the contradictor would and
      record it with `--by session`; the report says that review was not
      independent. Never write `--by contradictor` for your own review.
   3. Each objection: `proof answer <id> <n> --text "…"`, or `--dismiss
      --reason "…"`. Then `proof accept <id>`, and `question answer`.

A question decided: `question answer <Q> --conclusion <facts>`; given up:
`question unresolved <Q> --reason "<why>"`. `verify --standard` shows each
question's elements and what each lacks. With `proof.standard` strict, a
question that does not conform fails it and keeps `close` from closing the
research; a partial one does not. An answered question gets a computed
confidence (proved, probable, possible, unsupported) and its reasons; it
blocks nothing.

"Established" means the data say so, not that the reasoning is right: read
the sources, and say so when they leave a doubt; Probandia does not replace
the genealogist's judgement. Tell the user which concluding facts no one has
checked (the digest's `UNCHECKED=`): only they can, at their terminal
(`fact check <fact> --by … --looked …`).
