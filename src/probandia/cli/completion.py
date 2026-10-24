"""Tab completion (cli.md § 6.10, 5.15.2).

``probandia __complete <words>`` prints the candidates for the last word, one
per line: commands, options, choices, research ids, families, facts, providers,
setting keys, the rules V-1 to V-20. The scripts that ``probandia completion
<shell>`` writes call it on each Tab. It reads the files only, and fast: no
network, no lock, no launcher, no output contract.
"""
import argparse

SCRIPTS = {
    "powershell": r"""# Probandia: Tab completion for PowerShell. Add this line to your profile ($PROFILE):
#   probandia completion powershell | Out-String | Invoke-Expression
Register-ArgumentCompleter -Native -CommandName probandia -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $words = @($commandAst.CommandElements | Select-Object -Skip 1 |
        Where-Object { $_.Extent.EndOffset -le $cursorPosition } | ForEach-Object { $_.ToString() })
    if ($wordToComplete -eq '') { $words += '' }
    probandia __complete @words 2>$null | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }
}
""",
    "bash": r"""# Probandia: Tab completion for bash. Add to ~/.bashrc:
#   eval "$(probandia completion bash)"
_probandia() {
    local IFS=$'\n'
    COMPREPLY=($(probandia __complete "${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null))
}
complete -o default -F _probandia probandia
""",
    "zsh": r"""# Probandia: Tab completion for zsh. Add to ~/.zshrc:
#   eval "$(probandia completion zsh)"
autoload -U +X bashcompinit && bashcompinit
_probandia() {
    local IFS=$'\n'
    COMPREPLY=($(probandia __complete "${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null))
}
complete -o default -F _probandia probandia
""",
    "fish": r"""# Probandia: Tab completion for fish. Save as ~/.config/fish/completions/probandia.fish:
#   probandia completion fish > ~/.config/fish/completions/probandia.fish
complete -c probandia -f -a '(probandia __complete (commandline -opc)[2..-1] (commandline -ct) 2>/dev/null)'
""",
}

RULES = tuple(f"V-{n}" for n in range(1, 21))   # verify.RULES, without importing verify


def _takes_value(action):
    return action.nargs != 0 and bool(action.option_strings)


def _dynamic(dest, environ, cwd, project_arg):
    """Candidates that come from the project or the catalogues, by argument name."""
    try:
        if dest in ("provider", "engine"):
            from probandia.providers import catalogue

            return list(catalogue.load())
        if dest in ("key",):
            from probandia.config import registry

            return [s.key for s in registry.SETTINGS if not s.is_pattern]
        if dest == "rule":
            return list(RULES)
        from probandia.project import find_project

        project = find_project(project_arg, environ, cwd)
        if dest == "research":
            from probandia.research import all_researches

            return sorted(r.id for r in all_researches(project))
        if dest == "family":
            from probandia.lifecycle import families

            return sorted(families(project))
        if dest == "fact":   # T248: fact check <fact>, among the facts of the families' indexes
            from probandia.indexes import FamilyIndexes
            from probandia.lifecycle import families

            return sorted({f["id"] for fam in families(project) for p in FamilyIndexes(project, fam).items("persons")
                           for f in p.get("facts") or [] if f.get("id")})
    except Exception:   # completion never fails loudly
        return []
    return []


def candidates(words, environ=None, cwd=None):
    """The candidates for the last of ``words`` (the word being typed, maybe empty)."""
    from probandia.cli import SHORTCUTS, VALUE_OPTIONS, _global_options, build_parser

    words = list(words) or [""]
    *done, current = words
    parser = build_parser()
    globals_ = _global_options()
    global_opts = sorted(o for a in globals_._actions for o in a.option_strings)
    project_arg = None
    rest, i = [], 0
    while i < len(done):   # the global options before the command, and -p's value
        w = done[i]
        if w in ("-p", "--project") and i + 1 < len(done):
            project_arg = done[i + 1]
        if not rest and w in VALUE_OPTIONS:
            i += 2
            continue
        if not rest and w.startswith("-") and w not in SHORTCUTS:
            i += 1
            continue
        rest.append(w)
        i += 1
    if done and done[-1] in VALUE_OPTIONS and not rest:   # the value of a global option
        action = next(a for a in globals_._actions if done[-1] in a.option_strings)
        found = list(action.choices or [])
    elif not rest:
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        found = (global_opts + sorted(SHORTCUTS) if current.startswith("-")
                 else sorted(n for n in sub.choices if not n.startswith("_")))
    else:
        found = _for_command(parser, rest, current, global_opts, environ, cwd, project_arg)
    return [c for c in found if c.startswith(current)]


def _for_command(parser, rest, current, global_opts, environ, cwd, project_arg):
    from probandia.cli import SHORTCUTS

    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    if rest[0] in SHORTCUTS:   # -r stands for report open
        rest = SHORTCUTS[rest[0]].split() + rest[1:]
    name = rest[0]
    p = sub.choices.get(name)
    if p is None:
        return []
    while True:   # commands with actions of their own (config show, team inbox…)
        nested = next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)
        if nested is None or len(rest) < 2 or rest[1] not in nested.choices:
            break
        p, rest = nested.choices[rest[1]], rest[1:]
    by_option = {o: a for a in p._actions for o in a.option_strings}
    previous = rest[-1] if len(rest) > 1 else None
    if previous in by_option and _takes_value(by_option[previous]):
        action = by_option[previous]
        return list(action.choices or []) or _dynamic(action.dest, environ, cwd, project_arg)
    if current.startswith("-"):
        return sorted(set(by_option) | set(global_opts))
    positionals = [a for a in p._actions if not a.option_strings and a.dest != "help"]
    given, i = 0, 1
    while i < len(rest):
        w = rest[i]
        if w in by_option:
            i += 2 if _takes_value(by_option[w]) else 1
            continue
        given += 1
        i += 1
    for action in positionals:
        if action.nargs in (argparse.REMAINDER, "*", "+"):
            target = action
            break
        if given == 0:
            target = action
            break
        given -= 1
    else:
        return []
    if isinstance(target, argparse._SubParsersAction):
        return sorted(target.choices)
    return [str(c) for c in (target.choices or [])] or _dynamic(target.dest, environ, cwd, project_arg)


def run(words, stdout, environ, cwd):
    """``probandia __complete``: one candidate per line; always exit code 0."""
    try:
        found = candidates(words, environ, cwd)
    except Exception:
        found = []
    stdout.write("".join(c + "\n" for c in found))
    stdout.flush()
    return 0
