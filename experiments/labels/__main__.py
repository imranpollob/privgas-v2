"""``python3 -m experiments.labels`` runs the privacy-leakage self-check."""

import sys

from .selfcheck import main

sys.exit(main())
