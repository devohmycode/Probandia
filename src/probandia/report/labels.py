"""The labels of reports, as gettext message ids: English ids, translated into
the research's language (French ships with the engine)."""
from probandia.i18n import N_

CONTENTS = N_("Contents")
PASS = N_("Pass {n}")
ERRATA = N_("Errata")
ERRATUM = N_("Erratum {id}")
ERRATUM_NOTICE = N_("Erratum {id} — pass {n}: {wrong} → {correction}. Cause: {cause}. {detection}")
CORRECTION = N_("Correction")
CAUSE = N_("Cause")
DETECTED_BY = N_("Detected by")
METHOD = N_("Method")
TOOLS = N_("web {web} · MCP {mcp} · archives {archive} · engine {engine}")
SOURCES = N_("Sources")
ACT_VIEWS = N_("Views of the acts")
ACT_VIEW = N_("View of the act: {citation}")
VIEW_LEFT_OUT = {"rights": N_("View not shown, its rights do not allow a copy: {file}"),
                 "missing": N_("View not found in the family folder: {file}"),
                 "size": N_("View not shown, the report would pass its size limit: {file}")}
REVISION_HISTORY = N_("Revision history")
LIVING_PERSON = N_("Living person")
GENERATED = N_("Generated")
TREE = N_("Tree")
ANCESTORS_OF = N_("Ancestors of {name}")       # T123: what a screen reader says of a chart
DESCENDANTS_OF = N_("Descendants of {name}")
TREE_HELP = N_("Tab goes from person to person, the arrows to the nearest one, Enter puts the person at the centre.")
QUESTION = N_("Question")
QUESTIONS = N_("Questions")
QUESTION_NO = N_("No.")
QUESTION_ANSWER = N_("Conclusion or reason")
QUESTION_STANDARD = N_("What will count as an answer")   # T249
PROOFS = N_("Proof arguments")
PROOF = N_("Proof argument for {question}")
PROOF_PARTS = (("question", N_("Question")), ("sources", N_("Sources")), ("analysis", N_("Analysis")),
               ("correlation", N_("Correlation")), ("conflicts", N_("Conflicts resolved")),
               ("conclusion", N_("Conclusion")))
REVIEWED_BY = N_("Reviewed by {who}.")
REVIEWERS = {"contradictor": N_("the contradictor, independently"),
             "session": N_("the same session that wrote it: not an independent review")}
OBJECTION = N_("Objection {n}")
OBJECTION_ANSWER = N_("Answer: {text}")
OBJECTION_DISMISSED = N_("Dismissed: {text}")
EVIDENCE = N_("Evidence and analysis")
ANALYSIS = N_("{name}: {kind}")
ANALYSIS_HEAD = {"asserts": N_("Asserts"), "informant": N_("Informant"), "source": N_("Source"),
                 "note": N_("Fact, note")}
AXIS_NAMES = {"source": N_("Source kind"), "information": N_("Information"), "evidence": N_("Evidence")}
AXES = {"source": {"original": N_("original"), "derivative": N_("derivative"), "authored": N_("authored")},
        "information": {"primary": N_("primary"), "secondary": N_("secondary"), "undetermined": N_("undetermined")},
        "evidence": {"direct": N_("direct"), "indirect": N_("indirect"), "negative": N_("negative")}}
RESOLUTION = N_("Resolution: {kept}. {reasoning}")
UNRESOLVED_ANALYSIS = N_("Not resolved yet.")
REFUTED_IN_PASS = N_("Refuted at pass {n}")
REFUTED_IN_VOLET = N_("Refuted in volet {volet}, pass {n}")
# FL-D8: a volet, the group of passes it opens, with what it starts from and what it takes on
VOLET = N_("Part {n} — {title}")
VOLET_PARTS = {"established": N_("Established"), "corrections": N_("Corrections"), "openings": N_("Openings")}
DIVERGENT_ANALYSIS = N_("Divergence left unresolved: {reason}")
TIMELINES = N_("Timelines")
TIMELINE = N_("Timeline of {name}")
TIMELINE_HEAD = {"year": N_("Year"), "age": N_("Age"), "event": N_("Event"), "place": N_("Place"),
                 "clash": N_("Dates that clash")}
