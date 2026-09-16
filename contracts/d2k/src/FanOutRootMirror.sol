// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

interface IRootMirror {
    function mirrorRoot(uint256 root) external;
}

/// @title FanOutRootMirror — HARNESS ONLY, not a protocol component
/// @notice NON-PRODUCTION | EXPERIMENT-HARNESS | EVALUATION-ONLY.
///
///         A frozen `CreditPool` pushes each new root to exactly one address,
///         fixed at construction (`IRootMirror public immutable creditPaymaster`).
///         To compare several root-acceptance policies under the SAME arrival
///         realisation — the same deposits, the same roots, the same block
///         order — the D2 kill-condition experiment constructs one frozen
///         `CreditPool` whose mirror target is this contract, which forwards
///         every `mirrorRoot` to a fixed list of Paymasters: the frozen
///         `CreditPaymaster` and one `HistoryCreditPaymaster` per tested K.
///
///         This is a paired-comparison device for the CONTENTION experiments
///         only. It inflates the Bootstrap's own gas by the fan-out, so NO gas,
///         storage or overhead number is ever taken from a fan-out deployment:
///         every §11 overhead measurement uses a dedicated single-target
///         deployment (one CreditPool -> one Paymaster), exactly as B3 deploys.
contract FanOutRootMirror {
    address public immutable creditPool;
    address[] private _targets;

    error NotCreditPool();
    error NoTargets();

    event FanOutRootMirrored(uint256 indexed newRoot, uint256 targets);

    constructor(address _creditPool, address[] memory targets_) {
        if (targets_.length == 0) revert NoTargets();
        creditPool = _creditPool;
        _targets = targets_;
    }

    function mirrorRoot(uint256 newRoot) external {
        if (msg.sender != creditPool) revert NotCreditPool();
        uint256 n = _targets.length;
        for (uint256 i = 0; i < n; ++i) {
            IRootMirror(_targets[i]).mirrorRoot(newRoot);
        }
        emit FanOutRootMirrored(newRoot, n);
    }

    function targets() external view returns (address[] memory) {
        return _targets;
    }

    function targetCount() external view returns (uint256) {
        return _targets.length;
    }
}
