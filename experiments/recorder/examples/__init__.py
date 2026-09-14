"""Synthetic, clearly-labelled example runs for B0, B1 and B2.

**These are not measured results.** Every row carries
``data_origin: "synthetic_fixture"`` and every run_id is prefixed
``synthetic-``; the validator enforces both, so a fixture can never be read
as an experimental observation.

They exist because at the time Prompt 3 was carried out ``baselines/``
contained only ``b3_privgas_v1`` -- B0, B1 and B2 have not been implemented
(docs/baseline-spec.md registry). Rather than fabricate measured runs, these
fixtures exercise the full recorder path end to end for each of the three
baselines and show exactly what a real run must produce. When Prompt 2 lands,
the baseline runners feed real observations through the same adapters and the
fixtures stay as golden examples and test data.
"""
