"""Deploying the D2-History-K experimental variant WITHOUT modifying frozen B3.

Why this is possible at all
---------------------------
The frozen ``CreditPool`` takes its root-mirror target and its registry as CONSTRUCTOR
arguments::

    constructor(address _creditPaymaster, address _registry)

and its only interaction with the Paymaster is ``creditPaymaster.mirrorRoot(newRoot)``.
So an experimental root-acceptance component can be substituted by deploying the
UNMODIFIED frozen ``CreditPool`` bytecode with a different constructor argument. Nothing
in ``baselines/b3_privgas_v1`` or ``baselines/b3_eval`` changes, and the substitution
touches none of: CreditPool semantics, the Bootstrap flow, the Semaphore verifier, proof
message binding, nullifier handling, the EntryPoint, the account implementation,
Paymaster sponsorship semantics or the W1 application call.

``AnnouncementRegistry`` and ``BootstrapPaymaster`` also hold their peers as immutables,
so a D2K environment is a complete SECOND frozen deployment (pool + bootstrap paymaster +
registry, all unmodified bytecode) whose single difference is the address the pool
mirrors roots to. The first, ordinary frozen deployment made by the W1 setup stays in
place and is still used as the control.

Two deployment shapes
---------------------
``dedicated``  one frozen CreditPool -> exactly one Paymaster, as B3 deploys. Every
               overhead, gas, storage and code-size number comes from here.
``fanout``     one frozen CreditPool -> ``FanOutRootMirror`` -> the frozen CreditPaymaster
               and one HistoryCreditPaymaster per tested K. Used only for the CONTENTION
               experiments, so that every K sees the same deposits, the same roots and the
               same block order (a paired comparison). The fan-out inflates the Bootstrap's
               own gas and is therefore never a source of a gas number.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from eth_abi import encode
from eth_utils import to_checksum_address

from ...recorder.provenance import repo_root
from ...workloads.w1 import abi, b3
from ...workloads.w1.chain import Chain

D2K_DIR = Path("contracts") / "d2k"

#: (artifact file, contract name) for every D2K contract the experiments deploy.
D2K_CONTRACTS = {
    "HistoryCreditPaymaster": ("HistoryCreditPaymaster.sol", "HistoryCreditPaymaster"),
    "FanOutRootMirror": ("FanOutRootMirror.sol", "FanOutRootMirror"),
    "LeanIMTBench": ("GasDecomposition.sol", "LeanIMTBench"),
    "RootMirrorPusher": ("GasDecomposition.sol", "RootMirrorPusher"),
    "MinimalRootMirror": ("GasDecomposition.sol", "MinimalRootMirror"),
    "PoolSurroundBench": ("GasDecomposition.sol", "PoolSurroundBench"),
    "NoopBench": ("GasDecomposition.sol", "NoopBench"),
    "BenchRunner": ("GasDecomposition.sol", "BenchRunner"),
    "PoseidonCallBench": ("GasDecomposition.sol", "PoseidonCallBench"),
}

SIG_HIST_CAPACITY = "historyCapacity()"
SIG_HIST_LENGTH = "historyLength()"
SIG_HIST_ROOTS = "historyRoots()"
SIG_HIST_IS_KNOWN = "isKnownRoot(uint256)"
SIG_HIST_REFCOUNT = "rootRefCount(uint256)"
SIG_HIST_ROOT_AGE = "rootAge(uint256)"
SIG_MIRROR_ROOT = "mirrorRoot(uint256)"
SIG_FANOUT_TARGETS = "targets()"
SIG_BENCH_INSERT = "insert(uint256)"
SIG_BENCH_PUSH = "push(uint256)"
SIG_BENCH_NOOP = "noop(uint256)"
SIG_BENCH_HASH_ONCE = "hashOnce(uint256,uint256)"
SIG_BENCH_STORE_ONLY = "storeOnly(uint256,uint256)"
SIG_SURROUND_DEPOSIT = "deposit(uint256)"
SIG_SURROUND_DEPOSIT_BOOK = "depositWithLeafBookkeeping(uint256)"
SIG_MIRROR_ELIGIBLE = "mirrorEligible(address)"

SELECTOR_MIRROR_ROOT = "0x" + abi.selector(SIG_MIRROR_ROOT).hex()


def d2k_dir(root: Optional[Path] = None) -> Path:
    return (Path(root) if root else repo_root()) / D2K_DIR


def forge_build_d2k(root: Optional[Path] = None) -> str:
    proc = subprocess.run(["forge", "build"], cwd=d2k_dir(root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"forge build (contracts/d2k) failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def load_d2k_artifact(name: str, root: Optional[Path] = None) -> b3.B3Artifact:
    file_name, contract = D2K_CONTRACTS[name]
    path = d2k_dir(root) / "out" / file_name / f"{contract}.json"
    if not path.is_file():
        raise RuntimeError(f"{path} missing; run `make d2k-build`")
    data = json.loads(path.read_text(encoding="utf-8"))
    return b3.B3Artifact(
        name=name, abi=data["abi"], bytecode_hex=data["bytecode"]["object"],
        deployed_hex=data["deployedBytecode"]["object"],
        link_references=data["bytecode"].get("linkReferences", {}),
        immutable_references=data["deployedBytecode"].get("immutableReferences", {}),
        deployed_link_references=data["deployedBytecode"].get("linkReferences", {}))


def load_d2k_all(root: Optional[Path] = None) -> Dict[str, b3.B3Artifact]:
    return {name: load_d2k_artifact(name, root) for name in D2K_CONTRACTS}


# --- deployment ------------------------------------------------------------------------


@dataclass
class DeploymentCost:
    """Deployment gas and runtime code size of one contract (§11 'Deployment')."""

    name: str
    address: str
    deployment_gas: int
    runtime_code_bytes: int
    creation_code_bytes: int


@dataclass
class D2KEnvironment:
    """One D2K deployment: a frozen pool/bootstrap/registry set plus root-acceptance targets."""

    shape: str                                  # "dedicated" | "fanout"
    credit_pool: str
    bootstrap_paymaster: str
    registry: str
    #: address the pool mirrors to (the fan-out, or the single Paymaster)
    mirror_target: str
    #: the frozen CreditPaymaster in this deployment (None for a dedicated K deployment)
    frozen_credit_paymaster: Optional[str]
    #: K -> HistoryCreditPaymaster address
    history_paymasters: Dict[int, str]
    credit_scope: int
    costs: List[DeploymentCost] = field(default_factory=list)

    def paymaster_for(self, variant: str) -> str:
        """``"frozen"`` or ``"K<k>"``."""
        if variant == "frozen":
            if self.frozen_credit_paymaster is None:
                raise KeyError("this deployment has no frozen CreditPaymaster")
            return self.frozen_credit_paymaster
        return self.history_paymasters[int(variant[1:])]

    def variants(self) -> List[str]:
        out = ["frozen"] if self.frozen_credit_paymaster else []
        return out + [f"K{k}" for k in sorted(self.history_paymasters)]

    def contracts(self) -> Dict[str, str]:
        d = {"D2K/CreditPool": self.credit_pool,
             "D2K/BootstrapPaymaster": self.bootstrap_paymaster,
             "D2K/AnnouncementRegistry": self.registry,
             "D2K/MirrorTarget": self.mirror_target}
        if self.frozen_credit_paymaster:
            d["D2K/CreditPaymaster"] = self.frozen_credit_paymaster
        d.update({f"D2K/HistoryCreditPaymaster(K={k})": a
                  for k, a in sorted(self.history_paymasters.items())})
        return d


class _Deployer:
    """Sequential deployer that records gas and code size for every contract."""

    def __init__(self, chain: Chain, account, gas: int) -> None:
        self.chain, self.account, self.gas = chain, account, gas
        self.costs: List[DeploymentCost] = []

    def next_addresses(self, n: int) -> List[str]:
        start = self.chain.nonce(self.account.address, "pending")
        return [b3.create_address(self.account.address, start + i) for i in range(n)]

    def deploy(self, name: str, art: b3.B3Artifact, types: Sequence[str], args: Sequence[Any],
               libraries: Optional[Mapping[str, str]] = None) -> str:
        data = art.linked_bytecode(libraries or {}) + (encode(list(types), list(args))
                                                       if types else b"")
        st = self.chain.send(self.account, label=f"d2k_deploy_{name}", phase="setup", to=None,
                             data=data, gas=self.gas)
        addr = to_checksum_address(st.receipt["contractAddress"])
        code = self.chain.code(addr, self.chain.block_number())
        self.costs.append(DeploymentCost(
            name=name, address=addr, deployment_gas=int(st.receipt["gasUsed"], 16),
            runtime_code_bytes=len(bytes.fromhex(code[2:])), creation_code_bytes=len(data)))
        return addr


def deploy_dedicated(chain: Chain, deployer, *, d2k_arts: Mapping[str, b3.B3Artifact],
                     b3_arts: Mapping[str, b3.B3Artifact], b3cfg: b3.B3Config,
                     entrypoint: str, verifier: str, announcer: str, poseidon: str,
                     history_k: Optional[int], gas: int,
                     registry_eoa: Optional[str] = None) -> D2KEnvironment:
    """One frozen CreditPool -> exactly ONE Paymaster, as B3 deploys.

    ``history_k is None`` deploys the FROZEN CreditPaymaster (the control); otherwise the
    D2-History-K variant with that capacity. Every gas/overhead/storage/code-size number
    in the result document comes from a deployment of this shape.

    ``registry_eoa`` (gas-decomposition benchmarks only) supplies the registry address the
    frozen ``CreditPool`` and ``BootstrapPaymaster`` accept ``mirrorEligible`` from, instead
    of deploying an ``AnnouncementRegistry``. Both contracts take that address as a
    constructor argument, so their code and their eligibility rule are unchanged; it only
    means the benchmark does not pay 0.021 ETH and one announcement transaction for each of
    256 depositors. The announcement path itself is measured separately, on the ordinary
    frozen deployment, by the feasibility-envelope and grant experiments.
    """
    dep = _Deployer(chain, deployer, gas)
    if registry_eoa is not None:
        pm_addr, pool_addr, boot_addr = dep.next_addresses(3)
        reg_addr = to_checksum_address(registry_eoa)
    else:
        pm_addr, pool_addr, boot_addr, reg_addr = dep.next_addresses(4)
    if history_k is None:
        pm = dep.deploy("CreditPaymaster", b3_arts["CreditPaymaster"],
                        ["address", "address", "address"], [entrypoint, pool_addr, verifier])
    else:
        pm = dep.deploy(f"HistoryCreditPaymaster_K{history_k}", d2k_arts["HistoryCreditPaymaster"],
                        ["address", "address", "address", "uint256"],
                        [entrypoint, pool_addr, verifier, int(history_k)])
    pool = dep.deploy("CreditPool", b3_arts["CreditPool"], ["address", "address"],
                      [pm_addr, reg_addr], libraries={"PoseidonT3": poseidon})
    boot = dep.deploy("BootstrapPaymaster", b3_arts["BootstrapPaymaster"],
                      ["address", "address", "address", "bytes4"],
                      [entrypoint, reg_addr, pool_addr, abi.selector(b3.SIG_POOL_DEPOSIT)])
    if registry_eoa is None:
        reg = dep.deploy("AnnouncementRegistry", b3_arts["AnnouncementRegistry"],
                         ["address", "address", "address", "uint256", "uint256"],
                         [announcer, boot_addr, pool_addr, b3cfg.v_min,
                          b3cfg.non_refundable_fee])
    else:
        reg = reg_addr
    if (pm, pool, boot, reg) != (pm_addr, pool_addr, boot_addr, reg_addr):
        raise RuntimeError("D2K dedicated deployment address drift")
    scope = _scope(chain, pm)
    return D2KEnvironment(
        shape="dedicated", credit_pool=pool, bootstrap_paymaster=boot, registry=reg,
        mirror_target=pm, frozen_credit_paymaster=pm if history_k is None else None,
        history_paymasters={} if history_k is None else {int(history_k): pm},
        credit_scope=scope, costs=dep.costs)


def deploy_fanout(chain: Chain, deployer, *, d2k_arts: Mapping[str, b3.B3Artifact],
                  b3_arts: Mapping[str, b3.B3Artifact], b3cfg: b3.B3Config, entrypoint: str,
                  verifier: str, announcer: str, poseidon: str, ks: Sequence[int],
                  gas: int) -> D2KEnvironment:
    """One frozen CreditPool -> FanOutRootMirror -> {frozen CreditPaymaster} U {K variants}.

    CONTENTION EXPERIMENTS ONLY. The frozen CreditPaymaster is deployed alongside the
    variants so "K = 1 reproduces frozen latest-root behaviour" is measured on the same
    chain, in the same trials, against the same roots -- not argued.
    """
    ks = [int(k) for k in ks]
    dep = _Deployer(chain, deployer, gas)
    n = 1 + 1 + len(ks) + 3
    addrs = dep.next_addresses(n)
    fan_addr = addrs[0]
    pm_addrs = addrs[1:1 + 1 + len(ks)]
    pool_addr, boot_addr, reg_addr = addrs[1 + 1 + len(ks):]
    fan = dep.deploy("FanOutRootMirror", d2k_arts["FanOutRootMirror"],
                     ["address", "address[]"], [pool_addr, pm_addrs])
    frozen_pm = dep.deploy("CreditPaymaster", b3_arts["CreditPaymaster"],
                           ["address", "address", "address"], [entrypoint, fan_addr, verifier])
    hist: Dict[int, str] = {}
    for k in ks:
        hist[k] = dep.deploy(f"HistoryCreditPaymaster_K{k}", d2k_arts["HistoryCreditPaymaster"],
                             ["address", "address", "address", "uint256"],
                             [entrypoint, fan_addr, verifier, k])
    pool = dep.deploy("CreditPool", b3_arts["CreditPool"], ["address", "address"],
                      [fan_addr, reg_addr], libraries={"PoseidonT3": poseidon})
    boot = dep.deploy("BootstrapPaymaster", b3_arts["BootstrapPaymaster"],
                      ["address", "address", "address", "bytes4"],
                      [entrypoint, reg_addr, pool_addr, abi.selector(b3.SIG_POOL_DEPOSIT)])
    reg = dep.deploy("AnnouncementRegistry", b3_arts["AnnouncementRegistry"],
                     ["address", "address", "address", "uint256", "uint256"],
                     [announcer, boot_addr, pool_addr, b3cfg.v_min, b3cfg.non_refundable_fee])
    if [fan, frozen_pm, *hist.values(), pool, boot, reg] != [fan_addr, *pm_addrs, pool_addr,
                                                             boot_addr, reg_addr]:
        raise RuntimeError("D2K fan-out deployment address drift")
    for a in (frozen_pm, *hist.values()):
        if _scope(chain, a) != _scope(chain, frozen_pm):
            raise RuntimeError("D2K variant credit scope differs from the frozen contract")
    return D2KEnvironment(
        shape="fanout", credit_pool=pool, bootstrap_paymaster=boot, registry=reg,
        mirror_target=fan, frozen_credit_paymaster=frozen_pm, history_paymasters=hist,
        credit_scope=_scope(chain, frozen_pm), costs=dep.costs)


def _scope(chain: Chain, paymaster: str) -> int:
    return b3.view_uint(chain, paymaster, b3.SIG_CPM_SCOPE)


# --- reads -------------------------------------------------------------------------------


def history_capacity(chain: Chain, pm: str) -> int:
    return b3.view_uint(chain, pm, SIG_HIST_CAPACITY)


def history_length(chain: Chain, pm: str) -> int:
    return b3.view_uint(chain, pm, SIG_HIST_LENGTH)


def is_known_root(chain: Chain, pm: str, root: int) -> bool:
    return bool(b3.view_uint(chain, pm, SIG_HIST_IS_KNOWN, ("uint256",), (root,)))


def root_refcount(chain: Chain, pm: str, root: int) -> int:
    return b3.view_uint(chain, pm, SIG_HIST_REFCOUNT, ("uint256",), (root,))


def root_age(chain: Chain, pm: str, root: int) -> Optional[int]:
    """Age of ``root`` in root-updates (0 = current); None if not retained."""
    from eth_abi import decode
    data = abi.call(SIG_HIST_ROOT_AGE, ["uint256"], [root])
    found, age = decode(["bool", "uint256"], bytes.fromhex(chain.eth_call(pm, data)[2:]))
    return int(age) if found else None


def history_roots(chain: Chain, pm: str) -> List[int]:
    from eth_abi import decode
    (roots,) = decode(["uint256[]"], bytes.fromhex(
        chain.eth_call(pm, abi.selector(SIG_HIST_ROOTS))[2:]))
    return [int(r) for r in roots]


def mirrored_root(chain: Chain, pm: str) -> int:
    """``merkleRoot()`` -- same signature in the frozen contract and the variant."""
    return b3.view_uint(chain, pm, b3.SIG_CPM_MERKLE_ROOT)
