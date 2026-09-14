// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Vm} from "forge-std/Test.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {W1Base} from "./W1Base.sol";

/// @notice B1: sender-funded upstream SimpleAccount (v0.9.0), no Paymaster.
/// Gas is paid by the standard non-Paymaster mechanism: during validation the
/// account forwards `missingAccountFunds` from its own ETH balance to the
/// EntryPoint, and the EntryPoint credits any unused prefund back to the
/// account's EntryPoint deposit (not to its ETH balance).
contract B1SenderAaTest is W1Base {
    function test_B1_successfulW1() public {
        address account = counterfactualAccount(recipient);
        uint256 funding = requiredPrefund(false);

        deliverAsset(account);
        vm.deal(account, funding); // stands in for the sender's ETH transfer

        PackedUserOperation memory op = sign(buildUserOp(recipient, false), RECIPIENT_KEY);
        uint256 beneficiaryBefore = beneficiary.balance;

        vm.recordLogs();
        submit(op);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        (bytes32 h, address sender, address pm, bool success, uint256 cost, uint256 used) = userOpEvent(logs);

        assertEq(h, entryPoint.getUserOpHash(op));
        assertEq(sender, account);
        assertEq(pm, address(0), "B1 has no Paymaster");
        assertTrue(success);
        assertEq(cost, used * (BASE_FEE + MAX_PRIORITY_FEE), "charged at min(maxFee, basefee+priority)");

        assertGt(account.code.length, 0, "account deployed by initCode");
        assertEq(token.balanceOf(account), 0);
        assertEq(token.balanceOf(destination), AMOUNT);

        // Reconciliation: funding = retained ETH + retained EntryPoint deposit + charged gas.
        assertEq(account.balance, 0, "account forwarded exactly the missing prefund");
        assertEq(entryPoint.balanceOf(account), funding - cost, "unused prefund is credited to the deposit");
        assertEq(account.balance + entryPoint.balanceOf(account) + cost, funding);
        assertEq(beneficiary.balance - beneficiaryBefore, cost, "beneficiary receives actualGasCost");
    }

    function test_B1_insufficientNativeFundingFails() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        vm.deal(account, requiredPrefund(false) - 1);

        PackedUserOperation memory op = sign(buildUserOp(recipient, false), RECIPIENT_KEY);
        vm.expectRevert(abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA21 didn't pay prefund"));
        submit(op);

        assertEq(account.code.length, 0, "whole bundle reverted: account not deployed");
        assertEq(token.balanceOf(account), AMOUNT, "asset not moved");
    }

    function test_B1_wrongSignerIsRejected() public {
        address account = counterfactualAccount(recipient);
        deliverAsset(account);
        vm.deal(account, requiredPrefund(false));
        PackedUserOperation memory op = sign(buildUserOp(recipient, false), INTRUDER_KEY);
        vm.expectRevert(abi.encodeWithSelector(IEntryPoint.FailedOp.selector, 0, "AA24 signature error"));
        submit(op);
    }

    function test_B1_userOpCarriesNoPaymasterData() public view {
        PackedUserOperation memory op = buildUserOp(recipient, false);
        assertEq(op.paymasterAndData.length, 0);
    }
}
