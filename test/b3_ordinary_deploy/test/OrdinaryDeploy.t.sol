// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

// This project deliberately lives OUTSIDE baselines/b3_privgas_v1 (the pinned
// submodule) and imports its source by remapping. It exists only to check
// whether the vendored B3 source deploys under an ORDINARY key on an
// EIP-170-enforcing EVM, without using vm.prank/vm.etch to fake deployability.
// See docs/b3-reproduction.md and docs/decision-log.md for context. Nothing
// here modifies the submodule.

import {Test} from "forge-std/Test.sol";
import {PoseidonT3} from "poseidon-solidity/PoseidonT3.sol";

contract OrdinaryDeployTest is Test {
    uint256 constant EIP170_CONTRACT_SIZE_LIMIT = 24576; // bytes

    /// @notice PASSES by confirming a known, frozen property of the pinned B3
    /// commit: CreditPool (src/CreditPool.sol) links against the zk-kit
    /// LeanIMT, which calls PoseidonT3.hash(). PoseidonT3 declares that
    /// function `public`, so Solidity compiles it as a separately deployed
    /// library contract (delegatecall), not inlined — and its runtime
    /// bytecode is over the EIP-170 24576-byte contract-size limit.
    ///
    /// `forge test`'s in-process EVM does not enforce EIP-170, so `new
    /// CreditPool(...)` succeeds silently there — it is NOT a reliable way to
    /// check deployability. This test instead asserts the underlying fact
    /// directly, as a standing regression check against the pinned baseline
    /// commit. The consequence — an ordinary-key deployment actually failing
    /// on a live chain — is exercised separately by
    /// scripts/run_b3_ordinary_deploy.sh / script/OrdinaryDeploy.s.sol, which
    /// attempt a real broadcast and record the real result rather than
    /// asserting it here. That script confirmed, against a default (no
    /// --code-size-limit override) anvil:
    ///   "Error: `PoseidonT3` is above the contract size limit (29315 > 24576)."
    ///
    /// This is a property of the vendored bytecode, not a prank/impersonation
    /// artifact, and not something this repo repairs here — see
    /// docs/decision-log.md for the "never silently repair B3" rule.
    function test_poseidonT3_confirmedExceedsEip170SizeLimit() public pure {
        uint256 size = type(PoseidonT3).runtimeCode.length;
        assertGt(
            size,
            EIP170_CONTRACT_SIZE_LIMIT,
            "expected the pinned B3 commit's PoseidonT3 to still exceed the EIP-170 24576-byte limit; if this no longer holds, the baseline commit or dependency pin has changed and docs/b3-reproduction.md needs re-verifying, not this assertion silently flipped"
        );
    }
}
