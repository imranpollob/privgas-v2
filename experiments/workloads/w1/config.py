"""Load baselines/w1_b0_b2/w1-config.json -- the one set of matched W1 parameters.

The Foundry tests read the same file, so the forge semantics tests and the
live measurement cannot silently drift to different amounts, fees or limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ...recorder.provenance import repo_root

BASELINE_DIR = Path("baselines") / "w1_b0_b2"
CONFIG_FILE = "w1-config.json"

#: EntryPoint provenance, verified in docs/b3-reproduction.md (byte-identical
#: vendored tree) and re-checked by the dependency-pin test.
ENTRYPOINT_VERSION = "0.9.0"
ENTRYPOINT_SOURCE_COMMIT = "b36a1ed52ae00da6f8a4c8d50181e2877e4fa410"
ENTRYPOINT_SOURCE_REPO = "https://github.com/eth-infinitism/account-abstraction"

#: (baseline_id, workload_id) -> experiment_id. B0 has no warm variant (an EOA
#: has nothing to pre-deploy); B2 warm variants are not implemented (optional,
#: no new semantics).
EXPERIMENT_IDS = {
    ("B0", "W1-cold"): "baselines/b0-w1-cold",
    ("B1", "W1-cold"): "baselines/b1-w1-cold",
    ("B1", "W1-warm"): "baselines/b1-w1-warm",
    ("B2-Allowlist", "W1-cold"): "baselines/b2-allowlist-w1-cold",
    ("B2-Signature", "W1-cold"): "baselines/b2-signature-w1-cold",
}

#: run_id suffixes must be a single [a-z0-9]{1,16} token (RE_RUN_ID).
RUN_ID_SUFFIX = {
    ("B0", "W1-cold"): "b0cold",
    ("B1", "W1-cold"): "b1cold",
    ("B1", "W1-warm"): "b1warm",
    ("B2-Allowlist", "W1-cold"): "b2allowcold",
    ("B2-Signature", "W1-cold"): "b2sigcold",
}

PAYMASTER_OF = {
    "B2-Allowlist": "ObservablePaymaster",
    "B2-Signature": "SignatureVerifyingPaymaster",
}


@dataclass(frozen=True)
class W1Config:
    raw: Dict[str, Any]

    def _u(self, section: str, key: str) -> int:
        return int(self.raw[section][key])

    @property
    def chain_id(self) -> int:
        return int(self.raw["chain_id"])

    # token
    @property
    def token_supply(self) -> int:
        return self._u("token", "supply")

    @property
    def transfer_amount(self) -> int:
        return self._u("token", "transfer_amount")

    @property
    def token_decimals(self) -> int:
        return int(self.raw["token"]["decimals"])

    # fees
    @property
    def base_fee(self) -> int:
        return self._u("fees", "base_fee_per_gas")

    @property
    def max_priority_fee(self) -> int:
        return self._u("fees", "max_priority_fee_per_gas")

    @property
    def max_fee(self) -> int:
        return self._u("fees", "max_fee_per_gas")

    def gas_limit(self, name: str) -> int:
        return self._u("eoa_tx_gas_limits", name)

    # userop
    @property
    def verification_gas_limit(self) -> int:
        return self._u("userop", "verification_gas_limit")

    @property
    def call_gas_limit(self) -> int:
        return self._u("userop", "call_gas_limit")

    @property
    def provisional_pre_verification_gas(self) -> int:
        """Only for the calibration dry run; the measured op uses the calibrated value."""
        return self._u("userop", "provisional_pre_verification_gas")

    @property
    def paymaster_signature_validity(self) -> tuple:
        return (self._u("userop", "paymaster_signature_valid_until"),
                self._u("userop", "paymaster_signature_valid_after"))

    @property
    def paymaster_verification_gas_limit(self) -> int:
        return self._u("userop", "paymaster_verification_gas_limit")

    @property
    def paymaster_post_op_gas_limit(self) -> int:
        return self._u("userop", "paymaster_post_op_gas_limit")

    @property
    def account_salt(self) -> int:
        return self._u("userop", "account_salt")

    @property
    def nonce_key(self) -> int:
        return self._u("userop", "nonce_key")

    def funding(self, key: str) -> int:
        return self._u("funding", key)

    # derived quantities the baselines must agree on
    def required_prefund(self, with_paymaster: bool, pre_verification_gas: int) -> int:
        """EntryPoint v0.9 _getRequiredPrefund for this config."""
        gas = (self.verification_gas_limit + self.call_gas_limit
               + pre_verification_gas)
        if with_paymaster:
            gas += (self.paymaster_verification_gas_limit
                    + self.paymaster_post_op_gas_limit)
        return gas * self.max_fee

    @property
    def b0_eth_allowance(self) -> int:
        """ETH the B0 sender supplies: exactly enough for the action tx."""
        return self.gas_limit("b0_action") * self.max_fee

def baseline_dir(root: Optional[Path] = None) -> Path:
    return (Path(root) if root else repo_root()) / BASELINE_DIR


def load_config(root: Optional[Path] = None) -> W1Config:
    path = baseline_dir(root) / CONFIG_FILE
    return W1Config(raw=json.loads(path.read_text(encoding="utf-8")))
