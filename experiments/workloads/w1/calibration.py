"""The preVerificationGas calibration artifact and its environment fingerprint.

The EntryPoint's unmeasured overhead O (gas a bundle transaction spends that
``UserOperationEvent.actualGasUsed`` does not include, beyond the 21,000
intrinsic gas and calldata) is a property of the ENVIRONMENT, not of each
research sample. It is measured once by ``python3 -m
experiments.workloads.w1.calibrate`` (exact-bundle dry runs, ``pvg.calibrate``)
and written to ``baselines/w1_b0_b2/calibration/pvg-overhead.json``.
Experiment runs read O from that artifact and never dry-run their operations.

O is keyed by OPERATION SHAPE, because measurement showed it depends on
(a) whether the UserOperation has callData (a deploy-only op with empty
callData skips the account call inside the EntryPoint's inner frame) and
(b) the gas REFUND of the executed call: O is measured from the receipt, which
is net of refunds. The W1 application call (ERC-20 ``transfer`` of the account's
whole balance) clears a storage slot and earns the EIP-3529 4,800-gas refund;
B3's Bootstrap call (``CreditPool.deposit``) clears nothing. Transferring
``amount - 1`` instead raises O by exactly 4,800 (measured 2026-09-14), so O is
"EntryPoint unmeasured overhead net of the execution's refund", not a property
of the EntryPoint alone:

* ``execute_call``         -- ``execute(token, 0, transfer(...))``: the W1 application call
                              (every measured W1 action, including B3's Spend)
* ``execute_pool_deposit`` -- ``execute(pool, 0, deposit(uint256))``: B3 Bootstrap
* ``empty_calldata``       -- deploy-only warm-up operation

Across all measured operations within a shape the calibration requires ONE
value; it fails rather than averaging.

Recalibration is REQUIRED (``RecalibrationRequired``) when anything in the
fingerprint changes: EntryPoint source commit or bytecode, account / factory /
Paymaster bytecode, bundler version, bundle size, beneficiary pre-funding
(an empty beneficiary adds a 25,000-gas new-account charge), chain id,
hardfork, or anvil version. Changing bundler logic that affects the encoded
bundle or the EntryPoint call requires bumping ``bundler.BUNDLER_ID``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .artifacts import Artifact
from .bundler import BUNDLER_ID
from .config import ENTRYPOINT_SOURCE_COMMIT, W1Config, baseline_dir
from .profiles import STANDARD, EvaluationProfile
from .rpc import ANVIL_HARDFORK

ARTIFACT_RELPATH = Path("calibration") / "pvg-overhead.json"
ARTIFACT_VERSION = "1"
BUNDLE_SIZE = 1
SHAPES = ("execute_call", "execute_pool_deposit", "empty_calldata")
#: Shapes a complete calibration of each profile must contain.
SHAPES_BY_PROFILE = {"eip170_standard": ("execute_call", "empty_calldata"),
                     "b3_compat_local": SHAPES}
_POOL_DEPOSIT_SELECTOR = bytes.fromhex("b6b55f25")  # deposit(uint256)


class RecalibrationRequired(RuntimeError):
    """The pinned environment no longer matches the calibration artifact."""


def op_shape(call_data: bytes) -> str:
    if len(call_data) == 0:
        return "empty_calldata"
    if len(call_data) == 196 and call_data[132:136] == _POOL_DEPOSIT_SELECTOR:
        return "execute_pool_deposit"
    return "execute_call"


def environment_fingerprint(cfg: W1Config, arts: Mapping[str, Artifact],
                            anvil_version: str, profile: Optional[EvaluationProfile] = None,
                            b3_arts: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    profile = profile or STANDARD
    bytecode = {name: arts[name].deployed_bytecode_sha256
                for name in ("EntryPoint", "SimpleAccountFactory", "SimpleAccount",
                             "ObservablePaymaster", "SignatureVerifyingPaymaster")}
    fp: Dict[str, Any] = {
        "entrypoint_source_commit": ENTRYPOINT_SOURCE_COMMIT,
        "deployed_bytecode_sha256": bytecode,
        "bundler_version": BUNDLER_ID,
        "bundle_size": BUNDLE_SIZE,
        "beneficiary_prefunded": cfg.funding("beneficiary_eth") > 0,
        "chain_id": cfg.chain_id,
        "hardfork": ANVIL_HARDFORK,
        "anvil_version": anvil_version,
        # A different chain configuration is a different environment.
        "evaluation_profile": profile.profile_id,
        "code_size_limit": profile.effective_code_size_limit,
    }
    if profile.includes_b3_infrastructure:
        if b3_arts is None:
            raise ValueError(f"profile {profile.profile_id} needs the B3 artifacts")
        from .b3 import B3_SOURCE_COMMIT
        fp["b3_source_commit"] = B3_SOURCE_COMMIT
        bytecode.update({f"B3/{name}": a.deployed_bytecode_sha256
                         for name, a in sorted(b3_arts.items())})
    return fp


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def artifact_path(root: Optional[Path] = None, profile_id: str = STANDARD.profile_id) -> Path:
    """One artifact per evaluation profile; the standard one keeps its original path."""
    if profile_id == STANDARD.profile_id:
        return baseline_dir(root) / ARTIFACT_RELPATH
    return baseline_dir(root) / ARTIFACT_RELPATH.with_name(f"pvg-overhead.{profile_id}.json")


def load_artifact(root: Optional[Path] = None,
                  profile_id: str = STANDARD.profile_id) -> Dict[str, Any]:
    path = artifact_path(root, profile_id)
    if not path.is_file():
        raise RecalibrationRequired(
            f"{path} is missing; run `python3 -m experiments.workloads.w1.calibrate "
            f"--profile {profile_id}` before experiment runs")
    return json.loads(path.read_text(encoding="utf-8"))


def overhead_for(artifact: Mapping[str, Any], shape: str,
                 fingerprint: Mapping[str, Any]) -> int:
    if artifact.get("artifact_version") != ARTIFACT_VERSION:
        raise RecalibrationRequired("calibration artifact version mismatch")
    if artifact["environment_fingerprint"] != fingerprint:
        diff = sorted(k for k in fingerprint
                      if artifact["environment_fingerprint"].get(k) != fingerprint[k])
        raise RecalibrationRequired(
            f"environment changed since calibration ({diff}); rerun "
            "`python3 -m experiments.workloads.w1.calibrate`")
    if shape not in artifact["entrypoint_unmeasured_overhead_by_shape"]:
        raise RecalibrationRequired(f"no calibrated overhead for op shape {shape!r}")
    return int(artifact["entrypoint_unmeasured_overhead_by_shape"][shape])


def artifact_sha256(artifact: Mapping[str, Any]) -> str:
    return digest(artifact)
