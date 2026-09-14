"""Tests for the experiment recorder and the public/private data boundary.

Run with either::

    python3 -m unittest discover -s experiments/tests -t .
    python3 -m pytest experiments/tests

Stdlib ``unittest`` only, so the suite runs from a fresh clone with no
dependency install step.

Boundary tests deliberately run their assertions in a **subprocess**: the
public/private boundary is a process-level property (see
experiments/_boundary.py), so a test that imported both sides into the test
runner would be testing nothing.
"""
