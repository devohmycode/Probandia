import glob
import hashlib
import json
import os
import unittest

from probandia.errors import SchemaError, SchemaVersionError
from probandia.util import yamlio
from probandia.util.schema import Validator, load_schema, schemas_dir, validate_document
from tests import ROOT

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
FORMATS = ("research", "family", "persons", "places", "sources", "searches", "hypotheses",
           "variants", "non-links", "gaps", "analyses", "proofs", "event", "report", "library", "proposal", "source-types",
           "matrix", "bench-case", "bench-result", "workshop-link")

try:
    import jsonschema
except ImportError:  # a development dependency; continuous integration installs it
    jsonschema = None


def fixtures(kind, group):
    return sorted(glob.glob(os.path.join(FIXTURES, kind, group, "*.yaml")))


def expected_path(path):
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
    assert first.startswith("# expect: "), path
    return first[len("# expect: "):].strip()


class Fixtures(unittest.TestCase):
    def test_there_are_fixtures(self):
        for kind in FORMATS:
            self.assertGreaterEqual(len(fixtures(kind, "valid")), 1, kind)
            self.assertGreaterEqual(len(fixtures(kind, "invalid")), 1, kind)

    def test_fixture_project_validates(self):
        import json as _json
        family = os.path.join(FIXTURES, "project", "families", "hugo")
        validate_document("family", yamlio.load(os.path.join(family, "family.yaml")))
        for name in os.listdir(os.path.join(family, "index")):
            path = os.path.join(family, "index", name)
            validate_document(name[:-5], yamlio.load(path), path)
        rdir = os.path.join(family, "research", "2026-09-30-parents-of-victor-hugo")
        validate_document("research", yamlio.load(os.path.join(rdir, "research.yaml")))
        with open(os.path.join(rdir, "events.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                validate_document("event", _json.loads(line))

    def test_valid_fixtures_are_accepted(self):
        for kind in FORMATS:
            for path in fixtures(kind, "valid"):
                with self.subTest(path=os.path.relpath(path, FIXTURES)):
                    validate_document(kind, yamlio.load(path), path)

    def test_invalid_fixtures_are_rejected_with_the_path(self):
        for kind in FORMATS:
            for path in fixtures(kind, "invalid"):
                with self.subTest(path=os.path.relpath(path, FIXTURES)):
                    with self.assertRaises(SchemaError) as cm:
                        validate_document(kind, yamlio.load(path), path)
                    paths = [issue.path for issue in cm.exception.errors]
                    self.assertIn(expected_path(path), paths)


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class AgreesWithJsonschema(unittest.TestCase):
    """The built-in validator and jsonschema give the same verdict on every fixture."""

    def test_schemas_are_valid_2020_12(self):
        for name in os.listdir(schemas_dir()):
            if not name.endswith(".json"):   # examples/: samples, not schemas
                continue
            with open(os.path.join(schemas_dir(), name), encoding="utf-8") as fh:
                jsonschema.Draft202012Validator.check_schema(json.load(fh))

    def test_same_verdicts(self):
        for kind in FORMATS:
            reference = jsonschema.Draft202012Validator(load_schema(kind, 1))
            for group in ("valid", "invalid"):
                for path in fixtures(kind, group):
                    with self.subTest(path=os.path.relpath(path, FIXTURES)):
                        doc = yamlio.load(path)
                        self.assertEqual(reference.is_valid(doc), group == "valid")
                        self.assertEqual(not Validator(load_schema(kind, 1)).errors(doc),
                                         group == "valid")


class Versions(unittest.TestCase):
    def setUp(self):
        self.doc = yamlio.load(os.path.join(FIXTURES, "family", "valid", "full.yaml"))

    def test_newer_version_is_refused(self):
        self.doc["schema"] = 2
        with self.assertRaises(SchemaVersionError) as cm:
            validate_document("family", self.doc, "family.yaml")
        self.assertIn("newer than this engine knows", str(cm.exception))
        self.assertEqual(cm.exception.exit_code, 2)

    def test_missing_version(self):
        del self.doc["schema"]
        with self.assertRaises(SchemaError) as cm:
            validate_document("family", self.doc)
        self.assertEqual(cm.exception.errors[0].path, "$.schema")

    def test_published_schemas_are_frozen(self):
        # version-1.0.0 T214, STABILITY.md: a published schema never changes; a new shape is a new -N file,
        # whose fingerprint is added here
        with open(os.path.join(FIXTURES, "schema-fingerprints.json"), encoding="utf-8") as fh:
            frozen = json.load(fh)
        for path in glob.glob(os.path.join(schemas_dir(), "*.json")):
            name = os.path.basename(path)
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()
            with self.subTest(schema=name):
                self.assertIn(name, frozen, "a new schema: add its fingerprint")
                self.assertEqual(digest, frozen[name], "a frozen schema changed: write a new -N schema instead")


class Keywords(unittest.TestCase):
    def check(self, schema, value):
        return [str(e) for e in Validator(schema).errors(value)]

    def test_types(self):
        self.assertEqual(self.check({"type": "integer"}, True), ["$: expected integer, got true"])
        self.assertEqual(self.check({"type": ["string", "null"]}, None), [])
        self.assertEqual(self.check({"type": "number"}, 1), [])

    def test_required_and_unknown(self):
        s = {"type": "object", "required": ["a"], "additionalProperties": False,
             "properties": {"b": {"type": "string"}}}
        self.assertEqual(self.check(s, {"b": "x", "c": 1}), ["$.a: required", "$.c: unknown key"])

    def test_enum_and_pattern(self):
        self.assertEqual(len(self.check({"enum": ["a", "b"]}, "c")), 1)
        self.assertEqual(self.check({"type": "string", "pattern": "^x"}, "xy"), [])
        self.assertEqual(len(self.check({"type": "string", "pattern": "^x"}, "yx")), 1)

    def test_nested_paths(self):
        s = {"type": "object", "properties": {"list": {"type": "array", "items": {
            "type": "object", "properties": {"n": {"type": "integer", "maximum": 3}}}}}}
        self.assertEqual(self.check(s, {"list": [{"n": 1}, {"n": 4}]}),
                         ["$.list[1].n: greater than 3: 4"])

    def test_odd_keys_are_quoted(self):
        s = {"type": "object", "additionalProperties": {"type": "integer"}}
        self.assertEqual(self.check(s, {"a b": "x"}), ['$["a b"]: expected integer, got "x"'])

    def test_one_of(self):
        s = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertEqual(self.check(s, 1.5), [])
        self.assertEqual(self.check(s, 1), ["$: matches more than one alternative"])

    def test_one_of_explains_with_the_alternative_of_the_value_type(self):
        # an object refused by {null | object} used to read "expected null"
        s = {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": False,
                                          "properties": {"id": {"type": ["string", "null"]},
                                                         "as_written": {"type": "string"}}}]}
        self.assertEqual(self.check(s, {"id": None, "as_written": "Nancy", "street": "rue Carnot"}),
                         ["$.street: unknown key"])
        self.assertEqual(self.check(s, 3), ["$: expected null, got 3"])

    def test_property_names(self):
        s = {"type": "object", "propertyNames": {"type": "string", "pattern": "^[a-z]+$"},
             "additionalProperties": {"type": "integer"}}
        self.assertEqual(self.check(s, {"ok": 1}), [])
        self.assertEqual(self.check(s, {"Not ok": 1}), ['$["Not ok"]: does not match ^[a-z]+$: "Not ok"'])

    def test_unsupported_keyword_is_refused(self):
        with self.assertRaises(ValueError):
            Validator({"type": "object", "properties": {"a": {"if": {}}}})


