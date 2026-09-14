// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

// Real broadcast deployment attempt for B3 (baselines/b3_privgas_v1), using an
// ordinary signed transaction (vm.startBroadcast with a real private key) against
// a live JSON-RPC node — NOT vm.prank/vm.etch impersonation. Run against a
// default (no --code-size-limit override) anvil instance to test whether the
// vendored source deploys on an ordinary EIP-170-enforcing EVM.
// See docs/b3-reproduction.md.

import {Script, console} from "forge-std/Script.sol";
import {CreditPool} from "b3-baseline/CreditPool.sol";

contract OrdinaryDeploy is Script {
    function run() external {
        uint256 pk = vm.envUint("DEPLOYER_PK");
        console.log("Deployer:", vm.addr(pk));

        vm.startBroadcast(pk);
        CreditPool pool = new CreditPool(address(0xC0DEC0DE), address(0xBEEF));
        vm.stopBroadcast();

        console.log("CreditPool deployed at:", address(pool));
    }
}
