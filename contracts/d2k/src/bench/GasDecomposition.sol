// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {InternalLeanIMT, LeanIMTData} from "@zk-kit/lean-imt.sol/InternalLeanIMT.sol";
import {PoseidonT3} from "poseidon-solidity/PoseidonT3.sol";
import {EligibilityLogic} from "b3-frozen-src/lib/EligibilityLogic.sol";

interface IRootMirrorTarget {
    function mirrorRoot(uint256 root) external;
}

/// @notice D2-B gas decomposition benchmarks (docs/d2-killcondition-results.md §16-19).
///
///         NON-PRODUCTION | BENCHMARK-ONLY. These contracts exist to attribute the
///         measured growth of the frozen `CreditPool.deposit` to its parts. They are
///         compiled with the frozen specimen's own compiler settings
///         (solc 0.8.28, via-IR, optimizer 200) and use the SAME incremental-tree
///         library (`@zk-kit/lean-imt.sol/InternalLeanIMT`) and the SAME Poseidon
///         implementation (`poseidon-solidity/PoseidonT3`, linked to the same deployed
///         library address) as the frozen `CreditPool`. No alternative Merkle primitive
///         is introduced.
///
///         G1 `LeanIMTBench`        — the incremental-tree insertion, alone.
///         G2 `RootMirrorPusher`    — publishing a changing root into a Paymaster-like
///                                    contract, with no Merkle work.
///         G3 `PoolSurroundBench`   — `CreditPool.deposit`'s surrounding logic
///                                    (eligibility, one-shot flag, mirror call, event)
///                                    with the tree insertion replaced.
///         G4 `NoopBench`           — the bare external-call floor.
///         G5 `PoseidonCallBench`   — one `PoseidonT3.hash` delegatecall, alone.

// ── G1 ───────────────────────────────────────────────────────────────────────

/// @dev `CreditPool` declares `LeanIMTData private _tree` as its FIRST storage member
///      (its two other fields are immutables, which occupy no storage), so `_tree` sits
///      at slots 0..3 here exactly as it does there and the SSTORE cost pattern of an
///      insertion is identical. Nothing else is done: no eligibility, no event, no
///      mirror call, no return value.
contract LeanIMTBench {
    using InternalLeanIMT for LeanIMTData;

    LeanIMTData private _tree;

    function insert(uint256 leaf) external {
        _tree._insert(leaf);
    }

    function currentRoot() external view returns (uint256) {
        return _tree._root();
    }

    function treeSize() external view returns (uint256) {
        return _tree.size;
    }

    function treeDepth() external view returns (uint256) {
        return _tree.depth;
    }
}

// ── G2 ───────────────────────────────────────────────────────────────────────

/// @dev Stands where `CreditPool` stands in the mirror path: an external caller that
///      does nothing but push a changing root into the Paymaster. Point `mirror` at the
///      frozen `CreditPaymaster` (constructed with `creditPool = address(this)`) to
///      measure B3's own mirror cost, or at a `HistoryCreditPaymaster` to measure the
///      variant's root-update cost. The pushed value is supplied by the caller, so no
///      hashing happens anywhere in the measured frame.
contract RootMirrorPusher {
    address public immutable mirror;

    constructor(address _mirror) {
        mirror = _mirror;
    }

    function push(uint256 root) external {
        IRootMirrorTarget(mirror).mirrorRoot(root);
    }
}

/// @dev A minimal single-slot mirror, for the mirror cost without the frozen
///      contract's own event/immutable layout. Accepts one fixed pusher.
contract MinimalRootMirror {
    address public immutable creditPool;
    uint256 private _merkleRoot;

    error NotCreditPool();

    event RootMirrored(uint256 indexed newRoot);

    constructor(address _creditPool) {
        creditPool = _creditPool;
    }

    function mirrorRoot(uint256 newRoot) external {
        if (msg.sender != creditPool) revert NotCreditPool();
        _merkleRoot = newRoot;
        emit RootMirrored(newRoot);
    }

    function merkleRoot() external view returns (uint256) {
        return _merkleRoot;
    }
}

// ── G3 ───────────────────────────────────────────────────────────────────────