class Views(unittest.TestCase):
    """T247: a source on several views; where the act is on its view."""

    def test_images_and_region(self):
        index = os.path.join(FIXTURES, "project", "families", "hugo", "index")
        sources = yamlio.load(os.path.join(index, "sources.yaml"))
        sources["sources"][0]["images"] = [sources["sources"][0]["image"], "evidence/images/e-1802-n-46.jpg"]
        validate_document("sources", sources, "sources.yaml")
        sources["sources"][0]["images"] = []
        with self.assertRaises(SchemaError):
            validate_document("sources", sources, "sources.yaml")
        persons = yamlio.load(os.path.join(index, "persons.yaml"))
        fact = persons["persons"][0]["facts"][0]
        fact["excerpt"] = {"kind": "transcription", "lines": [1, 2], "text": "x", "sha256": "0" * 64}
        for region in ("120,340,880,720", "0.1,0.25,0.8,0.3", "pct:5,40,90,25", "2:pct:5,40,90,25", None):
            fact["excerpt"]["region"] = region
            validate_document("persons", persons, "persons.yaml")
        for region in ("full", "1,2,3", "0:1,2,3,4", "x,y,w,h"):
            fact["excerpt"]["region"] = region
            with self.assertRaises(SchemaError, msg=region):
                validate_document("persons", persons, "persons.yaml")