TIMELINE_ROLES = {"father": N_("father"), "mother": N_("mother"), "spouse": N_("spouse"), "child": N_("child")}
QUESTION_STATUSES = {"open": N_("open"), "answered": N_("answered"), "unresolved": N_("unresolved")}
GUIDES = N_("Locality guides")
GUIDE_TODAY = N_("{name}, today {current}")
GUIDE_JURISDICTIONS = N_("Jurisdictions")
GUIDE_REPOSITORIES = N_("Repositories")
GUIDE_GAPS = N_("Known gaps")
GUIDE_BUILT = N_("Guide built on {date} from: {sources}.")
GUIDE_COPIED = N_("Taken from the family {family}.")
GUIDE_DERIVED = N_("derived from a rule or a catalogue, not from a record of the place")
GUIDE_OPEN = N_("no known end")
GUIDE_UNKNOWN = N_("no known start")
GUIDE_HEAD = {"level": N_("Level"), "name": N_("Name"), "from": N_("From"), "to": N_("To"), "source": N_("Source"),
              "repository": N_("Repository"), "holdings": N_("Holdings"), "note": N_("Note"),
              "archive": N_("Archive"), "years": N_("Years"), "kind": N_("Kind"), "reference": N_("Reference")}
LEVELS = {"commune": N_("commune"), "municipality": N_("municipality"), "canton": N_("canton"),
          "district": N_("district"), "arrondissement": N_("arrondissement"), "department": N_("department"),
          "region": N_("region"), "province": N_("province"), "state": N_("state"), "country": N_("country"),
          "parish": N_("parish"), "parish-group": N_("group of parishes"), "deanery": N_("deanery"),
          "diocese": N_("diocese"), "church-province": N_("church province"), "bailliage": N_("bailliage"),
          "seneschalsy": N_("seneschalsy"), "generality": N_("generality"), "court": N_("court")}
SOURCE_TYPES = {"birth": N_("births"), "baptism": N_("baptisms"), "marriage": N_("marriages"), "death": N_("deaths"),
                "burial": N_("burials"), "census": N_("censuses"), "notarial": N_("notarial records"),
                "press": N_("newspapers"), "book": N_("books"), "manuscript": N_("manuscripts"),
                "directory": N_("directories")}
GAP_KINDS = {"destroyed": N_("records destroyed"), "missing": N_("records missing"),
             "lacunary": N_("records incomplete")}
COVERAGE = N_("Source coverage of {question}")
COVERAGE_HEAD = {"type": N_("Source type"), "places": N_("Places"), "years": N_("Years"), "state": N_("State"),
                 "how": N_("Searches, gaps or reason")}
COVERAGE_STATES = {"consulted": N_("consulted"), "gap": N_("gap"), "not_applicable": N_("not applicable"),
                   "unjustified_gap": N_("unjustified gap"), "todo": N_("to do")}
COVERAGE_UNKNOWN = {"window": N_("The question has no window: the sources it calls for are not known yet."),
                    "places": N_("The question names no place of known country: the sources it calls for are "
                                 "not known yet.")}
COVERAGE_COUNTRY = N_("No source type is catalogued yet for the country {country}.")
COVERAGE_GAPS = N_("Gaps")
# TRUST3: the confidence of a conclusion
CONFIDENCE = N_("Confidence")
CONFIDENCE_LEVELS = {"proved": N_("proved"), "probable": N_("probable"), "possible": N_("possible"),
                     "unsupported": N_("unsupported")}
