"""Independent per-actor identities for the D1 multi-actor pilot.

Every identifier of every actor is drawn from its own deterministic stream,
keyed by (secret run seed, pool size, private slot, identity kind) only:

* ``actor``            opaque actor handle (the hidden person, R3's answer)
* ``wallet``           established wallet W (a real secp256k1 key; never
                       transacts in W1) and its opaque handle
* ``asset_sender``     the account that pays the actor (key + handle); in
                       B0/B1 also the economic gas funder
* ``recipient``        the fresh recipient key: the B0 EOA itself, or the
                       owner of the counterfactual SimpleAccount (B1/B2/B3)
* ``stealth``          opaque handle of the fresh recipient account
* ``semaphore``        B3 Semaphore v4 identity secret
* ``credit`` / ``issuance``  B3 opaque credit and issuance handles
* ``ephemeral``        B3 announcement ephemeral key (never transacts)
* ``issuer``           B4-CrossAccount: owner key of the ISSUER SimpleAccount, which
                       is announced, bootstraps and deposits the commitment; distinct
                       from the recipient (spender) key, never derived from it
* ``issuer_funder``    B4-CrossAccount: the wallet that pays the issuer account's
                       ``announceAndFund`` admission (funded by the faucet); distinct
                       from the asset sender so no public funding edge joins the
                       issuer and the spender

No identifier is computed from another identifier (a handle is not a hash of
an address, a Semaphore secret is not derived from the recipient key, ...):
two identifiers of one actor share only the secret seed and the slot. The slot
is a private generation index; nothing public is ordered by it (the schedule
draws every public order from separate streams, ``schedule.py``).

Different pool sizes of one seed are independent actor populations (the pool
size is part of every derivation), so no actor is shared between runs of
different pool sizes. Baselines and scenarios at the same (seed, pool size)
share actors on purpose: that is the matched comparison.

Private keys and secrets are never written to disk; the seed regenerates them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List

from eth_account import Account

SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
DOMAIN = "privgas-v2/d1/actor/v1"

KINDS = ("actor", "wallet", "asset_sender", "recipient", "stealth", "semaphore",
         "credit", "issuance", "ephemeral", "issuer", "issuer_funder")


def _draw(seed: int, pool_size: int, slot: int, kind: str, counter: int = 0) -> bytes:
    if kind not in KINDS:
        raise ValueError(f"unknown identity kind {kind!r}")
    return hashlib.sha256(
        f"{DOMAIN}/{seed}/{pool_size}/{slot}/{kind}/{counter}".encode()).digest()


def _key(seed: int, pool_size: int, slot: int, kind: str) -> bytes:
    counter = 0
    while True:
        k = _draw(seed, pool_size, slot, kind, counter)
        if 0 < int.from_bytes(k, "big") < SECP256K1_N:
            return k
        counter += 1  # pragma: no cover - probability ~2^-128


def _handle(prefix: str, seed: int, pool_size: int, slot: int, kind: str) -> str:
    # A separate stream from any key of the same kind ("handle/" namespace).
    h = hashlib.sha256(
        f"{DOMAIN}/handle/{seed}/{pool_size}/{slot}/{kind}".encode()).hexdigest()
    return f"{prefix}_{h[:12]}"


@dataclass(frozen=True)
class Actor:
    slot: int                  # PRIVATE generation index
    actor_handle: str
    wallet_key: bytes
    wallet_handle: str
    asset_sender_key: bytes
    asset_sender_handle: str
    recipient_key: bytes
    semaphore_secret: str
    ephemeral_key: bytes
    credit_handle: str
    issuance_handle: str
    issuer_key: bytes          # B4-CrossAccount issuer account owner
    issuer_funder_key: bytes   # B4-CrossAccount admission payer
    _seed: int
    _pool_size: int

    @property
    def wallet(self):
        return Account.from_key(self.wallet_key)

    @property
    def asset_sender(self):
        return Account.from_key(self.asset_sender_key)

    @property
    def recipient(self):
        return Account.from_key(self.recipient_key)

    @property
    def ephemeral(self):
        return Account.from_key(self.ephemeral_key)

    @property
    def issuer(self):
        return Account.from_key(self.issuer_key)

    @property
    def issuer_funder(self):
        return Account.from_key(self.issuer_funder_key)

    def issuer_handle(self) -> str:
        """Opaque handle of the B4-CrossAccount issuer account."""
        return _handle("stealth", self._seed, self._pool_size, self.slot, "issuer")

    def stealth_handle(self, baseline_id: str) -> str:
        """Opaque handle of this actor's fresh account under one baseline (an
        EOA in B0 and a SimpleAccount elsewhere are different accounts)."""
        slug = baseline_id.lower().replace("-", "")
        h = hashlib.sha256(
            f"{DOMAIN}/handle/{self._seed}/{self._pool_size}/{self.slot}/stealth/{slug}"
            .encode()).hexdigest()
        return f"stealth_{h[:12]}"


def make_actors(seed: int, pool_size: int) -> List[Actor]:
    if pool_size < 1:
        raise ValueError("pool_size must be >= 1")
    actors = []
    for slot in range(pool_size):
        actors.append(Actor(
            slot=slot,
            actor_handle=_handle("actor", seed, pool_size, slot, "actor"),
            wallet_key=_key(seed, pool_size, slot, "wallet"),
            wallet_handle=_handle("wallet", seed, pool_size, slot, "wallet"),
            asset_sender_key=_key(seed, pool_size, slot, "asset_sender"),
            asset_sender_handle=_handle("sender", seed, pool_size, slot, "asset_sender"),
            recipient_key=_key(seed, pool_size, slot, "recipient"),
            semaphore_secret=_draw(seed, pool_size, slot, "semaphore").hex(),
            ephemeral_key=_key(seed, pool_size, slot, "ephemeral"),
            credit_handle=_handle("credit", seed, pool_size, slot, "credit"),
            issuance_handle=_handle("issuance", seed, pool_size, slot, "issuance"),
            issuer_key=_key(seed, pool_size, slot, "issuer"),
            issuer_funder_key=_key(seed, pool_size, slot, "issuer_funder"),
            _seed=seed, _pool_size=pool_size))
    _check_distinct(actors)
    return actors


def sponsor_handle(seed: int) -> str:
    """The shared sponsor-operator wallet (B2/B3 economic gas funder)."""
    h = hashlib.sha256(f"{DOMAIN}/handle/{seed}/sponsor_operator".encode()).hexdigest()
    return f"sponsor_{h[:12]}"


def _check_distinct(actors: List[Actor]) -> None:
    handles: Dict[str, int] = {}
    keys: Dict[bytes, int] = {}
    for a in actors:
        for h in (a.actor_handle, a.wallet_handle, a.asset_sender_handle, a.credit_handle,
                  a.issuance_handle, a.stealth_handle("B0"), a.stealth_handle("B1"),
                  a.issuer_handle()):
            if h in handles:  # pragma: no cover - 48-bit handles, tiny pools
                raise RuntimeError(f"handle collision {h}")
            handles[h] = a.slot
        for k in (a.wallet_key, a.asset_sender_key, a.recipient_key, a.ephemeral_key,
                  a.issuer_key, a.issuer_funder_key):
            if k in keys:  # pragma: no cover
                raise RuntimeError("key collision")
            keys[k] = a.slot
