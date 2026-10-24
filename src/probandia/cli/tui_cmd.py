"""The optional terminal interface: the application of CLI15 and its console's
forms. Importing the engine never imports Textual, nor does this module: the help
of ``tui`` describes the application from it (T108)."""
import subprocess
import sys
import textwrap

from probandia.cli.output import Result
from probandia.i18n import N_, _

# The screens, in the order of their keys, 1 to 7 (decision T6, T92), and what each shows.
SCREENS = [("home", N_("Home")), ("quotas", N_("Quotas")), ("researches", N_("Researches")),
           ("family", N_("Family")), ("proposals", N_("Proposals")), ("config", N_("Config")), ("help", N_("Help"))]
SHOWS = {"home": N_("the researches, the last events of the one chosen, the lowest accounts and the alerts"),
         "quotas": N_("the free quotas of the accounts, the providers and their keys"),
         "researches": N_("each research: its file, its log, its report and its team"),
         "family": N_("the family's tree, its persons and their facts"),
         "proposals": N_("the proposals waiting, read then accepted or set aside"),
         "config": N_("the settings, the library of scripts and the diagnostic"),
         "help": N_("every setting, where its value comes from, the providers' conditions, the keys and the variables")}
PALETTE_KEY, RUN_KEY = "ctrl+p", "ctrl+r"   # the application's and the console's bindings


def about():
    """What ``probandia tui --help`` says of the application: its screens and their keys, the
    palette and the console (T108)."""
    width = max(len(_(title)) for _name, title in SCREENS)
    out = [_("Its screens, each on its key:")]
    for n, (name, title) in enumerate(SCREENS, 1):
        out += textwrap.wrap(f"  {n}  {_(title).ljust(width)}  {_(SHOWS[name])}", 78,
                             subsequent_indent=" " * (width + 7))
    for text in (_("{palette} opens the palette: a screen, or the form of a command.").format(
                     palette=PALETTE_KEY.title()),
                 _("The console fills in a command in its form, and {run} runs it without leaving the application: "
                   "its readable output under the form, its confirmations and the keys it asks for in the "
                   "application's windows.").format(run=RUN_KEY.title()),
                 _("? lists every key, q quits. The application writes nothing itself: each action runs a "
                   "command of the engine.")):
        out += [""] + textwrap.wrap(text, 78)
    return "\n".join(out)


def command_line(argv):
    """``argv`` as the person would type it in this system's shell."""
    import shlex

    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def execute(argv, *, stdout, stdin, environ, cwd, preview_args=None):
    """A command of the console: its line, a secret written <redacted> (``preview_args``), then
    its readable output, as at a terminal; its questions go where ``asking`` puts them."""
    from probandia import cli

    # The forms run in human mode, including under an agent-configured shell.
    argv = [a for a in argv if a not in ("--json", "--quiet", "-q")]
    argv = [*argv, "--output-format", "human"]
    preview_args = argv if preview_args is None else [*preview_args, "--output-format", "human"]
    stdout.write(_("Command: {command}").format(command=command_line(["probandia", *preview_args])) + "\n")
    return cli.main(argv, stdout=stdout, stdin=stdin,
                    environ=environ, cwd=cwd)


def run(ctx):
    # The terminal first: an agent or a script without one learns it at once, before
    # Textual is imported (0.6 to 1 s) and whether it is installed or not (T86).
    from probandia.cli.asking import interactive, terminal

    if not interactive(ctx.stdin, ctx.environ) or not terminal(ctx.stdout):
        return Result("FAIL", {"REASON": "tui-needs-terminal"},
                      [_("The terminal interface needs an interactive terminal.")], exit_code=2)
    try:
        from probandia.cli.tui_app import make_app
    except ImportError:
        return Result("FAIL", {"REASON": "tui-unavailable"},
                      [_("Install the terminal interface: {command}").format(
                          command='uv tool install "probandia[tui]"')], exit_code=2)
    make_app(ctx).run()   # the console runs its commands in the application (T107)
    result = Result("OK")
    result.raw = ""
    return result
