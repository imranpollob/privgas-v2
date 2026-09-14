// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {W1Base} from "./W1Base.sol";

/// @notice B0 contract-level semantics. B0 involves no contract other than
/// the token, so this file only pins the application action. The B0
/// properties that are about ETH -- successful W1 with a sender-supplied gas
/// allowance, failure with insufficient ETH, and retained-ETH accounting --
/// are transaction-validity properties enforced by the node, which forge
/// cannot model; they are tested against anvil with real signed transactions
/// in experiments/workloads/w1/tests/test_live_baselines.py.
contract B0SenderEoaTest is W1Base {
    function test_B0_freshEoaTransfersTheAssetToTheDestination() public {
        assertEq(recipient.code.length, 0, "B0 recipient is an EOA");
        deliverAsset(recipient);

        vm.prank(recipient);
        (bool ok,) = address(token).call(applicationCalldata());
        assertTrue(ok);

        assertEq(token.balanceOf(recipient), 0);
        assertEq(token.balanceOf(destination), AMOUNT);
    }

    function test_B0_involvesNoEntryPointOrPaymasterState() public {
        deliverAsset(recipient);
        vm.prank(recipient);
        (bool ok,) = address(token).call(applicationCalldata());
        assertTrue(ok);
        assertEq(entryPoint.balanceOf(recipient), 0);
        assertEq(entryPoint.getNonce(recipient, 0), 0);
        assertFalse(paymaster.sponsored(recipient));
    }
}
