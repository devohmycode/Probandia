"""Help for a person: the commands grouped by theme, examples, and short pages
on the subjects people ask about (cli.md § 6.8).

The contract keeps argparse's full help, which lists every command (agents and
the acceptance test of sprint S1 rely on it); ``--help --all`` shows it to a
person too.
"""
from probandia.i18n import N_, _

# The commands a person types, by theme. The engine's other commands stay out
# of the readable help.
GROUPS = [
    (N_("Research"), ("new", "resume", "fork", "verify", "question", "matrix", "fact", "close", "status", "board",
                      "statusline")),
    (N_("Reports, trees, exports and imports"), ("report", "tree", "export", "import", "import-gedcom")),
    (N_("Families and what they hold"), ("research", "family", "find", "person", "searches", "sources", "negatives",
                                          "hypotheses", "gaps", "proposals")),
    (N_("Free quotas"), ("usage", "quota", "cache")),
    (N_("Settings and checks"), ("init", "config", "keys", "providers", "watch", "doctor", "library", "memory", "template",
                                  "browser")),
    (N_("Genealogist's tools"), ("dates", "variants", "places", "cite")),
    (N_("Help"), ("help", "completion", "tui")),
]

# Command lines are not translated: they are what one types.
EXAMPLES = {
    "new": ['probandia new "Who were the parents of Émile Marchand?" --family marchand'],
    "resume": ["probandia resume", 'probandia resume 2026-09-30 --instructions "search Hautbois first"'],
    "fork": ["probandia fork 2026-09-30 --at 2 --name second-lead"],
    "verify": ["probandia verify", "probandia verify --rule V-3", "probandia verify --standard"],
    "question": ["probandia question list", 'probandia question add "Where did he die?" --person emile-marchand-1851',
                 'probandia question edit Q1 --standard "his birth act, naming both parents"',
                 "probandia question answer Q1 --conclusion emile-marchand-1851.birth",
                 'probandia question unresolved Q2 --reason "the registers of 1850-1852 are lost"'],
    "matrix": ["probandia matrix", "probandia matrix 2026-09-30 --question Q1",
               'probandia matrix justify Q1 notarial --reason "the family owned nothing"'],
    "fact": ['probandia fact check emile-marchand-1851.birth --by "Marie Durand" '
             '--looked "the image of the act, view 45"'],
    "close": ["probandia close", "probandia close 2026-09-30 --yes"],
    "status": ["probandia status", "probandia -s --family marchand"],
    "board": ["probandia board --json", "probandia board 2026-09-30 --json"],
    # Claude Code runs the command of its statusLine setting with a JSON object on stdin
    "statusline": ["probandia statusline", "in ~/.claude/settings.json or .claude/settings.json:",
                   '  "statusLine": {"type": "command", "command": "probandia statusline"}'],
    "report": ["probandia report open", "probandia -r 2026-09-30", "probandia report show 2026-09-30",
               "probandia report render --formats md,html"],
    "tree": ["probandia tree --family marchand --format html"],
    "export": ["probandia export gedcom7 --family marchand --living mask"],
    "config": ["probandia config show --origin", "probandia config grade advanced", "probandia config diff",
               "probandia config wizard"],
    "init": ["probandia init"],
    "tui": ["probandia tui", "probandia -l fr tui"],
    "cache": ["probandia cache stats", "probandia cache stats --provider tavily",
              "probandia cache clear --provider brave", "probandia cache clear --older-than 30d --yes"],
    "quota": ["probandia quota show", "probandia quota sync", 'probandia quota add tavily 3 --note "web site"'],
    "doctor": ["probandia doctor"],
    "watch": ["probandia watch", "probandia watch --keys"],
    "providers": ["probandia providers", "probandia providers show serper", "probandia providers disable serper",
                  "probandia providers stale"],
    "keys": ["probandia keys", "probandia keys check", "probandia keys set SERPER_API_KEY",
             "probandia keys signup serper"],
    "library": ["probandia library list", "probandia library find \"births Luxembourg\"",
                "probandia library promote anlux-births --to user",
                "probandia library draft SKILL.md --kind skill --id probandia-ad56-registers",
                "probandia library install probandia-ad56-registers --scope project --for claude-code",
                "probandia library export lot.zip --ids anlux-births"],
    "memory": ["probandia memory list",
               'probandia memory add "Reports use the sober template, for printing" --kind template',
               "probandia memory remove M3", "probandia memory sync"],
    "template": ["probandia template list", "probandia template designer",
                 "probandia template check family-book.html", "probandia template import family-book.html",
                 "probandia template use family-book --level family --research 2026-09-30",
                 "probandia render --all"],
    "import": ["probandia import C:/genealogy/workshop --dry-run"],
    "workshop": ["probandia workshop status", "probandia workshop diff --format yaml",
                 "probandia workshop push --dry-run", "probandia workshop push --accept victor-hugo-1802.death",
                 "probandia workshop pull", "probandia workshop link 2026-09-30 --report paris-1822"],
    "import-gedcom": ["probandia import-gedcom family.ged --family marchand"],
    "dates": ['probandia dates "3 nivôse an XII"', "probandia dates --age 34 --on 1885-03-02"],
    "variants": ["probandia variants Marchand --paleo"],
    "places": ['probandia places "Colmar" --as-of 1850', "probandia places guide Nancy --family marchand",
               "probandia places guide nancy --family martin --copy-from marchand"],
    "help": ["probandia help quotas", "probandia help exit-codes"],
    "completion": ["probandia completion powershell | Out-String | Invoke-Expression",
                   'eval "$(probandia completion bash)"'],
    "read": ['probandia read https://example.org/registres --question "baptism of Victor Hugo"',
             'probandia read https://example.org/registres --map --links naissances',
             'probandia read https://example.org/liste?page=1 --crawl 10 --links page= --question "Hugo"',
             'probandia read https://example.org/inventaire --extract "the registers: cote, commune, years"'],
    "usage": ["probandia -u", "probandia -u --sync", "probandia usage serper", "probandia -u --families",
              "probandia -u --csv > quotas.csv", "probandia usage --alert 20%", "probandia -u --forecast",
              "probandia usage --short"],
}