CONFIDENCE_OF = N_("Confidence of the conclusion: {level}")
CONFIDENCE_REASONS = {
    "index": N_("rests on an index, not on the record itself: {ids}"),
    "hypothesis": N_("rests on a hypothesis: {ids}"),
    "refuted": N_("rests on a refuted fact: {ids}"),
    "no-status": N_("rests on a fact without a status: {ids}"),
    "indirect": N_("indirect evidence: {ids}"),
    "negative": N_("negative evidence, drawn from an absence: {ids}"),
    "secondary": N_("secondary information that no second source confirms: {ids}"),
    "same-informant": N_("secondary information that only one informant gives, though in several sources: {ids}"),
    "same-original": N_("secondary information whose second source copies the first, or is the same act: {ids}"),
    "objection": N_("an objection of the contradictor is still open: {ids}"),
    "chronology": N_("dates that clash, unexplained: {ids}"),
    "gps-partial": N_("the question conforms only partly to the GPS: {ids}"),
    "gps-not-conform": N_("the question does not conform to the GPS: at most possible ({ids})"),
    "chronology-error": N_("dates that cannot both be true: at most possible ({ids})"),
    "no-excerpt": N_("a record fact does not quote its passage: at most probable ({ids})"),
    "uncertain-reading": N_("a reading marked uncertain, not yet revised: at most probable ({ids})"),
}
# TRUST2: the passage a fact cites, in its note
EXCERPT = N_("“{text}” ({where})")
EXCERPT_LINE = N_("line {a} of the transcription")
EXCERPT_LINES = N_("lines {a}–{b} of the transcription")
EXCERPT_PAGE = N_("page read on {date}")
# T248: a person looked at the record a fact rests on, in the fact's note
FACT_CHECKED = N_("Checked by {who} on {date}, against {looked}.")
# GPS8: the five elements of the Genealogical Proof Standard, question by question
# T239: the report counts the elements the data document; it claims no conformity, which a genealogist judges
STANDARD_COUNT = N_("Elements of the Genealogical Proof Standard established: {n} of {m}")
STANDARD_CAVEAT = N_("Probandia checks that each element is documented in the data; whether the reasoning holds "
                     "is the genealogist's judgement.")
STANDARD_OF = N_("{question}: the elements of the Genealogical Proof Standard")
AI_ASSISTED = N_("Written with the help of AI agents: each fact cites its source, and the engine checks the "
                 "citations and the rules of proof; reading the sources again remains the reader's part.")
STANDARD_HEAD = {"element": N_("Element"), "state": N_("State"), "lacks": N_("What is missing")}
STANDARD_ELEMENTS = {"exhaustive": N_("Reasonably exhaustive search"),
                     "citations": N_("Complete and accurate citations"),
                     "analysis": N_("Analysis and correlation"),
                     "conflicts": N_("Conflicting evidence resolved"),
                     "argument": N_("Soundly reasoned conclusion")}
STANDARD_STATES = {"established": N_("established"), "partial": N_("partial"), "missing": N_("lacking"),
                   "not_applicable": N_("not applicable")}
STANDARD_LEVELS = {"conform": N_("conform"), "partial": N_("partly conform"), "not_conform": N_("not conform")}
STANDARD_LACKS = {
    "unknown": N_("the question has no {ids}"),
    "general-alone": N_("no specific question of the research is answered"),
    "holes": N_("source types to search, or to justify: {ids}"),
    "no-facts": N_("no fact yet"),
    "no-status": N_("facts without a status: {ids}"),
    "no-citation": N_("facts without a citation: {ids}"),
    "required": N_("sources without the fields their model requires: {ids}"),
    "untyped": N_("sources without a type, whose citation cannot be checked: {ids}"),
    "no-excerpt": N_("record facts that do not quote their passage: {ids}"),
    "excerpt-broken": N_("excerpts not found as quoted: {ids}"),
    "unanalysed": N_("conflicts without an analysis: {ids}"),
    "axes": N_("analyses whose evidence lacks its three axes: {ids}"),
    "unclassified": N_("concluding facts without their three axes (source, information, evidence): {ids}"),
    "chronology": N_("dates that clash, unexplained: {ids}"),
    "open-analysis": N_("analyses not resolved: {ids}"),
    "divergent-analysis": N_("divergences left unresolved, for an answered question: {ids}"),
    "no-conclusion": N_("no conclusion yet: the question is open"),
    "no-argument": N_("no proof argument accepted, though one is required ({ids})"),
    "argument-pending": N_("proof argument not accepted yet: {ids}"),
    "not-independent": N_("proof argument reviewed by the same session only: {ids}"),
}
STANDARD_REASONS = {"identity": N_("identity"), "indirect": N_("indirect evidence"),
                    "negative": N_("negative evidence"), "conflict": N_("conflict"),
                    "window": N_("window"), "places": N_("place of known country")}
