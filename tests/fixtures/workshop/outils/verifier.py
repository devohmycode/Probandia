"""A minimal check of the test workshop, in the spirit of a workshop's own outils/verifier.py:
every fact of commun/personnes.yaml carries statut, volet and chapitre, the last two in Roman
numerals. Standard library only: it reads the lines, never the YAML."""
import re
import sys

MARKERS = ("statut", "volet", "chapitre")
ROMAN = re.compile(r"^[IVXLCDM]+$")


def facts(text):
    """The flow maps of the file, each joined on one line."""
    out, current = [], None
    for line in text.splitlines():
        if current is None and "{" in line and ("statut" in line or line.rstrip().endswith(",")):
            current = line[line.index("{"):]
        elif current is not None:
            current += " " + line.strip()
        if current is not None and current.count("{") == current.count("}"):
            out.append(current)
            current = None
    return out


def main():
    with open("commun/personnes.yaml", encoding="utf-8") as fh:
        text = fh.read()
    errors = []
    for fact in facts(text):
        values = dict(re.findall(r"(\w+): ([^,{}\"]+|\"[^\"]*\")", fact))
        for key in MARKERS:
            if key not in values:
                errors.append(f"no {key}: {fact[:60]}")
        for key in ("volet", "chapitre", "volet_refute"):
            if key in values and not ROMAN.match(values[key].strip()):
                errors.append(f"{key} not in Roman numerals: {values[key]}")
    for e in errors:
        print(e)
    print(f"{len(facts(text))} facts checked, {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