/// @dev `CreditPool.deposit` with the LeanIMT insertion replaced, everything else kept:
///      the same `EligibilityLogic.checkDepositEligible` call on the same two mappings,
///      the same `_used[msg.sender] = true`, the same external `mirrorRoot` push and the
///      same `Deposited(commitment, newRoot)` event, from the same declaration order so
///      the mappings land on the same storage slots as in `CreditPool`.
///
///      Two modes isolate the tree's non-hashing bookkeeping:
///      * `deposit`           (G3a) — surrounding logic only; the "root" is the commitment.
///      * `depositWithLeafBookkeeping` (G3b) — additionally performs the two writes
///        `_insert` makes outside the hashing loop (`size` and `leaves[leaf]`), so
///        G3b - G3a is the cost of the tree's size/leaf bookkeeping alone.
contract PoolSurroundBench {
    IRootMirrorTarget public immutable creditPaymaster;
    address public immutable registry;

    // Mirrors CreditPool's storage layout: LeanIMTData occupies slots 0..3.
    uint256 private _size; // LeanIMTData.size
    uint256 private _depth; // LeanIMTData.depth
    mapping(uint256 => uint256) private _sideNodes; // LeanIMTData.sideNodes (unused)
    mapping(uint256 => uint256) private _leaves; // LeanIMTData.leaves
    mapping(address => bool) private _eligible;
    mapping(address => bool) private _used;

    error NotRegistry();
    error NotEligible(address sender);
    error AlreadyDeposited(address sender);

    event Deposited(uint256 indexed commitment, uint256 newRoot);
    event EligibilityMirrored(address indexed stealthAddress);

    constructor(address _creditPaymaster, address _registry) {
        creditPaymaster = IRootMirrorTarget(_creditPaymaster);
        registry = _registry;
    }

    function mirrorEligible(address stealthAddress) external {
        if (msg.sender != registry) revert NotRegistry();
        _eligible[stealthAddress] = true;
        emit EligibilityMirrored(stealthAddress);
    }

    function deposit(uint256 commitment) external {
        _guard();
        uint256 newRoot = commitment;
        creditPaymaster.mirrorRoot(newRoot);
        emit Deposited(commitment, newRoot);
    }

    function depositWithLeafBookkeeping(uint256 commitment) external {
        _guard();
        uint256 index = _size;
        unchecked {
            _size = index + 1;
        }
        _leaves[commitment] = index + 1;
        uint256 newRoot = commitment;
        creditPaymaster.mirrorRoot(newRoot);
        emit Deposited(commitment, newRoot);
    }

    function _guard() private {
        if (!EligibilityLogic.checkDepositEligible(_eligible[msg.sender], _used[msg.sender])) {
            if (!_eligible[msg.sender]) revert NotEligible(msg.sender);
            revert AlreadyDeposited(msg.sender);
        }
        _used[msg.sender] = true;
    }

    function treeSize() external view returns (uint256) {
        return _size;
    }

    function isEligible(address addr) external view returns (bool) {
        return _eligible[addr];
    }

    function hasDeposited(address addr) external view returns (bool) {
        return _used[addr];
    }
}

// ── measurement device ───────────────────────────────────────────────────────

/// @dev Makes every benchmark a SUB-FRAME of a CALL, exactly like the frozen
///      `CreditPool.deposit` is a sub-frame of `SimpleAccount.execute` inside the
///      EntryPoint. The tracer then reports each benchmark's own frame gas on the same
///      footing, with no intrinsic-gas or calldata accounting to reconcile. The cold
///      account-access charge for reaching the target is paid by THIS frame, not by the
///      measured one, in both cases.
contract BenchRunner {
    error CallFailed(bytes reason);

    function run(address target, bytes calldata data) external {
        (bool ok, bytes memory ret) = target.call(data);
        if (!ok) revert CallFailed(ret);
    }
}

// ── G4 / G5 ──────────────────────────────────────────────────────────────────

/// @dev The floor: an external call that takes one word and does nothing with it.
contract NoopBench {
    function noop(uint256) external {}
}

/// @dev One `PoseidonT3.hash` delegatecall and nothing else, plus a no-argument-work
///      variant so the call's own overhead can be netted out.
contract PoseidonCallBench {
    uint256 public sink;

    function hashOnce(uint256 a, uint256 b) external {
        sink = PoseidonT3.hash([a, b]);
    }

    function storeOnly(uint256 a, uint256) external {
        sink = a;
    }
}
