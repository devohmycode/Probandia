import json
import os
import tempfile
import unittest

from probandia import tokens

RID = "2026-09-30-parents-of-victor-hugo"


def message(mid, ts, inp, out, read, short=0, long=0, split=True):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": short + long}
    if split:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": short, "ephemeral_1h_input_tokens": long}
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": "claude-opus-5-5", "usage": usage}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = self.tmp.name
        os.makedirs(os.path.join(self.project, ".probandia"))

    def transcript(self, name, rows):
        path = os.path.join(self.project, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
        return path

    def lines(self, rows):
        with open(os.path.join(self.project, ".probandia", "tokens.jsonl"), "a", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))


class FiveMinuteCache(Base):
    """version-1.0.0 T37: the five-minute cache apart from the one-hour cache."""

    def test_the_split_is_read_message_by_message(self):
        path = self.transcript("s.jsonl", [message("m1", "2026-10-13T09:00:00Z", 10, 100, 1000, long=4000),
                                           message("m2", "2026-10-13T09:01:00Z", 2, 50, 2000, short=800)])
        self.assertEqual([u for _t, u in tokens.messages(path)[0]],
                         [{"input": 10, "output": 100, "cache_read": 1000, "cache_write": 4000, "cache_write_5m": 0},
                          {"input": 2, "output": 50, "cache_read": 2000, "cache_write": 800, "cache_write_5m": 800}])
        totals = tokens.parse(path)
        # 12 + 5 × 150 + 0.1 × 3000 + 2 × 4000 (one hour) + 1.25 × 800 (five minutes)
        self.assertEqual(tokens.weighted(totals), 12 + 750 + 300 + 8000 + 1000)

    def test_a_new_line_carries_cache_write_5m_and_an_old_one_is_one_hour(self):
        path = self.transcript("s.jsonl", [message("m1", "2026-10-13T09:00:00Z", 10, 100, 1000, long=4000),
                                           message("m2", "2026-10-13T09:01:00Z", 2, 50, 2000, short=800)])
        out = tokens.record(self.project, {"hook_event_name": "Stop", "transcript_path": path}, "claude-code",
                            session="s1", research=RID)
        self.assertEqual((out[0]["cache_write"], out[0]["cache_write_5m"]), (4800, 800))
        with open(os.path.join(self.project, ".probandia", "tokens.jsonl"), encoding="utf-8") as fh:
            row = json.loads(fh.readline())
        self.assertEqual((row["cache_write"], row["cache_write_5m"]), (4800, 800))   # added, nothing renamed
        self.assertEqual(tokens.kinds(self.project, RID)["weighted"], 10062)
        self.lines([{"research": RID, "pass": None, "role": "reader", "input": 0, "output": 0, "cache_read": 0,
                     "cache_write": 1000}])   # written before T37: no cache_write_5m
        self.assertEqual(tokens.kinds(self.project, RID)["weighted"], 10062 + 2000)

    def test_a_transcript_without_the_split_is_one_hour(self):
        path = self.transcript("s.jsonl", [message("m1", "2026-10-13T09:00:00Z", 0, 0, 0, long=1000, split=False)])
        self.assertEqual(tokens.weighted(tokens.parse(path)), 2000)

    def test_the_five_minute_part_never_exceeds_the_whole(self):
        self.assertEqual(tokens.weighted({"cache_write": 100, "cache_write_5m": 400}), 125)


class ByModel(Base):
    """version-1.0.0 T38: the sums of a research per (harness, model) pair."""

    def test_two_models_are_kept_apart(self):
        row = {"research": RID, "pass": 1, "input": 10, "output": 100, "cache_read": 1000, "cache_write": 0}
        self.lines([dict(row, role="session", harness="claude-code", model="claude-opus-5-5", cache_write=4000),
                    dict(row, role="reader", harness="claude-code", model="claude-sonnet-5-5", cache_write=800,
                         cache_write_5m=800),
                    dict(row, role="reader", harness="claude-code", model="claude-sonnet-5-5"),
                    dict(row, research="another", harness="claude-code", model="claude-haiku-5-5")])
        found = tokens.by_model(self.project, RID)
        self.assertEqual(list(found), [("claude-code", "claude-opus-5-5"), ("claude-code", "claude-sonnet-5-5")])
        self.assertEqual(found[("claude-code", "claude-opus-5-5")],
                         {"input": 10, "output": 100, "cache_read": 1000, "cache_write": 4000, "cache_write_5m": 0,
                          "weighted": 10 + 500 + 100 + 8000})
        self.assertEqual(found[("claude-code", "claude-sonnet-5-5")],
                         {"input": 20, "output": 200, "cache_read": 2000, "cache_write": 800, "cache_write_5m": 800,
                          "weighted": 20 + 1000 + 200 + 1000})
        self.assertEqual(sum(t["weighted"] for t in found.values()), tokens.kinds(self.project, RID)["weighted"])
        self.assertEqual(tokens.by_model(self.project, "none"), {})


if __name__ == "__main__":
    unittest.main()
