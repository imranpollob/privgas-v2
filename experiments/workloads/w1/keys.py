"""Seed-derived keys for every W1 role.

Keys depend on (seed, role) only -- never on the baseline -- so B0, B1 and B2
run with the same seed share the same asset sender, destination, bundler and
recipient key. That is part of holding the comparison constant.

Private keys are never written to disk. The seed regenerates them, and the
seed itself is secret (docs/experiment-schema.md Sec. 8.3).

The faucet is anvil's well-known dev account 0 and is used only in the setup
phase. It is not a W1 participant.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict

from eth_account import Account

SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

#: anvil default mnemonic, account 0 (public, documented dev key).
ANVIL_FAUCET_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

ROLES = (
    "deployer",          # deploys the shared environment (setup only)
    "asset_sender",      # sends the ERC-20 (and, in B0/B1, the ETH allowance)
    "recipient",         # B0: the fresh EOA. B1/B2: the fresh account's owner key
    "destination",       # receives the token in step 2 (never signs)
    "bundler",           # in-repo instrumented bundler EOA (B1/B2)
    "beneficiary",       # EntryPoint beneficiary (never signs)
    "sponsor_operator",  # owner of both Paymasters (deposits; B2-Allowlist allowlisting)
    "sponsor_signer",    # B2-Signature authorization key; signs off chain, never transacts
    "established_wallet",  # the actor's pre-existing wallet W; never on chain in W1
    "block_producer",    # anvil coinbase, receives priority fees (never signs)
    "intruder",          # key for negative tests only
    "announcement_ephemeral",  # B3: ephemeral key whose public key is announced; never transacts
)


def derive_key(seed: int, role: str) -> bytes:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    counter = 0
    while True:
        digest = hashlib.sha256(
            f"privgas-v2/w1/key/v1/{seed}/{role}/{counter}".encode()).digest()
        k = int.from_bytes(digest, "big")
        if 0 < k < SECP256K1_N:
            return digest
        counter += 1  # pragma: no cover - probability ~2^-128


@dataclass(frozen=True)
class RoleKeys:
    seed: int
    keys: Dict[str, bytes]

    def account(self, role: str):
        return Account.from_key(self.keys[role])

    def address(self, role: str) -> str:
        return self.account(role).address

    def addresses(self) -> Dict[str, str]:
        return {role: self.address(role) for role in ROLES}


def role_keys(seed: int) -> RoleKeys:
    return RoleKeys(seed=seed, keys={r: derive_key(seed, r) for r in ROLES})


def semaphore_identity_secret(seed: int, index: int = 0) -> str:
    """B3: secret of the recipient's Semaphore v4 identity (``new Identity(secret)``).

    Derived from the secret seed only; never written to disk. Its commitment is
    public once deposited; the secret is what makes the Spend proof possible.
    """
    return hashlib.sha256(
        f"privgas-v2/w1/b3-semaphore-identity/v1/{seed}/{index}".encode()).hexdigest()


def faucet():
    return Account.from_key(ANVIL_FAUCET_KEY)


def opaque_handle(seed: int, kind: str, role: str) -> str:
    """Opaque hidden identifier for ground truth, e.g. ``actor_3f9a1c2b``.

    Derived from the (secret) seed so it is stable across B0/B1/B2 of the
    same seed, and never address-shaped (RE_OPAQUE_ID).
    """
    h = hashlib.sha256(f"privgas-v2/w1/handle/v1/{seed}/{role}".encode())
    return f"{kind}_{h.hexdigest()[:10]}"
