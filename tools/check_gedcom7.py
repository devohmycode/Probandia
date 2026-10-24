"""Development check: re-read a GEDCOM 7 export with the ``gedcom7`` package.

    python tools/check_gedcom7.py exports/hugo-2026-10-01.gdz

Parses ``gedcom.ged`` (from the GEDZIP archive, or a plain ``.ged``), validates
it against the GEDCOM 7 grammar, writes it back and parses it again. Exit code 1
on any error. ``gedcom7`` is a development dependency only (SPECS § 14).
"""
import sys
import zipfile


def read(path):
    if path.lower().endswith((".gdz", ".zip")):
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "gedcom.ged" not in names:
                raise SystemExit(f"{path}: no gedcom.ged in the archive")
            if any(n.startswith("META-INF/") for n in names):
                raise SystemExit(f"{path}: GEDZIP must not hold META-INF")
            data = z.read("gedcom.ged")
    else:
        with open(path, "rb") as fh:
            data = fh.read()
    if not data.startswith(b"\xef\xbb\xbf"):
        raise SystemExit(f"{path}: gedcom.ged must start with a byte order mark")
    return data.decode("utf-8-sig")


def main(argv):
    import gedcom7

    failed = 0
    for path in argv:
        text = read(path)
        try:
            records = gedcom7.loads(text)
            gedcom7.validate(records)
            again = gedcom7.loads(gedcom7.dumps(records))
        except Exception as err:  # noqa: BLE001 — report every kind of failure
            print(f"FAIL {path}: {type(err).__name__}: {err}")
            failed += 1
            continue
        print(f"OK {path}: {len(records)} records, {len(again)} after a round trip")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
