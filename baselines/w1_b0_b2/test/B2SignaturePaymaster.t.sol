// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Vm} from "forge-std/Test.sol";
import {EntryPoint} from "account-abstraction/core/EntryPoint.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {UserOperationLib} from "account-abstraction/core/UserOperationLib.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {BaseAccount} from "account-abstraction/core/BaseAccount.sol";
import {W1Base} from "./W1Base.sol";
import {SignatureVerifyingPaymaster} from "../src/SignatureVerifyingPaymaster.sol";

/// @notice B2-Signature: same SimpleAccount, EntryPoint, token, destination and
/// application call as B1; gas paid from SignatureVerifyingPaymaster's deposit
/// when the op carries the sponsor's signature over the EntryPoint userOpHash.
contract B2SignaturePaymasterTest is W1Base {
    bytes internal AA34 = abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA34 signature error");

    function setUp() public override {
        super.setUp();
        fundPaymasters();
    }

    /// @dev Account + sponsor sign the same op. The sponsor signs first; the
    /// account's signature does not cover the paymaster signature bytes.
    function sponsoredOp(address owner, uint256 ownerKey) internal view returns (PackedUserOperation memory op) {
        op = buildUserOp(owner, Sponsor.Signature);
        op = signPaymaster(op, SPONSOR_SIGNER_KEY);
        op = sign(op, ownerKey);
    }

    function test_B2Sig_validAuthorizationSponsorsW1WithZeroNativeEthAndNoAllowlistTx() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        uint256 depositBefore = entryPoint.balanceOf(address(sigPaymaster));

        vm.recordLogs();
        submit(op);
        (, address sender, address pm, bool success, uint256 cost,) = userOpEvent(vm.getRecordedLogs());

        assertEq(sender, account);
        assertEq(pm, address(sigPaymaster), "Paymaster address is public in UserOperationEvent");
        assertTrue(success);
        assertEq(token.balanceOf(destination), AMOUNT);
        assertEq(account.balance, 0);
        assertEq(entryPoint.balanceOf(account), 0);
        assertEq(depositBefore - entryPoint.balanceOf(address(sigPaymaster)), cost);
    }

    function test_B2Sig_wrongSignerIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        op = signPaymaster(op, INTRUDER_KEY);
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_missingSignatureIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature); // 65 zero bytes
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_authorizationForOneSenderDoesNotSponsorAnother() public {
        // Sponsor authorizes the op of account A; the same paymasterAndData is
        // attached to account B's (validly account-signed) op.
        PackedUserOperation memory opA = sponsoredOp(recipient, RECIPIENT_KEY);
        address ownerB = vm.addr(INTRUDER_KEY);
        deliverAsset(counterfactualAccount(ownerB));
        PackedUserOperation memory opB = buildUserOp(ownerB, Sponsor.Signature);
        opB.paymasterAndData = opA.paymasterAndData;
        opB = sign(opB, INTRUDER_KEY);
        assertTrue(opA.sender != opB.sender);
        vm.expectRevert(AA34);
        submit(opB);
    }

    function test_B2Sig_modifiedCallIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        // Change the application call after sponsor authorization; the account
        // re-signs, so only the sponsor signature is stale.
        op.callData = abi.encodeCall(
            BaseAccount.execute, (address(token), 0, abi.encodeCall(IERC20.transfer, (destination, AMOUNT - 1)))
        );
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_modifiedGasFieldIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.preVerificationGas += 1;
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    // ------------------------------------------------------------------
    // Single-field mutation tests. Each: (1) obtain a valid sponsor
    // authorization, (2) mutate ONLY the target field, (3) re-sign the account
    // so account validation itself is valid, (4) expect the Paymaster
    // authorization to fail (AA34). A control first proves the unmutated op
    // is accepted, so a failure can only come from the mutation.
    // ------------------------------------------------------------------

    function _assertAuthorizedThenMutationRejected(PackedUserOperation memory mutated) internal {
        deliverAsset(counterfactualAccount(recipient));
        uint256 snap = vm.snapshotState();
        submit(sponsoredOp(recipient, RECIPIENT_KEY)); // control: accepted
        vm.revertToState(snap);
        mutated = sign(mutated, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(mutated);
    }

    function _pmSignature(bytes memory pmd) internal pure returns (bytes memory sig) {
        sig = new bytes(65);
        for (uint256 i = 0; i < 65; i++) sig[i] = pmd[pmd.length - 10 - 65 + i];
    }

    /// paymasterAndData with explicit static gas limits and the given signature.
    function _pmdWithLimits(uint128 verificationLimit, uint128 postOpLimit, bytes memory sig)
        internal
        view
        returns (bytes memory)
    {
        return abi.encodePacked(
            address(sigPaymaster), verificationLimit, postOpLimit,
            abi.encode(uint48(0), uint48(0)), sig, uint16(sig.length), PAYMASTER_SIG_MAGIC
        );
    }

    function test_B2Sig_mutatedInitCodeFactoryDataIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        // Trailing byte after createAccount(owner, salt): the factory ignores it
        // (ABI decoding) and still returns the same sender, so only keccak(initCode)
        // changes -- the account deploys and validates normally.
        op.initCode = abi.encodePacked(op.initCode, bytes1(0x01));
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedMaxFeePerGasIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.gasFees = bytes32((MAX_PRIORITY_FEE << 128) | (MAX_FEE + 1));
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedMaxPriorityFeePerGasIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.gasFees = bytes32(((MAX_PRIORITY_FEE - 1) << 128) | MAX_FEE);
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedPaymasterVerificationGasLimitIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.paymasterAndData = _pmdWithLimits(
            uint128(PM_VERIFICATION_GAS_LIMIT + 1), uint128(PM_POST_OP_GAS_LIMIT), _pmSignature(op.paymasterAndData)
        );
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedPaymasterPostOpGasLimitIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.paymasterAndData = _pmdWithLimits(
            uint128(PM_VERIFICATION_GAS_LIMIT), uint128(PM_POST_OP_GAS_LIMIT + 1), _pmSignature(op.paymasterAndData)
        );
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedVerificationGasLimitIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.accountGasLimits = bytes32(((VERIFICATION_GAS_LIMIT + 1) << 128) | CALL_GAS_LIMIT);
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_mutatedCallGasLimitIsRejected() public {
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        op.accountGasLimits = bytes32((VERIFICATION_GAS_LIMIT << 128) | (CALL_GAS_LIMIT + 1));
        _assertAuthorizedThenMutationRejected(op);
    }

    function test_B2Sig_unmutatedPaymasterDataRebuildIsStillAccepted() public {
        // Guards the helpers above: rebuilding paymasterAndData with the SAME
        // limits and signature must not change the hash or the authorization.
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        bytes32 before = entryPoint.getUserOpHash(op);
        op.paymasterAndData = _pmdWithLimits(
            uint128(PM_VERIFICATION_GAS_LIMIT), uint128(PM_POST_OP_GAS_LIMIT), _pmSignature(op.paymasterAndData)
        );
        assertEq(entryPoint.getUserOpHash(op), before);
        submit(op);
    }

    function test_B2Sig_replayOfAnIncludedOpFailsOnNonce() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY);
        submit(op);
        vm.expectRevert(abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA25 invalid account nonce"));
        submit(op);
    }

    function test_B2Sig_authorizationDoesNotCarryOverToTheNextNonce() public {
        address account = counterfactualAccount(recipient);
        vm.prank(assetSender);
        require(token.transfer(account, 2 * AMOUNT));
        PackedUserOperation memory first = sponsoredOp(recipient, RECIPIENT_KEY);
        submit(first);

        PackedUserOperation memory second = buildUserOp(recipient, Sponsor.Signature); // nonce 1, no initCode needed
        second.initCode = "";
        second.paymasterAndData = first.paymasterAndData; // reuse the sponsor signature
        second = sign(second, RECIPIENT_KEY);
        assertEq(second.nonce, first.nonce + 1);
        vm.expectRevert(AA34);
        submit(second);
    }

    function test_B2Sig_signatureForAnotherEntryPointDomainIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        EntryPoint other = new EntryPoint();
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        bytes32 otherHash = other.getUserOpHash(op);
        assertTrue(otherHash != entryPoint.getUserOpHash(op), "EntryPoint address is in the domain");
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SPONSOR_SIGNER_KEY, otherHash);
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, 0, 0, abi.encodePacked(r, s, v));
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_signatureForAnotherChainIdIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        // Literal chain ids: under via-IR a local copy of block.chainid can be
        // re-read after vm.chainId, which would silently skip the restore.
        assertEq(block.chainid, 31337);
        vm.chainId(31338);
        bytes32 foreignHash = entryPoint.getUserOpHash(op);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SPONSOR_SIGNER_KEY, foreignHash);
        vm.chainId(31337);
        assertTrue(foreignHash != entryPoint.getUserOpHash(op), "chain id is in the domain");
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, 0, 0, abi.encodePacked(r, s, v));
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_signatureForAnotherPaymasterIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        SignatureVerifyingPaymaster twin = new SignatureVerifyingPaymaster(
            IEntryPoint(address(entryPoint)), sponsorOperator, vm.addr(SPONSOR_SIGNER_KEY)
        );
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        op.paymasterAndData = signaturePaymasterAndData(twin, 0, 0, new bytes(65));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SPONSOR_SIGNER_KEY, entryPoint.getUserOpHash(op));
        // Same signer, same op, but the signature was made over twin's address.
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, 0, 0, abi.encodePacked(r, s, v));
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_expiredAuthorizationIsRejected() public {
        deliverAsset(counterfactualAccount(recipient));
        vm.warp(1_000);
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        op = signPaymaster(op, SPONSOR_SIGNER_KEY, 999, 0);
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA32 paymaster expired or not due"));
        submit(op);
    }

    function test_B2Sig_validityWindowIsSigned() public {
        deliverAsset(counterfactualAccount(recipient));
        PackedUserOperation memory op = sponsoredOp(recipient, RECIPIENT_KEY); // signed with 0/0
        bytes memory sig = new bytes(65);
        bytes memory pmd = op.paymasterAndData;
        for (uint256 i = 0; i < 65; i++) sig[i] = pmd[pmd.length - 10 - 65 + i];
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, type(uint48).max, 0, sig);
        op = sign(op, RECIPIENT_KEY);
        vm.expectRevert(AA34);
        submit(op);
    }

    function test_B2Sig_userOpHashExcludesSignatureBytesButNotItsPresence() public view {
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        bytes32 placeholderHash = entryPoint.getUserOpHash(op);
        PackedUserOperation memory signed = signPaymaster(buildUserOp(recipient, Sponsor.Signature), SPONSOR_SIGNER_KEY);
        assertEq(entryPoint.getUserOpHash(signed), placeholderHash, "signature bytes excluded");

        PackedUserOperation memory noSuffix = buildUserOp(recipient, Sponsor.Signature);
        noSuffix.paymasterAndData = abi.encodePacked(
            address(sigPaymaster), uint128(PM_VERIFICATION_GAS_LIMIT), uint128(PM_POST_OP_GAS_LIMIT), abi.encode(uint48(0), uint48(0))
        );
        assertTrue(entryPoint.getUserOpHash(noSuffix) != placeholderHash, "suffix presence is hashed");
    }

    function test_B2Sig_signatureSuffixMatchesUpstreamEncoding() public view {
        bytes memory sig = new bytes(65);
        sig[0] = 0x01;
        bytes memory ours = signaturePaymasterAndData(sigPaymaster, 0, 0, sig);
        bytes memory upstream = this.upstreamEncode(sig);
        bytes memory tail = new bytes(upstream.length);
        for (uint256 i = 0; i < upstream.length; i++) tail[i] = ours[ours.length - upstream.length + i];
        assertEq(keccak256(tail), keccak256(upstream));
    }

    function upstreamEncode(bytes calldata sig) external pure returns (bytes memory) {
        return UserOperationLib.encodePaymasterSignature(sig);
    }

    function test_B2Sig_noAllowlistStateIsInvolved() public view {
        // No setSponsored-style storage: the only authorization state is the
        // immutable public signer.
        assertEq(sigPaymaster.verifyingSigner(), vm.addr(SPONSOR_SIGNER_KEY));
    }

    function test_B2Sig_validationIsOnlyCallableByEntryPoint() public {
        PackedUserOperation memory op = buildUserOp(recipient, Sponsor.Signature);
        vm.expectPartialRevert(bytes4(keccak256("NotFromEntryPoint(address,address,address)")));
        sigPaymaster.validatePaymasterUserOp(op, bytes32(0), 0);
    }
}
