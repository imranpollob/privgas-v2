"""The preVerificationGas calibration artifact and its environment fingerprint.

The EntryPoint's unmeasured overhead O (gas a bundle transaction spends that
``UserOperationEvent.actualGasUsed`` does not include, beyond the 21,000
intrinsic gas and calldata) is a property of the ENVIRONMENT, not of each
research sample. It is measured once by ``python3 -m
experiments.workloads.w1.calibrate`` (exact-bundle dry runs, ``pvg.calibrate``)
and written to ``baselines/w1_b0_b2/calibration/pvg-overhead.json``.
Experiment runs read O from that artifact and never dry-run their operations.

O is keyed by OPERATION SHAPE, because measurement showed it depends on
whether the UserOperation has callData (a deploy-only op with empty callData
skips the account call inside the EntryPoint's inner frame):

* ``execute_call``   -- non-empty callData (every measured W1 action)
* ``empty_calldata`` -- deploy-only warm-up operation

Across all measured shapes within a class the calibration requires ONE value;
it fails rather than averaging.

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
from .rpc import ANVIL_HARDFORK

ARTIFACT_RELPATH = Path("calibration") / "pvg-overhead.json"
ARTIFACT_VERSION = "1"
BUNDLE_SIZE = 1
SHAPES = ("execute_call", "empty_calldata")


class RecalibrationRequired(RuntimeError):
    """The pinned environment no longer matches the calibration artifact."""


def op_shape(call_data: bytes) -> str:
    return "execute_call" if len(call_data) > 0 else "empty_calldata"


def environment_fingerprint(cfg: W1Config, arts: Mapping[str, Artifact],
                            anvil_version: str) -> Dict[str, Any]:
    return {
        "entrypoint_source_commit": ENTRYPOINT_SOURCE_COMMIT,
        "deployed_bytecode_sha256": {
            name: arts[name].deployed_bytecode_sha256
            for name in ("EntryPoint", "SimpleAccountFactory", "SimpleAccount",
                         "ObservablePaymaster", "SignatureVerifyingPaymaster")},
        "bundler_version": BUNDLER_ID,
        "bundle_size": BUNDLE_SIZE,
        "beneficiary_prefunded": cfg.funding("beneficiary_eth") > 0,
        "chain_id": cfg.chain_id,
        "hardfork": ANVIL_HARDFORK,
        "anvil_version": anvil_version,
    }


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def artifact_path(root: Optional[Path] = None) -> Path:
    return baseline_dir(root) / ARTIFACT_RELPATH


def load_artifact(root: Optional[Path] = None) -> Dict[str, Any]:
    path = artifact_path(root)
    if not path.is_file():
        raise RecalibrationRequired(
            f"{path} is missing; run `python3 -m experiments.workloads.w1.calibrate` "
            "before experiment runs")
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
