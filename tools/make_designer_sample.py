"""Writes ``designer/sample.json``: the engine's slots for the sample report of
``tests/sample-project-gps`` (its research that meets the GPS, GPS8), in English and French, and the report labels, which
the template designer shows (optimize.md 4.7).

    python tools/make_designer_sample.py

Running it again writes the same bytes; ``tests/unit/test_templates.py`` checks
that the file is up to date.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from probandia.report.designer import sample_data  # noqa: E402

PROJECT = os.path.join(ROOT, "tests", "sample-project-gps")
OUT = os.path.join(ROOT, "designer", "sample.json")


def text():
    return json.dumps(sample_data(PROJECT), ensure_ascii=False, sort_keys=True, indent=1) + "\n"


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text())
    print(OUT)
