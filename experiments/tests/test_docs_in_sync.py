"""The schema documentation must not drift from the validator.

Generated tables in docs/experiment-schema.md are regenerated here and
compared. A doc that says something the code does not enforce is worse than
no doc, because it will be believed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from experiments.recorder import docgen
from experiments.recorder.baselines import BASELINE_IDS
from experiments.recorder.privatekeys import FORBIDDEN_PRIVATE_KEYS
from experiments.recorder.validate import describe_schema
from experiments.recorder.version import SCHEMA_VERSION, STREAMS

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "experiment-schema.md"


class TestDocsInSync(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")

    def test_generated_tables_match_the_schemas(self):
        self.assertEqual(
            docgen.render(self.text), self.text,
            "docs/experiment-schema.md is stale. Run:\n"
            "  python3 -m experiments.recorder.docgen --write")

    def test_every_field_of_every_stream_is_documented(self):
        for stream in STREAMS:
            for field in describe_schema(stream):
                with self.subTest(stream=stream, field=field["field"]):
                    self.assertIn(f"`{field['field']}`", self.text)

    def test_current_schema_version_is_stated(self):
        self.assertIn(f"`{SCHEMA_VERSION}`", self.text)

    def test_every_baseline_appears_in_the_capability_table(self):
        for baseline_id in BASELINE_IDS:
            with self.subTest(baseline=baseline_id):
                self.assertIn(baseline_id, self.text)

    def test_every_forbidden_key_is_listed_or_a_documented_alias(self):
        """The denylist is only credible if the doc names what is on it."""
        documented = {
            key for key in FORBIDDEN_PRIVATE_KEYS if f"`{key}`" in self.text}
        aliases = {"ground_truth", "labels", "secret", "relation_labels",
                   "intended_relation_labels", "true_value", "label"}
        missing = FORBIDDEN_PRIVATE_KEYS - documented - aliases
        self.assertEqual(missing, set(),
                         f"denylisted keys not named in the doc: {sorted(missing)}")

    def test_known_limitations_are_stated(self):
        for phrase in (
            "not a privacy proof",
            "Synthetic examples are not measurements",
            "binding, not hiding",
            "Cost accounting is not in the event schema",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
