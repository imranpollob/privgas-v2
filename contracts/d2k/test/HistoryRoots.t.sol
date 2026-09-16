// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {HistoryCreditPaymaster} from "../src/HistoryCreditPaymaster.sol";
import {CreditPaymaster} from "b3-frozen-src/CreditPaymaster.sol";

/// @notice Ring-buffer retention mechanics of the D2-History-K experimental variant.
///         Proof-path behaviour (real Groth16, real verifier, real EntryPoint) is tested
///         live in experiments/liveness/d2k/tests/test_live.py; this file pins the parts
///         that need no proof: entry, exit, the eviction boundary, duplicates, the
///         K = 1 reduction and the storage bound.
contract HistoryRootsTest is Test {
    address constant EP = address(0xEE);
    address constant VERIFIER = address(0xFE);

    function _pm(uint256 k) internal returns (HistoryCreditPaymaster) {
        // creditPool == address(this): this test contract plays CreditPool.
        return new HistoryCreditPaymaster(EP, address(this), VERIFIER, k);
    }

    function test_zeroCapacityRejected() public {
        vm.expectRevert(HistoryCreditPaymaster.ZeroHistoryCapacity.selector);
        new HistoryCreditPaymaster(EP, address(this), VERIFIER, 0);
    }

    function test_onlyCreditPoolMayMirror() public {
        HistoryCreditPaymaster pm = _pm(4);
        vm.prank(address(0xBEEF));
        vm.expectRevert(HistoryCreditPaymaster.NotCreditPool.selector);
        pm.mirrorRoot(1);
    }

    function test_emptyHistoryAcceptsNothing() public {
        HistoryCreditPaymaster pm = _pm(8);
        assertEq(pm.merkleRoot(), 0);
        assertEq(pm.historyLength(), 0);
        assertFalse(pm.isKnownRoot(0));
        assertFalse(pm.isKnownRoot(1));
    }

    /// K = 1 must be latest-root-only: exactly the frozen acceptance rule.
    function test_k1IsLatestRootOnly() public {
        HistoryCreditPaymaster pm = _pm(1);
        for (uint256 r = 1; r <= 5; ++r) {
            pm.mirrorRoot(r);
            assertEq(pm.merkleRoot(), r);
            assertTrue(pm.isKnownRoot(r));
            assertEq(pm.historyLength(), 1);
            if (r > 1) assertFalse(pm.isKnownRoot(r - 1));
        }
    }

    /// A root is accepted for exactly K-1 subsequent updates and rejected from the K-th.
    function test_evictionBoundaryIsExact() public {
        uint256[6] memory ks = [uint256(1), 2, 4, 8, 16, 32];
        for (uint256 x = 0; x < ks.length; ++x) {
            uint256 k = ks[x];
            HistoryCreditPaymaster pm = _pm(k);
            pm.mirrorRoot(1000);
            // K-1 further updates: still accepted, age grows by one each time.
            for (uint256 j = 1; j <= k - 1; ++j) {
                pm.mirrorRoot(1000 + j);
                assertTrue(pm.isKnownRoot(1000), "evicted too early");
                (bool found, uint256 age) = pm.rootAge(1000);
                assertTrue(found);
                assertEq(age, j, "wrong age");
            }
            assertEq(pm.historyLength(), k);
            // the K-th update after it evicts it, and nothing else.
            pm.mirrorRoot(2000);
            assertFalse(pm.isKnownRoot(1000), "not evicted at the boundary");
            assertTrue(pm.isKnownRoot(2000));
            if (k > 1) assertTrue(pm.isKnownRoot(1001));
            assertEq(pm.historyLength(), k);
        }
    }

    function test_currentRootIsAlwaysAccepted() public {
        HistoryCreditPaymaster pm = _pm(4);
        for (uint256 r = 1; r <= 20; ++r) {
            pm.mirrorRoot(r);
            assertEq(pm.merkleRoot(), r);
            assertTrue(pm.isKnownRoot(r));
            (bool found, uint256 age) = pm.rootAge(r);
            assertTrue(found);
            assertEq(age, 0);
        }
    }

    function test_unknownAndZeroRootsRejected() public {
        HistoryCreditPaymaster pm = _pm(8);
        for (uint256 r = 1; r <= 8; ++r) {
            pm.mirrorRoot(r);
        }
        assertFalse(pm.isKnownRoot(0));
        assertFalse(pm.isKnownRoot(9)); // never mirrored ("future"/fabricated)
        assertFalse(pm.isKnownRoot(type(uint256).max));
    }

    /// A root mirrored twice survives until BOTH of its slots are evicted.
    function test_duplicateRootsAreRefcounted() public {
        HistoryCreditPaymaster pm = _pm(4);
        pm.mirrorRoot(7);
        pm.mirrorRoot(8);
        pm.mirrorRoot(7); // same root again
        pm.mirrorRoot(9);
        assertEq(pm.rootRefCount(7), 2);
        pm.mirrorRoot(10); // evicts the FIRST 7
        assertEq(pm.rootRefCount(7), 1);
        assertTrue(pm.isKnownRoot(7));
        pm.mirrorRoot(11);
        pm.mirrorRoot(12); // evicts the second 7
        assertEq(pm.rootRefCount(7), 0);
        assertFalse(pm.isKnownRoot(7));
    }

    function test_historyRootsAreNewestFirst() public {
        HistoryCreditPaymaster pm = _pm(4);
        pm.mirrorRoot(1);
        pm.mirrorRoot(2);
        uint256[] memory partialHist = pm.historyRoots();
        assertEq(partialHist.length, 2);
        assertEq(partialHist[0], 2);
        assertEq(partialHist[1], 1);
        pm.mirrorRoot(3);
        pm.mirrorRoot(4);
        pm.mirrorRoot(5);
        uint256[] memory full = pm.historyRoots();
        assertEq(full.length, 4);
        assertEq(full[0], 5);
        assertEq(full[3], 2);
    }

    /// Storage stays bounded: after many updates only 2K + 1 slots are non-zero.
    function test_storageStaysBounded() public {
        uint256 k = 8;
        HistoryCreditPaymaster pm = _pm(k);
        vm.record();
        for (uint256 r = 1; r <= 200; ++r) {
            pm.mirrorRoot(r);
        }
        (, bytes32[] memory writes) = vm.accesses(address(pm));
        uint256 nonZero;
        bytes32[] memory seen = new bytes32[](writes.length);
        uint256 n;
        for (uint256 i = 0; i < writes.length; ++i) {
            bool dup;
            for (uint256 j = 0; j < n; ++j) {
                if (seen[j] == writes[i]) {
                    dup = true;
                    break;
                }
            }
            if (dup) continue;
            seen[n++] = writes[i];
            if (vm.load(address(pm), writes[i]) != bytes32(0)) ++nonZero;
        }
        // K ring slots + K refcounts + the head cursor (the cursor is itself zero
        // whenever the ring has just wrapped, hence the 2K lower bound).
        assertLe(nonZero, 2 * k + 1, "history storage is not bounded by 2K + 1");
        assertGe(nonZero, 2 * k, "history lost a retained root");
        // `n` (slots ever touched) grows with the number of updates because each
        // evicted refcount slot is cleared again; the PERSISTENT footprint above is
        // what "bounded" means here.
        assertGt(n, 2 * k + 1);
    }

    /// The variant keeps every frozen constant.
    function test_frozenConstantsUnchanged() public {
        HistoryCreditPaymaster h = _pm(8);
        CreditPaymaster f = new CreditPaymaster(EP, address(this), VERIFIER);
        assertEq(h.MAX_CREDIT_GAS(), f.MAX_CREDIT_GAS());
        assertEq(h.MAX_ACCEPTED_MAX_FEE_PER_GAS(), f.MAX_ACCEPTED_MAX_FEE_PER_GAS());
        assertEq(h.MAX_SPONSORSHIP_COST(), f.MAX_SPONSORSHIP_COST());
        assertEq(h.CREDIT_NULLIFIER_SCOPE(), f.CREDIT_NULLIFIER_SCOPE());
    }

    /// Root-update cost must not depend on K (O(1) update).
    function test_updateGasIsIndependentOfK() public {
        uint256[4] memory ks = [uint256(1), 4, 8, 32];
        uint256[4] memory gas;
        for (uint256 x = 0; x < ks.length; ++x) {
            HistoryCreditPaymaster pm = _pm(ks[x]);
            // fill the ring so every measured update also evicts
            for (uint256 r = 1; r <= ks[x] + 1; ++r) {
                pm.mirrorRoot(r);
            }
            uint256 before = gasleft();
            pm.mirrorRoot(9_999);
            gas[x] = before - gasleft();
        }
        for (uint256 x = 1; x < ks.length; ++x) {
            uint256 lo = gas[x] < gas[0] ? gas[x] : gas[0];
            uint256 hi = gas[x] < gas[0] ? gas[0] : gas[x];
            assertLt(hi - lo, 200, "steady-state update gas depends on K");
        }
    }
}
