// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Vm} from "forge-std/Test.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {W1Base} from "./W1Base.sol";

/// @notice Cross-baseline matching: the three baselines differ only in account
/// type and gas mechanism, never in the application action.
contract MatchedTest is W1Base {
    function setUp() public override {
        super.setUp();
        vm.deal(sponsorOperator, PAYMASTER_DEPOSIT);
        vm.prank(sponsorOperator);
        paymaster.deposit{value: PAYMASTER_DEPOSIT}();
    }

    function test_B1_and_B2_useTheSameAccountImplementationAndFactory() public {
        PackedUserOperation memory b1 = buildUserOp(recipient, false);
        PackedUserOperation memory b2 = buildUserOp(recipient, true);
        assertEq(b1.sender, b2.sender, "same counterfactual account");
        assertEq(keccak256(b1.initCode), keccak256(b2.initCode), "same factory call");

        // Run B1, snapshot the deployed runtime code, then run B2 on a fresh state.
        uint256 snap = vm.snapshotState();
        deliverAsset(b1.sender);
        vm.deal(b1.sender, requiredPrefund(false));
        submit(sign(b1, RECIPIENT_KEY));
        bytes32 b1Code = b1.sender.codehash;
        address b1Impl = address(uint160(uint256(vm.load(b1.sender, _IMPLEMENTATION_SLOT))));
        vm.revertToState(snap);

        deliverAsset(b2.sender);
        vm.prank(sponsorOperator);
        paymaster.setSponsored(b2.sender, true);
        submit(sign(b2, RECIPIENT_KEY));
        assertEq(b2.sender.codehash, b1Code, "same proxy runtime code");
        assertEq(address(uint160(uint256(vm.load(b2.sender, _IMPLEMENTATION_SLOT)))), b1Impl, "same implementation");
        assertEq(b1Impl, address(factory.accountImplementation()));
    }

    bytes32 private constant _IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    function test_B1_and_B2_executeTheSameApplicationCall() public view {
        PackedUserOperation memory b1 = buildUserOp(recipient, false);
        PackedUserOperation memory b2 = buildUserOp(recipient, true);
        assertEq(keccak256(b1.callData), keccak256(b2.callData));
        assertEq(b1.accountGasLimits, b2.accountGasLimits, "same account gas limits");
        assertEq(b1.gasFees, b2.gasFees, "same fee policy");
        assertEq(b1.preVerificationGas, b2.preVerificationGas);
    }

    function test_allBaselines_sameTokenAmountDestinationAndIntendedAction() public view {
        // B0 sends applicationCalldata() to the token directly; B1/B2 wrap the
        // byte-identical call in SimpleAccount.execute(token, 0, ...).
        bytes memory app = applicationCalldata();
        bytes memory wrapped = accountCalldata();
        (address target, uint256 value, bytes memory inner) =
            abi.decode(_stripSelector(wrapped), (address, uint256, bytes));
        assertEq(target, address(token));
        assertEq(value, 0);
        assertEq(keccak256(inner), keccak256(app));

        (address to, uint256 amount) = abi.decode(_stripSelector(app), (address, uint256));
        assertEq(to, destination);
        assertEq(amount, AMOUNT);
        assertEq(bytes4(app), bytes4(keccak256("transfer(address,uint256)")));
    }

    function _stripSelector(bytes memory data) private pure returns (bytes memory out) {
        out = new bytes(data.length - 4);
        for (uint256 i = 4; i < data.length; i++) out[i - 4] = data[i];
    }
}
