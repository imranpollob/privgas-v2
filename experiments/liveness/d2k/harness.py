"""D2K chain: the frozen D2 pilot harness plus one D2K deployment.

``D2KChain`` extends the FROZEN D2 pilot's ``D2Chain`` (``experiments/liveness/d2``,
imported unchanged) and adds nothing to the protocol path. After the ordinary W1 + frozen
B3 setup it deploys a second, complete, UNMODIFIED frozen B3 credit deployment
(``CreditPool`` / ``BootstrapPaymaster`` / ``AnnouncementRegistry``) whose only difference
is the address the pool mirrors roots to (``mitigation.py`` explains why this needs no
change to frozen code), and rebinds ``env.b3`` to it so every inherited method --
``announce``, ``bootstrap_op``, ``bootstrap_now``, ``build_pool``, ``prove_for``,
``with_proof`` -- operates on the D2K deployment without being rewritten.

The ORIGINAL frozen deployment made by the W1 setup is kept (``frozen_b3``) and is used
as the untouched control for the gas-decomposition reproduction check.

Everything that is not the root-acceptance component is identical to the pilot: the same
staged bundler, the same simulation method, the same preVerificationGas calibration, the
same Semaphore prover and artifacts, the same W1 application call, the same
``b3_compat_local`` profile.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...workloads.w1 import abi, b3
from ...workloads.w1.prover import group_depth
from ...workloads.w1.userop import (UserOp, ep_nonce, get_userop_hash, init_code,
                                    sign_userop)
from ..d2.harness import (D2Chain, HarnessInvariantViolation, ProofRecord,
                          SPEND_PRICING_PLACEHOLDER)
from . import mitigation


class D2KChain(D2Chain):
    """One anvil chain with the W1 + frozen-B3 setup and a D2K deployment on top.

    ``shape="fanout"``    -> contention experiments (all variants, one arrival stream).
    ``shape="dedicated"`` -> one root-acceptance component only; the source of every
                             gas / overhead / storage / code-size number.
    """

    def __init__(self, seed: int, d2cfg: Dict[str, Any], *, shape: str = "fanout",
                 ks: Sequence[int] = (1,), history_k: Optional[int] = None,
                 registry_eoa_role: Optional[str] = None,
                 root: Optional[Path] = None) -> None:
        super().__init__(seed, d2cfg, root)
        self.shape = shape
        self.ks = [int(k) for k in ks]
        self.history_k = history_k
        #: gas-decomposition benchmarks only: grant eligibility from this role's EOA
        #: instead of deploying an AnnouncementRegistry (see mitigation.deploy_dedicated).
        self.registry_eoa_role = registry_eoa_role
        self.d2k_arts = mitigation.load_d2k_all(self.root_dir)
        self.frozen_b3: Optional[b3.B3Environment] = None
        self.d2k: Optional[mitigation.D2KEnvironment] = None

    def _setup(self) -> None:
        super()._setup()
        self.frozen_b3 = self.env.b3
        deployer = self.keys.account("deployer")
        gas = self.cfg.gas_limit("deployment")
        common = dict(d2k_arts=self.d2k_arts, b3_arts=self.b3arts, b3cfg=self.b3cfg,
                      entrypoint=self.env.entrypoint,
                      verifier=self.frozen_b3.semaphore_verifier,
                      announcer=self.frozen_b3.announcer,
                      poseidon=self.frozen_b3.poseidon_t3, gas=gas)
        if self.shape == "fanout":
            self.d2k = mitigation.deploy_fanout(self.chain, deployer, ks=self.ks, **common)
        elif self.shape == "dedicated":
            self.d2k = mitigation.deploy_dedicated(
                self.chain, deployer, history_k=self.history_k,
                registry_eoa=(self.keys.address(self.registry_eoa_role)
                              if self.registry_eoa_role else None), **common)
        else:
            raise ValueError(self.shape)
        # Fund the D2K BootstrapPaymaster and every credit Paymaster's EntryPoint deposit
        # exactly as the W1 setup funds the frozen pair, plus the D2 top-up.
        topup = int(self.d2["setup"]["paymaster_extra_deposit"])
        base = self.b3cfg.paymaster_deposit
        targets = [self.d2k.bootstrap_paymaster]
        if self.d2k.frozen_credit_paymaster:
            targets.append(self.d2k.frozen_credit_paymaster)
        targets += list(self.d2k.history_paymasters.values())
        # A D2K deployment holds up to eight Paymasters; top the sponsor operator up first
        # so it can fund every EntryPoint deposit (experiment setup, not B3).
        from ...workloads.w1.keys import faucet
        self.chain.send(faucet(), label="d2k_setup_sponsor_topup", phase="setup",
                        to=self.keys.address("sponsor_operator"),
                        value=len(targets) * (base + topup) + 10 ** 18,
                        gas=self.cfg.gas_limit("native_transfer"))
        for pm in targets:
            self.chain.send(self.keys.account("sponsor_operator"), label="d2k_setup_pm_deposit",
                            phase="setup", to=self.env.entrypoint,
                            data=abi.call(b3.SIG_EP_DEPOSIT_TO, ["address"], [pm]),
                            value=base + topup, gas=self.cfg.gas_limit("setup_call"))
        # Rebind: from here on every inherited method uses the D2K deployment.
        self.env.b3 = replace(
            self.frozen_b3, credit_pool=self.d2k.credit_pool,
            bootstrap_paymaster=self.d2k.bootstrap_paymaster, registry=self.d2k.registry,
            credit_paymaster=(self.d2k.frozen_credit_paymaster
                              or self.d2k.mirror_target), credit_scope=self.d2k.credit_scope)
        self.setup_end_block = self.chain.block_number()

    def grant_eligibility(self, p) -> None:
        """Benchmark-only replacement for ``announce``: the EOA registry marks an account
        eligible in the frozen ``CreditPool`` and ``BootstrapPaymaster`` directly. Both
        contracts take the registry address as a constructor argument, so neither their
        code nor their eligibility rule changes; only the 0.021 ETH announcement and its
        transaction are skipped, 256 times over. Never used by a contention experiment."""
        if not self.registry_eoa_role:
            raise HarnessInvariantViolation("grant_eligibility needs an EOA registry")
        reg = self.keys.account(self.registry_eoa_role)
        for target in (self.d2k.credit_pool, self.d2k.bootstrap_paymaster):
            st = self.chain.send(reg, label="d2k_bench_mirror_eligible", phase="setup",
                                 to=target,
                                 data=abi.call(mitigation.SIG_MIRROR_ELIGIBLE, ["address"],
                                               [p.account]),
                                 gas=self.cfg.gas_limit("setup_call"))
            if int(st.receipt["status"], 16) != 1:
                raise HarnessInvariantViolation("mirrorEligible reverted")
        p.announced = True

    # -- reads -----------------------------------------------------------------------

    def root(self) -> int:
        """The root every acceptance component was last given.

        In both shapes this is the pool's own current root; the mirrored value is checked
        against it by ``assert_mirrors_agree`` rather than assumed.
        """
        return self.pool_root()

    def variant_root(self, variant: str) -> int:
        return mitigation.mirrored_root(self.chain, self.d2k.paymaster_for(variant))

    def assert_mirrors_agree(self) -> None:
        pool = self.pool_root()
        for v in self.d2k.variants():
            if self.variant_root(v) != pool:
                raise HarnessInvariantViolation(
                    f"variant {v} mirrored root != CreditPool.currentRoot()")

    def history_state(self, variant: str) -> Dict[str, Any]:
        pm = self.d2k.paymaster_for(variant)
        if variant == "frozen":
            return {"variant": variant, "capacity": 1,
                    "roots": [str(mitigation.mirrored_root(self.chain, pm))]}
        return {"variant": variant, "capacity": mitigation.history_capacity(self.chain, pm),
                "length": mitigation.history_length(self.chain, pm),
                "roots": [str(r) for r in mitigation.history_roots(self.chain, pm)]}

    def accepts_root(self, variant: str, root: int) -> bool:
        """Whether this acceptance component would pass a proof naming ``root`` now."""
        pm = self.d2k.paymaster_for(variant)
        if variant == "frozen":
            return mitigation.mirrored_root(self.chain, pm) == root
        return mitigation.is_known_root(self.chain, pm, root)

    def root_age(self, variant: str, root: int) -> Optional[int]:
        if variant == "frozen":
            return 0 if mitigation.mirrored_root(self.chain, self.d2k.paymaster_for(variant)) == root \
                else None
        return mitigation.root_age(self.chain, self.d2k.paymaster_for(variant), root)

    def nullifier_spent_for(self, variant: str, proof: ProofRecord) -> bool:
        return bool(b3.view_uint(self.chain, self.d2k.paymaster_for(variant),
                                 b3.SIG_CPM_NULLIFIER_SPENT, ("uint256",),
                                 (int(proof.proof["nullifier"]),)))

    def pm_deposit_variant(self, variant: str) -> int:
        from ...workloads.w1.userop import ep_deposit
        return ep_deposit(self.chain, self.env.entrypoint, self.d2k.paymaster_for(variant),
                          self.chain.block_number())

    # -- spend ------------------------------------------------------------------------

    def spend_op_for(self, p, variant: str, max_fee: Optional[int] = None,
                     call_gas_limit: Optional[int] = None) -> Tuple[UserOp, str]:
        """``D2Chain.spend_op`` with an explicit credit Paymaster.

        Identical in every other field: the same W1 application call, the same account
        verification and call gas limits, the same frozen
        ``spend_paymaster_verification_gas_limit``, the same all-non-zero proof
        placeholder for preVerificationGas pricing, the same account signature over a
        userOpHash that excludes the proof.
        """
        fee = max_fee or self.cfg.max_fee
        pm = self.d2k.paymaster_for(variant)
        nonce = ep_nonce(self.chain, self.env.entrypoint, p.account, self.cfg.nonce_key)
        call_data = self.app_call

        def build(pvg: int) -> UserOp:
            op = UserOp(sender=p.account, nonce=nonce, init_code=b"", call_data=call_data,
                        verification_gas_limit=self.cfg.verification_gas_limit,
                        call_gas_limit=call_gas_limit or self.cfg.call_gas_limit,
                        pre_verification_gas=pvg,
                        max_priority_fee_per_gas=min(self.cfg.max_priority_fee, fee),
                        max_fee_per_gas=fee, paymaster=pm,
                        paymaster_verification_gas_limit=self.b3cfg.userop(
                            "spend_paymaster_verification_gas_limit"),
                        paymaster_post_op_gas_limit=self.b3cfg.userop("paymaster_post_op_gas_limit"))
            op.paymaster_signature = SPEND_PRICING_PLACEHOLDER
            sign_userop(self.chain, self.env.entrypoint, op, p.owner)
            return op

        build.call_data = call_data  # type: ignore[attr-defined]
        op = self._estimate(build)
        op.paymaster_signature = b3.PLACEHOLDER_PROOF
        h = get_userop_hash(self.chain, self.env.entrypoint, op)
        return op, h

    def prove_against(self, p, message_hex: str, members: List[int], *,
                      scope: Optional[int] = None, use_cache: bool = True) -> ProofRecord:
        """A real proof over an EXPLICIT member list (a historical prefix, for instance),
        optionally with a wrong scope (a negative control). Never checks the live root."""
        mem = list(members)
        depth = group_depth(len(mem))
        message = int(message_hex, 16)
        sc = self.env.b3.credit_scope if scope is None else int(scope)
        key = (p.semaphore_secret, hash(tuple(mem)), message, depth, sc)
        if use_cache and key in self.proof_cache:
            rec = self.proof_cache[key]
            return ProofRecord(rec.proof, rec.root, rec.depth, rec.group_size, rec.prove_ms,
                               rec.verify_off_chain_ms, True)
        res = self.prover.prove(identity_secret=p.semaphore_secret, members=mem, message=message,
                                scope=sc, merkle_tree_depth=depth, label="d2k")
        self.proofs_generated += 1
        self.proving_ms_total += res.prove_ms
        if int(res.proof["merkleTreeRoot"]) != res.group_root:
            raise HarnessInvariantViolation("proof merkleTreeRoot != prover group root")
        rec = ProofRecord(res.proof, res.group_root, depth, len(mem), res.prove_ms,
                          res.verify_off_chain_ms, False)
        if use_cache:
            self.proof_cache[key] = rec
        return rec
