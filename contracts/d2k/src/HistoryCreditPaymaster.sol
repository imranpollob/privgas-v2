// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IPaymaster} from "account-abstraction/interfaces/IPaymaster.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {UserOperationLib} from "account-abstraction/core/UserOperationLib.sol";
import {ISemaphoreVerifier} from "@semaphore-protocol/contracts/interfaces/ISemaphoreVerifier.sol";
import {ISemaphore} from "@semaphore-protocol/contracts/interfaces/ISemaphore.sol";

/// @title HistoryCreditPaymaster — the D2-History-K EXPERIMENTAL variant
/// @notice NON-PRODUCTION | EXPERIMENTAL-MITIGATION | EVALUATION-ONLY.
///
///         This is NOT a proposed protocol. It is the single-difference
///         experimental variant of the frozen B3 `CreditPaymaster`
///         (baselines/b3_privgas_v1 @ 02a3f0ab…e43a3e) used by the D2
///         kill-condition experiment (docs/d2-killcondition-results.md).
///
///         THE ONLY INTENDED SEMANTIC DIFFERENCE
///         -------------------------------------
///         Frozen:      `proof.merkleTreeRoot` must equal the ONE mirrored root.
///         D2-History-K: `proof.merkleTreeRoot` must be one of the K most
///                       recently mirrored roots (current root included).
///
///         Everything else is copied verbatim from the frozen contract and must
///         stay byte-for-byte equivalent in behaviour: the cost/gas/fee caps,
///         the credit scope constant, the paymasterAndData layout, the
///         `PAYMASTER_SIG_MAGIC` convention, proof decoding, the
///         message/scope binding, `_hashForCircuit`, nullifier handling,
///         `postOp`, the `onlyEntryPoint` modifier, the `mirrorRoot` caller
///         check, the `RootMirrored`/`CreditSpent` events and every error type.
///         A diff against the frozen source should show only the root-history
///         storage, `mirrorRoot`'s body, step 3 of validation and the extra
///         view helpers.
///
///         BOUNDED ROOT HISTORY — exact retention semantics
///         ------------------------------------------------
///         * `K` (immutable, >= 1) is the history CAPACITY in roots. The current
///           root counts toward K: K = 1 keeps only the current root and is
///           therefore latest-root-only, i.e. frozen behaviour; K = 8 keeps the
///           current root and the 7 roots before it.
///         * ENTRY: a root enters the history when `CreditPool.deposit` pushes it
///           through `mirrorRoot`. Nothing else can insert a root.
///         * EXIT: the ring slot about to be overwritten is evicted at that same
///           moment. With K distinct roots held, the (K+1)-th update evicts the
///           oldest. A root is therefore accepted for exactly K - 1 subsequent
///           root updates and rejected from the K-th onwards.
///         * STORAGE: a K-slot ring buffer `_ring` plus a refcount map `_count`
///           and the write cursor `_head`. Steady-state footprint is 2K + 1
///           non-zero slots, independent of how many roots have ever existed.
///           No unbounded "every root ever seen" mapping exists.
///         * LOOKUP: O(1) in K — one `SLOAD` of `_count[root]`, the same shape as
///           the frozen contract's single `_merkleRoot` SLOAD.
///         * UPDATE: O(1) in K — one SLOAD of the evicted slot, one refcount
///           decrement, one ring write, one refcount increment, one cursor write.
///         * DUPLICATES: `_count` is a refcount, not a flag, so a root mirrored
///           twice occupies two ring slots and stays valid until BOTH are
///           evicted. Retention is therefore deterministic and never depends on
///           eviction order.
///         * ROOT 0 is the empty-slot sentinel. It is never counted and never
///           accepted: a LeanIMT root is a Poseidon output over a non-zero leaf,
///           and `_insert` rejects a zero leaf, so 0 is not a reachable root.
///
///         WHAT THIS DOES NOT CHANGE
///         -------------------------
///         Nullifiers are scope-fixed in the frozen design
///         (`CREDIT_NULLIFIER_SCOPE` is a constant, not a function of the root),
///         so one credit yields the SAME nullifier whichever retained root it
///         proves against: accepting an old root cannot enable a second spend.
///         Membership in `CreditPool` is append-only (`InternalLeanIMT._insert`
///         only; no `_update`, no `_remove`; `_eligible`/`_used` are only ever
///         set to true), so an older root is a prefix of later membership and
///         cannot re-authorise a revoked commitment. Both properties are
///         re-established experimentally, not assumed.
///
///         ERC-7562: validation reads only this contract's own storage
///         (`_count`, `_ring`, `_head`, `_nullifiers`). `_count` is keyed by a
///         calldata value rather than by `msg.sender`, exactly as the frozen
///         contract's `_nullifiers[proof.nullifier]` already is, so no new
///         storage-rule class is introduced. Like the frozen contract this must
///         be staked before going live; NO staking or production-bundler claim
///         is made or tested here.
contract HistoryCreditPaymaster is IPaymaster {
    using UserOperationLib for PackedUserOperation;

    // ── Frozen constants (verbatim) ──────────────────────────────────────────
    uint256 public constant MAX_CREDIT_GAS = 500_000;
    uint256 public constant MAX_ACCEPTED_MAX_FEE_PER_GAS = 10 gwei;
    uint256 public constant CREDIT_NULLIFIER_SCOPE = uint256(keccak256("stealth-protocol.credit.v1"));
    uint256 public constant MAX_SPONSORSHIP_COST = MAX_CREDIT_GAS * MAX_ACCEPTED_MAX_FEE_PER_GAS;

    address public immutable entryPoint;
    address public immutable creditPool; // only caller allowed for mirrorRoot

    ISemaphoreVerifier public immutable verifier;

    /// @notice Root-history capacity K (>= 1). K = 1 is latest-root-only.
    uint256 public immutable historyCapacity;

    // ── Bounded root history (the ONE experimental difference) ───────────────
    /// @dev Next ring slot to write. `_ring[(_head + K - 1) % K]` is the current root.
    uint256 private _head;

    // Spent nullifiers — same position and semantics as the frozen contract.
    mapping(uint256 => bool) private _nullifiers;

    /// @dev Ring buffer of the K most recent roots; slot value 0 means "empty".
    mapping(uint256 => uint256) private _ring;
    /// @dev How many ring slots currently hold this root (0 = not accepted).
    mapping(uint256 => uint256) private _count;

    // ── Frozen errors (verbatim) ─────────────────────────────────────────────
    error NotEntryPoint();
    error NotCreditPool();
    error InvalidProof();
    error NullifierSpent(uint256 nullifier);
    error GasCapExceeded(uint256 requested, uint256 cap);
    error GasPriceCapExceeded(uint256 requested, uint256 cap);
    error MaxCostExceeded(uint256 requested, uint256 cap);
    error RootMismatch(uint256 proofRoot, uint256 storedRoot);
    error WrongScope();
    error WrongMessage();
    /// @dev Experimental-variant-only: rejects a nonsensical deployment.
    error ZeroHistoryCapacity();

    event RootMirrored(uint256 indexed newRoot);
    event CreditSpent(uint256 indexed nullifier, address indexed sender);

    modifier onlyEntryPoint() {
        if (msg.sender != entryPoint) revert NotEntryPoint();
        _;
    }

    constructor(address _entryPoint, address _creditPool, address _verifier, uint256 _historyCapacity) {
        if (_historyCapacity == 0) revert ZeroHistoryCapacity();
        entryPoint = _entryPoint;
        creditPool = _creditPool;
        verifier = ISemaphoreVerifier(_verifier);
        historyCapacity = _historyCapacity;
    }

    /// @notice Called by CreditPool.deposit() after each insertion. Inserts the new
    ///         root into the ring buffer and evicts whatever occupied that slot.
    ///         O(1) in K.
    function mirrorRoot(uint256 newRoot) external {
        if (msg.sender != creditPool) revert NotCreditPool();
        uint256 k = historyCapacity;
        uint256 i = _head;
        uint256 evicted = _ring[i];
        if (evicted != 0) {
            uint256 remaining;
            unchecked {
                remaining = _count[evicted] - 1;
            }
            if (remaining == 0) {
                delete _count[evicted];
            } else {
                _count[evicted] = remaining;
            }
        }
        _ring[i] = newRoot;
        unchecked {
            _count[newRoot] = _count[newRoot] + 1;
            _head = i + 1 == k ? 0 : i + 1;
        }
        emit RootMirrored(newRoot);
    }

    /// @notice ERC-4337 paymaster validation. Reads only own storage.
    function validatePaymasterUserOp(
        PackedUserOperation calldata userOp,
        bytes32 userOpHash,
        uint256 maxCost
    ) external override onlyEntryPoint returns (bytes memory context, uint256 validationData) {
        // ── 0. Sponsorship budget (frozen) ──────────────────────────────────
        if (maxCost > MAX_SPONSORSHIP_COST) {
            revert MaxCostExceeded(maxCost, MAX_SPONSORSHIP_COST);
        }

        // ── 1. Gas cap (frozen) ─────────────────────────────────────────────
        uint256 callGas = userOp.unpackCallGasLimit();
        uint256 verifyGas = userOp.unpackVerificationGasLimit();
        if (callGas + verifyGas > MAX_CREDIT_GAS) {
            revert GasCapExceeded(callGas + verifyGas, MAX_CREDIT_GAS);
        }

        uint256 maxFeePerGas = userOp.unpackMaxFeePerGas();
        if (maxFeePerGas > MAX_ACCEPTED_MAX_FEE_PER_GAS) {
            revert GasPriceCapExceeded(maxFeePerGas, MAX_ACCEPTED_MAX_FEE_PER_GAS);
        }

        // ── 2. Decode proof (frozen) ────────────────────────────────────────
        bytes calldata proofBytes = UserOperationLib.getPaymasterSignature(userOp.paymasterAndData);
        if (proofBytes.length == 0) revert InvalidProof();
        ISemaphore.SemaphoreProof memory proof = abi.decode(proofBytes, (ISemaphore.SemaphoreProof));

        // ── 3. Root check — THE ONLY SEMANTIC DIFFERENCE ────────────────────
        // Frozen: `if (proof.merkleTreeRoot != _merkleRoot) revert RootMismatch(...)`.
        // Here: accept any of the K retained roots. One own-storage SLOAD, O(1) in K.
        // The reported `storedRoot` is still the CURRENT root, so the error is
        // shaped exactly like the frozen one for any tooling that parses it.
        if (_count[proof.merkleTreeRoot] == 0) {
            revert RootMismatch(proof.merkleTreeRoot, _currentRoot());
        }

        // ── 4. Proof binding (frozen) ───────────────────────────────────────
        uint256 uopHashUint = uint256(userOpHash);
        if (proof.scope != CREDIT_NULLIFIER_SCOPE) revert WrongScope();
        if (proof.message != uopHashUint) revert WrongMessage();

        // ── 5. Replay check (frozen) ────────────────────────────────────────
        if (_nullifiers[proof.nullifier]) revert NullifierSpent(proof.nullifier);

        // ── 6. ZK proof verification (frozen) ───────────────────────────────
        bool valid = verifier.verifyProof(
            [proof.points[0], proof.points[1]],
            [[proof.points[2], proof.points[3]], [proof.points[4], proof.points[5]]],
            [proof.points[6], proof.points[7]],
            [
                proof.merkleTreeRoot,
                proof.nullifier,
                _hashForCircuit(proof.message),
                _hashForCircuit(proof.scope)
            ],
            proof.merkleTreeDepth
        );
        if (!valid) revert InvalidProof();

        // ── 7. Mark nullifier spent (frozen) ─────────────────────────────────
        _nullifiers[proof.nullifier] = true;

        emit CreditSpent(proof.nullifier, userOp.sender);

        return ("", 0);
    }

    /// @dev Required by IPaymaster. Not called when context is empty. (frozen)
    function postOp(PostOpMode, bytes calldata, uint256, uint256) external override onlyEntryPoint {}

    // ── Internal ─────────────────────────────────────────────────────────────

    /// @dev Matches Semaphore.sol's _hash(): keccak256(abi.encodePacked(x)) >> 8. (frozen)
    function _hashForCircuit(uint256 x) private pure returns (uint256) {
        return uint256(keccak256(abi.encodePacked(x))) >> 8;
    }

    /// @dev Most recently mirrored root (0 before the first deposit). Derived from
    ///      the ring, so publishing a root costs no extra storage slot.
    function _currentRoot() private view returns (uint256) {
        uint256 i = _head;
        unchecked {
            return _ring[i == 0 ? historyCapacity - 1 : i - 1];
        }
    }

    // ── View helpers ─────────────────────────────────────────────────────────

    /// @notice Same signature and meaning as the frozen contract's `merkleRoot()`.
    function merkleRoot() external view returns (uint256) {
        return _currentRoot();
    }

    function isNullifierSpent(uint256 nullifier) external view returns (bool) {
        return _nullifiers[nullifier];
    }

    /// @notice True iff a proof naming `root` would pass the root check now.
    function isKnownRoot(uint256 root) external view returns (bool) {
        return root != 0 && _count[root] != 0;
    }

    /// @notice How many ring slots this root currently occupies.
    function rootRefCount(uint256 root) external view returns (uint256) {
        return _count[root];
    }

    /// @notice Number of occupied ring slots (<= K).
    function historyLength() external view returns (uint256 n) {
        uint256 k = historyCapacity;
        for (uint256 i = 0; i < k; ++i) {
            if (_ring[i] != 0) ++n;
        }
    }

    /// @notice The retained roots, newest first; trailing empty slots are omitted.
    function historyRoots() external view returns (uint256[] memory out) {
        uint256 k = historyCapacity;
        uint256[] memory buf = new uint256[](k);
        uint256 n;
        uint256 i = _head;
        for (uint256 j = 0; j < k; ++j) {
            i = i == 0 ? k - 1 : i - 1;
            if (_ring[i] == 0) continue;
            buf[n++] = _ring[i];
        }
        out = new uint256[](n);
        for (uint256 j = 0; j < n; ++j) {
            out[j] = buf[j];
        }
    }

    /// @notice Age of `root` in root-updates: 0 = current, K-1 = oldest retained.
    ///         `found = false` if the root is not retained.
    function rootAge(uint256 root) external view returns (bool found, uint256 age) {
        uint256 k = historyCapacity;
        uint256 i = _head;
        for (uint256 j = 0; j < k; ++j) {
            i = i == 0 ? k - 1 : i - 1;
            if (_ring[i] == root && root != 0) {
                return (true, j);
            }
        }
        return (false, 0);
    }
}
