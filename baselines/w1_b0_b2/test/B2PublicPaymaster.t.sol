// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Vm} from "forge-std/Test.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {W1Base} from "./W1Base.sol";
import {ObservablePaymaster} from "../src/ObservablePaymaster.sol";

/// @notice B2: same SimpleAccount, same EntryPoint, same action as B1; gas is
/// paid from ObservablePaymaster's EntryPoint deposit under the public
/// allowlist rule `sponsored[userOp.sender]`.
contract B2PublicPaymasterTest is W1Base {
    function setUp() public override {
        super.setUp();
        vm.deal(sponsorOperator, PAYMASTER_DEPOSIT);
        vm.prank(sponsorOperator);
        paymaster.deposit{value: PAYMASTER_DEPOSIT}();
    }

    function _sponsor(address account) internal {
        vm.prank(sponsorOperator);
        paymaster.setSponsored(account, true);
    }

    function test_B2_successfulSponsoredW1WithZeroNativeEth() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        _sponsor(account);
        assertEq(account.balance, 0, "recipient account starts with zero native ETH");

        PackedUserOperation memory op = sign(buildUserOp(recipient, true), RECIPIENT_KEY);
        uint256 depositBefore = entryPoint.balanceOf(address(paymaster));

        vm.recordLogs();
        submit(op);
        (bytes32 h, address sender, address pm, bool success, uint256 cost, uint256 used) =
            userOpEvent(vm.getRecordedLogs());

        assertEq(h, entryPoint.getUserOpHash(op));
        assertEq(sender, account);
        assertEq(pm, address(paymaster), "Paymaster is public in UserOperationEvent");
        assertTrue(success);
        assertEq(cost, used * (BASE_FEE + MAX_PRIORITY_FEE));

        assertEq(token.balanceOf(destination), AMOUNT);
        assertEq(account.balance, 0, "recipient never held native ETH");
        assertEq(entryPoint.balanceOf(account), 0, "recipient has no EntryPoint deposit");
        assertEq(depositBefore - entryPoint.balanceOf(address(paymaster)), cost, "deposit decreases by exactly actualGasCost");
    }

    function test_B2_unauthorizedSenderIsRejected() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        // not sponsored
        PackedUserOperation memory op = sign(buildUserOp(recipient, true), RECIPIENT_KEY);
        uint256 depositBefore = entryPoint.balanceOf(address(paymaster));

        vm.expectPartialRevert(IEntryPoint.FailedOpWithRevert.selector);
        submit(op);

        assertEq(entryPoint.balanceOf(address(paymaster)), depositBefore, "no deposit movement on rejection");
        assertEq(token.balanceOf(account), AMOUNT);
    }

    function test_B2_revokedSponsorshipIsRejected() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        _sponsor(account);
        vm.prank(sponsorOperator);
        paymaster.setSponsored(account, false);
        PackedUserOperation memory op = sign(buildUserOp(recipient, true), RECIPIENT_KEY);
        vm.expectPartialRevert(IEntryPoint.FailedOpWithRevert.selector);
        submit(op);
    }

    function test_B2_opWithoutPaymasterAndNoEthIsNotSponsored() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        _sponsor(account); // allowlisted, but the op does not name the Paymaster
        PackedUserOperation memory op = sign(buildUserOp(recipient, false), RECIPIENT_KEY);
        vm.expectRevert(abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA21 didn't pay prefund"));
        submit(op);
    }

    function test_B2_onlyOwnerCanSetSponsorship() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, address(this)));
        paymaster.setSponsored(address(0xBEEF), true);
    }

    function test_B2_validationIsOnlyCallableByEntryPoint() public {
        PackedUserOperation memory op = buildUserOp(recipient, true);
        vm.expectPartialRevert(bytes4(keccak256("NotFromEntryPoint(address,address,address)")));
        paymaster.validatePaymasterUserOp(op, bytes32(0), 0);
    }

    function test_B2_sponsorshipEmitsPublicEvent() public {
        address account = counterfactualAccount(recipient);
        vm.expectEmit(address(paymaster));
        emit ObservablePaymaster.SponsorshipSet(account, true);
        _sponsor(account);
    }
}
