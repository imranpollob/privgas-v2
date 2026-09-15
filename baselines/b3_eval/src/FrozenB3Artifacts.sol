// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

// Compile-only imports: `forge build` emits artifacts for the UNMODIFIED frozen
// B3 contracts (baselines/b3_privgas_v1 @ 02a3f0abdb979446545aa87149080bfb44e43a3e)
// so the W1 evaluation runner can deploy them. Nothing is subclassed, wrapped or
// changed. MockAnnouncer is B3's own ERC-5564 Announcer stand-in (B3 README:
// "used throughout"); SemaphoreVerifier is the real Groth16 verifier B3's paper-table
// tests use (not MockSemaphoreVerifier, not Demo.s.sol's DemoVerifier).
import {AnnouncementRegistry} from "b3-frozen-src/AnnouncementRegistry.sol";
import {BootstrapPaymaster} from "b3-frozen-src/BootstrapPaymaster.sol";
import {CreditPool} from "b3-frozen-src/CreditPool.sol";
import {CreditPaymaster} from "b3-frozen-src/CreditPaymaster.sol";
import {MockAnnouncer} from "b3-frozen-test/mock/MockAnnouncer.sol";
import {SemaphoreVerifier} from "@semaphore-protocol/contracts/base/SemaphoreVerifier.sol";
import {PoseidonT3} from "poseidon-solidity/PoseidonT3.sol";
