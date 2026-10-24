"""From a watch to issues (TRUST4-T5, optimize.md 6.18).

    python tools/watch_issues.py .probandia/watch.json --dry-run
    python tools/watch_issues.py .probandia/watch.json            # opens and closes them with gh

Reads the ``watch.json`` that ``probandia watch`` wrote and prepares one issue per
problem, its title stable so that the next watch finds it again:

- ``watch: <archive> witness failed``, once the witness has failed ``--after``
  times in a row (3: sites often blocked or offline would otherwise open one every
  week, TRUST-D7 made precise); its body gives the day, the error, the failures in
  a row and the command that replays it;
- ``watch: <catalogue> entry <id> is stale``, at once.

An open issue whose problem is gone (the witness passed, the entry is no longer
stale in this watch) is closed. With ``--dry-run`` nothing is sent: the plan is printed as JSON.
Without it, ``gh`` opens, comments and closes the issues labelled ``watch``: run
it only where the repository has a remote and its owner agreed (TRUST4-T6).
"""
import argparse
import json
import re
import subprocess
import sys

LABEL = "watch"


def witness_title(archive):
    return f"watch: {archive} witness failed"


def stale_title(catalogue, entry):
    return f"watch: {catalogue} entry {entry} is stale"


STALE_RE = re.compile(r"^watch: \S+ entry \S+ is stale$")


def plan(doc, after=3, open_titles=()):
    """{"open": [{title, body}], "close": [title]} for a watch. ``open_titles``, the issues open now:
    an entry's issue among them that this watch no longer finds stale is closed (T122)."""
    opened, closed = [], []
    for w in doc.get("witnesses") or []:
        title = witness_title(w["archive"])
        streak = w.get("streak") or 1
        if w["state"] == "failed" and streak >= after:
            opened.append({"title": title, "body": "\n".join([
                f"The witness `{w['archive']}.{w.get('operation')}` failed on {doc['date']}, "
                f"{streak} {'watch' if streak == 1 else 'watches'} in a row (Probandia {doc.get('version')}).", "",
                f"Error: {w.get('failure') or 'the witness did not find what it expects'}", "",
                f"Replay it: `probandia archive run {w['archive']}.witness`"])})
        elif w["state"] == "passed":
            closed.append(title)
    stale = {(s["catalogue"], s["entry"]) for s in doc.get("stale") or []}
    for catalogue, entry in sorted(stale):
        s = next(x for x in doc["stale"] if (x["catalogue"], x["entry"]) == (catalogue, entry))
        opened.append({"title": stale_title(catalogue, entry), "body": "\n".join([
            f"The entry `{entry}` of the {catalogue} catalogue was checked {s.get('checked') or 'never'}, "
            f"more than {doc.get('days')} days before {doc['date']}.", "",
            "Read its source again, then update its date (`checked` or `state.checked`)."])})
    stale_titles = {stale_title(c, e) for c, e in stale}
    closed += sorted(t for t in open_titles if STALE_RE.match(t) and t not in stale_titles)
    return {"open": opened, "close": closed}


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:2])}: {done.stderr.strip()[:300]}")
    return done.stdout


def open_issues():
    """{title: number} of the issues labelled ``watch`` open now."""
    return {i["title"]: i["number"] for i in json.loads(
        gh("issue", "list", "--label", LABEL, "--state", "open", "--json", "number,title", "--limit", "200"))}


def apply(todo, current):
    """Opens or comments the issues of ``todo["open"]``, closes those of ``todo["close"]``."""
    for issue in todo["open"]:
        if issue["title"] in current:
            gh("issue", "comment", str(current[issue["title"]]), "--body", issue["body"])
        else:
            gh("issue", "create", "--title", issue["title"], "--body", issue["body"], "--label", LABEL)
    for title in todo["close"]:
        if title in current:
            why = "The entry was checked again." if STALE_RE.match(title) else "The witness passes again."
            gh("issue", "close", str(current[title]), "--comment", why)


def main(argv=None):
    p = argparse.ArgumentParser(description="Turn a watch into issues.")
    p.add_argument("watch", help="the watch.json that probandia watch wrote")
    p.add_argument("--after", type=int, default=3, help="failures in a row before an issue opens (3)")
    p.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    a = p.parse_args(argv)
    with open(a.watch, encoding="utf-8") as fh:
        doc = json.load(fh)
    if a.dry_run:
        print(json.dumps(plan(doc, a.after), ensure_ascii=False, indent=1))
        return 0
    current = open_issues()
    todo = plan(doc, a.after, current)
    apply(todo, current)
    print(f"{len(todo['open'])} issue(s) opened or updated, {len(todo['close'])} to close if open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
