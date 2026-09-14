"""Record schemas for the three experiment data streams.

One module per stream:

  ground_truth      secret labels; never an attacker input
  public_events     what the declared public observer (A0/A1) can see
  bundler_private   what an instrumented bundler we operate (A2) can see

``common`` holds the envelope shared by all three and the generic
spec-driven validator.
"""

from . import bundler_private, ground_truth, public_events  # noqa: F401

STREAM_SCHEMAS = {
    "ground_truth": ground_truth.SCHEMA,
    "public_events": public_events.SCHEMA,
    "bundler_private": bundler_private.SCHEMA,
}