INSTRUCTIONS = N_("Instructions")
NOT_CONSULTED = N_("not consulted ({status})")
MANUAL_TASKS = N_("To read by hand")
MANUAL_TASK = N_("{archive}: {url} — not consulted, a sign-in is required")

LIVING_CHAPTERS = [
    ("summary", N_("Summary")),
    ("question", N_("Question and scope")),
    ("persons", N_("Persons")),
    ("evidence", N_("Evidence and analysis")),
    ("hypotheses", N_("Hypotheses")),
    ("negatives", N_("Negative searches")),
    ("open", N_("Open questions")),
    ("sources", N_("Sources")),
    ("guides", N_("Locality guides")),
    ("method", N_("Method")),
    ("revisions", N_("Revision history")),
]

STATUSES = {"record": N_("Record"), "index": N_("Index"), "hypothesis": N_("Hypothesis"),
            "refuted": N_("Refuted")}
CAUSES = {"misreading": N_("misreading"), "homonym": N_("homonym"), "faulty-index": N_("faulty index"),
          "outdated-negative": N_("outdated negative"), "wrong-inference": N_("wrong inference"),
          "tool-failure": N_("tool failure"), "missing-source": N_("missing source"),
          "other": N_("other")}
QUALIFIERS = {"about": N_("about {date}"), "before": N_("before {date}"), "after": N_("after {date}"),
              "between": N_("between {date} and {end}"), "calculated": N_("calculated {date}"),
              "exact": N_("{date}")}
CALENDARS = {"gregorian": N_("Gregorian"), "julian": N_("Julian"),
             "republican": N_("French Republican")}
FACT_TYPES = {"birth": N_("birth"), "baptism": N_("baptism"), "marriage": N_("marriage"),
              "death": N_("death"), "burial": N_("burial"), "residence": N_("residence"),
              "occupation": N_("occupation"), "census": N_("census"), "military": N_("military service"),
              "emigration": N_("emigration"), "naturalisation": N_("naturalisation"),
              "other": N_("event")}
TABLE = {"name": N_("Name"), "born": N_("Born"), "died": N_("Died"), "status": N_("Status"),
         "pass": N_("Pass"), "section": N_("Section"), "what": N_("What changed"), "why": N_("Why"),
         "step": N_("Step"), "harness": N_("Harness"), "model": N_("Model"), "agent": N_("Agent"),
         "tools": N_("Tools"),
         "query": N_("Query"), "engine": N_("Engine"), "window": N_("Window"), "variants": N_("Variants")}
CHANGES = {"rewritten": N_("rewritten"), "moved": N_("moved"), "merged": N_("merged"),
           "fact revised": N_("fact revised"), "fact retracted": N_("fact retracted")}
HYPOTHESIS_STATUSES = {"open": N_("open"), "retained": N_("retained"), "rejected": N_("rejected")}
NOTES = N_("Notes")
LEGEND = {"father": N_("father"), "mother": N_("mother"), "spouse": N_("spouse"),
          "record": N_("proven by a record"), "index": N_("from an index"),
          "hypothesis": N_("hypothesis"), "living": N_("living person, masked")}