class Yaml(unittest.TestCase):
    def test_timestamps_and_dates_stay_strings(self):
        doc = yamlio.loads("a: 2026-09-30T18:40:00Z\nb: 1851-03-02\nc: 12\n")
        self.assertEqual(doc, {"a": "2026-09-30T18:40:00Z", "b": "1851-03-02", "c": 12})

    def test_a_syntax_error_says_where_and_how(self):
        import tempfile

        from probandia.errors import YamlSyntaxError

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p1.yaml")
            with open(path, "w", encoding="utf-8") as fh:   # the session's internal error of 6 Oct. 2026
                fh.write("facts:\n- date: {value: '1929-09', original: 1[…] septembre 1929}\n")
            with self.assertRaises(YamlSyntaxError) as cm:
                yamlio.load_input(path)
        self.assertEqual((cm.exception.values["LINE"], cm.exception.reason), (2, "yaml"))
        self.assertIn("p1.yaml:2:", cm.exception.message)
        self.assertIn("double quotes", cm.exception.lines[0])

    def test_the_proposal_example_is_valid(self):
        from probandia.cli.data_cmd import EXAMPLE_PARTS, proposal_example

        doc = yamlio.loads(proposal_example("all"))
        validate_document("proposal", doc, "examples/proposal-1.yaml")
        # token-economy B4: the short form, which propose resolves from the transcription
        self.assertEqual(doc["facts"][0]["excerpt"], {"source": doc["facts"][0]["source"], "lines": "4-5"})
        for part in EXAMPLE_PARTS[1:]:
            self.assertEqual(list(yamlio.loads(proposal_example(part))), [part], part)
        # token-economy J1: the parts a pass with records needs, in one call
        four = proposal_example("facts,sources,searches,sections")
        self.assertEqual(list(yamlio.loads(four)), ["facts", "sources", "searches", "sections"])
        self.assertLess(len(four), len(proposal_example("all")) * 0.6)
        # H3: what the bench's agent got wrong is shown filled
        self.assertEqual(doc["persons"][0]["spouses"][0], {"person": "pierre-marchand-1822",
                                                            "marriage": "pierre-marchand-1822.marriage"})
        # token-economy J5: an invented family, nothing of the fixture family nor of the example cases
        for trace in ("hugo", "besan", "nancy", "fontaine", "auxon"):
            self.assertNotIn(trace, proposal_example("all").lower())
        self.assertEqual(set(doc["facts"][0]["place"]), {"id", "as_written"})
        self.assertIsNotNone(doc["facts"][0]["place"]["id"])
        self.assertEqual(doc["searches"][0]["filters"]["views"], "4-24")
        self.assertTrue(doc["searches"][0]["source_state"])   # a negative needs it (V-3)

    def test_round_trip_keeps_order_and_unicode(self):
        data = {"z": "Trébuchet", "a": [1, 2], "m": "2026-09-30T18:40:00Z"}
        text = yamlio.dumps(data)
        self.assertTrue(text.startswith("z: Trébuchet\n"))
        self.assertEqual(yamlio.loads(text), data)
