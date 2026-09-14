// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {BasePaymaster} from "account-abstraction/core/BasePaymaster.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {SIG_VALIDATION_SUCCESS} from "account-abstraction/core/Helpers.sol";

/// @title ObservablePaymaster (baseline B2)
/// @notice An ordinary, non-private Paymaster used only as the B2 baseline.
///
/// AUTHORIZATION RULE (the whole rule, nothing else):
///
///     A UserOperation is sponsored  <=>  sponsored[userOp.sender] == true
///
/// `sponsored` is a public mapping written only by the owner through
/// `setSponsored`, which emits `SponsorshipSet`. Everything about the rule is
/// therefore on chain and observable: which accounts are sponsored, when they
/// were added, and by whom.
///
/// What the rule deliberately does NOT do (so that it stays an ordinary
/// baseline rather than a design):
///   * no signatures, credentials, proofs, credits or hidden state;
///   * no restriction on callData, target, gas limits, or number of ops;
///   * no postOp: validation returns an empty context, so the EntryPoint
///     refunds unused prefund to this Paymaster's deposit directly.
/// Unauthorized senders cause validation to revert, which the EntryPoint
/// surfaces as FailedOpWithRevert(opIndex, "AA33 reverted", ...).
///
/// The contract is not a privacy mechanism and makes no privacy claim.
contract ObservablePaymaster is BasePaymaster {
    /// @notice Public allowlist of sponsored smart-account senders.
    mapping(address => bool) public sponsored;

    event SponsorshipSet(address indexed account, bool sponsored);

    error SenderNotSponsored(address sender);

    constructor(IEntryPoint entryPoint_, address owner_) BasePaymaster(entryPoint_, owner_) {}

    /// @notice Owner-only: add or remove `account` from the allowlist.
    function setSponsored(address account, bool isSponsored) external onlyOwner {
        sponsored[account] = isSponsored;
        emit SponsorshipSet(account, isSponsored);
    }

    function _validatePaymasterUserOp(PackedUserOperation calldata userOp, bytes32, uint256)
        internal
        view
        override
        returns (bytes memory context, uint256 validationData)
    {
        if (!sponsored[userOp.sender]) {
            revert SenderNotSponsored(userOp.sender);
        }
        return ("", SIG_VALIDATION_SUCCESS);
    }
}
