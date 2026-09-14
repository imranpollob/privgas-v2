"""The public/private data boundary (acceptance items I and J).

The boundary is a *process-level* property: importing one read-side package
makes the other unimportable for the life of the process. A test that
imported both into the unittest runner would destroy the thing it is testing,
so each assertion runs in a fresh subprocess via ``_run``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)


class TestFeatureSideCannotReachLabels(unittest.TestCase):
    """Item I: the public-data reader cannot load the private source."""

    def test_attacker_view_imports_cleanly_on_its_own(self):
        r = _run("""
            import experiments.attacker_view as av
            assert hasattr(av, "load_public_events")
            print("OK")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK", r.stdout)

    def test_importing_labels_after_attacker_view_raises(self):
        r = _run("""
            import experiments.attacker_view  # noqa: F401
            from experiments._boundary import BoundaryViolation
            try:
                import experiments.labels  # noqa: F401
            except BoundaryViolation as exc:
                print("BLOCKED:", exc)
            else:
                raise SystemExit("labels was importable from attacker-side code")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED:", r.stdout)

    def test_dynamic_import_of_labels_is_also_blocked(self):
        """importlib is not a way around the guard."""
        r = _run("""
            import importlib
            import experiments.attacker_view  # noqa: F401
            from experiments._boundary import BoundaryViolation
            for name in ("experiments.labels", "experiments.labels.loader",
                         "experiments.labels.evaluation"):
                try:
                    importlib.import_module(name)
                except BoundaryViolation:
                    continue
                raise SystemExit(f"{name} was importable dynamically")
            print("BLOCKED")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED", r.stdout)

    def test_the_block_is_symmetric(self):
        r = _run("""
            import experiments.labels  # noqa: F401
            from experiments._boundary import BoundaryViolation
            try:
                import experiments.attacker_view  # noqa: F401
            except BoundaryViolation as exc:
                print("BLOCKED:", exc)
            else:
                raise SystemExit("attacker_view was importable alongside labels")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED:", r.stdout)

    def test_recorder_is_importable_from_both_sides(self):
        """The write-side package is neutral and holds no data."""
        for side in ("experiments.attacker_view", "experiments.labels"):
            with self.subTest(side=side):
                r = _run(f"""
                    import {side}  # noqa: F401
                    import experiments.recorder as rec
                    assert rec.SCHEMA_VERSION
                    print("OK")
                """)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("OK", r.stdout)

    def test_attacker_readers_refuse_a_path_under_data_private(self):
        """Constructing the path by hand does not get around the guard."""
        r = _run("""
            from pathlib import Path
            import experiments.attacker_view as av
            root = Path.cwd()
            target = root / "data" / "private" / "anything" / "ground_truth.jsonl"
            try:
                av.load_public_events(target)
            except av.PrivateDataAccessError as exc:
                print("BLOCKED:", exc)
            else:
                raise SystemExit("a data/private path was readable")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED:", r.stdout)

    def test_attacker_readers_refuse_a_ground_truth_file_moved_elsewhere(self):
        r = _run("""
            from pathlib import Path
            import experiments.attacker_view as av
            try:
                av.load_public_events(Path("/tmp/ground_truth.jsonl"))
            except av.PrivateDataAccessError as exc:
                print("BLOCKED:", exc)
            else:
                raise SystemExit("a relocated ground-truth file was readable")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED:", r.stdout)

    def test_public_manifest_carrying_a_seed_is_refused(self):
        r = _run("""
            import json, tempfile
            from pathlib import Path
            import experiments.attacker_view as av
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "run_manifest.public.json"
                p.write_text(json.dumps({"seed": 42}))
                try:
                    av.load_public_manifest(p)
                except av.PrivateDataAccessError as exc:
                    print("BLOCKED:", exc)
                else:
                    raise SystemExit("a manifest carrying a seed was accepted")
        """)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCKED:", r.stdout)


if __name__ == "__main__":
    unittest.main()