TOPICS = {
    "quotas": [
        N_("Probandia uses only the free tiers of its providers, and never pays."),
        N_("quota show: what each free tier has left, in searches and pages, and the day it starts again."),
        N_("quota sync: reads the balances from the providers' accounts, at no cost."),
        N_("new and resume read them once a day, and an engine command after 20 calls on one provider; "
           "QUOTA_DRIFT= names a provider that counted what the ledger did not see."),
        N_("A share of each quota is kept in reserve (budget.reserve_percent, 10 % by default)."),
        N_("A call the free quota cannot pay for is not made: STATUS=STOP, with the next free provider."),
    ],
    "negatives": [
        N_("A web negative (\"found nowhere\") needs at least two independent index families "
           "(web.negative_families)."),
        N_("An engine whose answer is unrelated to the query does not count; an engine of a missing family "
           "takes over."),
        N_("A negative records what was searched and where, so that the search is not repeated in vain."),
    ],
    "grades": [
        N_("Settings come in three grades: essential (8 settings), advanced (about twenty more) and expert (all)."),
        N_("config show lists the settings of your grade; config grade advanced shows more."),
        N_("A setting above your grade keeps its default value."),
    ],
    "exit-codes": [
        N_("0: OK or WARN"),
        N_("1: FAIL, a check failed, a rule refused, a proposal was rejected"),
        N_("2: usage or configuration error"),
        N_("3: ASK, the user must answer"),
        N_("4: STOP, a free quota, a budget or a cap was reached, or the user declined"),
        N_("5: a lock is held by another owner"),
        N_("6: not inside a project"),
        N_("7: network or provider error after all retries"),
        N_("10: internal error, details in the log"),
        N_("130: interrupted (Ctrl+C)"),
    ],
    "files": [
        N_("probandia.toml: the project's settings, versioned; probandia.local.toml: local, not versioned."),
        N_("families/<family>/: the family's index, its researches, reports and trees."),
        N_("exports/: the GEDCOM files written by export, <family>-<date>.gdz or .ged."),
        N_("library/: the scripts the agents learned."),
        N_(".probandia/: internal state (cache, quota ledger, locks, logs), not versioned."),
        N_("Keys go in a .env file, the user's (next to config.toml) or the project's; they are never printed."),
    ],
}


def examples_epilog(name):
    """The text under a command's --help, or None."""
    lines = EXAMPLES.get(name)
    if not lines:
        return None
    return _("examples:") + "\n" + "\n".join("  " + line for line in lines)


def readable_help(style, commands, version):
    """The top-level help of the readable output."""
    by_name = {c.name: c for c in commands}
    out = [style.bold(f"probandia {version}") + " — " + _("nothing is concluded until it is proven."), "",
           _("usage: probandia [options] <command> [arguments]")]
    width = max(len(n) for _t, names in GROUPS for n in names)
    for title, names in GROUPS:
        out += ["", style.bold(_(title))]
        out += [f"  {n.ljust(width)}  {_(by_name[n].help)}" for n in names if n in by_name]
    out += ["", style.bold(_("Shortcuts")), "  -u  usage", "  -s  status", "  -r  report open", "",
            style.bold(_("Options")),
            "  -p <path>  " + _("project root"),
            "  -l <tag>   " + _("output language (BCP-47)"),
            "  -q         " + _("print only STATUS and DETAILS"),
            "  --json, --output-format human|contract|json, --plain, --no-color",
            "  -V         " + _("version"), "",
            _("probandia help <subject>: {subjects}").format(subjects=", ".join([*TOPICS, "settings"])),
            _("probandia --help --all: every command, the engine's included")]
    return "\n".join(out) + "\n"
