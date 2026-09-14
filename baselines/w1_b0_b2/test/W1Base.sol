// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test, Vm} from "forge-std/Test.sol";
import {EntryPoint} from "account-abstraction/core/EntryPoint.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {SimpleAccountFactory} from "account-abstraction/accounts/SimpleAccountFactory.sol";
import {BaseAccount} from "account-abstraction/core/BaseAccount.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {W1Token} from "../src/W1Token.sol";
import {ObservablePaymaster} from "../src/ObservablePaymaster.sol";
import {SignatureVerifyingPaymaster} from "../src/SignatureVerifyingPaymaster.sol";

/// @notice Shared W1 environment for the B0/B1/B2 Foundry tests.
///
/// Scope of these tests: contract-level semantics (who can authorize what,
/// which calldata executes, how the EntryPoint moves deposits). They are NOT
/// the cost measurement. Forge executes calls under cheatcode-controlled
/// senders (vm.prank) with no transaction-level ETH accounting, so EOA gas
/// payment, B0's "insufficient ETH" failure and every reported cost number
/// come from the live signed-transaction runner against anvil
/// (experiments/workloads/w1/), never from here.
abstract contract W1Base is Test {
    // --- config (w1-config.json is the single source of truth) -------------
    uint256 internal AMOUNT;
    uint256 internal SUPPLY;
    uint256 internal BASE_FEE;
    uint256 internal MAX_PRIORITY_FEE;
    uint256 internal MAX_FEE;
    uint256 internal VERIFICATION_GAS_LIMIT;
    uint256 internal CALL_GAS_LIMIT;
    uint256 internal PRE_VERIFICATION_GAS;
    uint256 internal PM_VERIFICATION_GAS_LIMIT;
    uint256 internal PM_POST_OP_GAS_LIMIT;
    uint256 internal SALT;
    uint256 internal PAYMASTER_DEPOSIT;

    /// PAYMASTER_SIG_MAGIC from UserOperationLib (internal constant, restated
    /// for off-chain-style encoding in tests; checked against upstream by
    /// test_signatureSuffixMatchesUpstreamEncoding).
    bytes8 internal constant PAYMASTER_SIG_MAGIC = 0x22e325a297439656;

    enum Sponsor { None, Allowlist, Signature }

    // --- actors (test keys; the live runner derives its own from the seed) --
    uint256 internal constant RECIPIENT_KEY = 0xA11CE;
    uint256 internal constant INTRUDER_KEY = 0xBAD;
    uint256 internal constant SPONSOR_SIGNER_KEY = 0x5160;
    address internal recipient; // B0: the fresh EOA; B1/B2: the account owner
    address internal assetSender = makeAddr("assetSender");
    address internal destination = makeAddr("destination");
    address internal sponsorOperator = makeAddr("sponsorOperator");
    address payable internal bundler = payable(makeAddr("bundler"));
    address payable internal beneficiary = payable(makeAddr("beneficiary"));

    // --- deployed environment (identical for all three baselines) -----------
    EntryPoint internal entryPoint;
    SimpleAccountFactory internal factory;
    W1Token internal token;
    ObservablePaymaster internal paymaster;
    SignatureVerifyingPaymaster internal sigPaymaster;

    function setUp() public virtual {
        _loadConfig();
        recipient = vm.addr(RECIPIENT_KEY);

        entryPoint = new EntryPoint();
        factory = new SimpleAccountFactory(IEntryPoint(address(entryPoint)));
        token = new W1Token(assetSender, SUPPLY);
        paymaster = new ObservablePaymaster(IEntryPoint(address(entryPoint)), sponsorOperator);
        sigPaymaster = new SignatureVerifyingPaymaster(
            IEntryPoint(address(entryPoint)), sponsorOperator, vm.addr(SPONSOR_SIGNER_KEY)
        );

        vm.fee(BASE_FEE);
        vm.txGasPrice(BASE_FEE + MAX_PRIORITY_FEE);
    }

    function _loadConfig() internal {
        string memory json = vm.readFile(string.concat(vm.projectRoot(), "/w1-config.json"));
        AMOUNT = _u(json, ".token.transfer_amount");
        SUPPLY = _u(json, ".token.supply");
        BASE_FEE = _u(json, ".fees.base_fee_per_gas");
        MAX_PRIORITY_FEE = _u(json, ".fees.max_priority_fee_per_gas");
        MAX_FEE = _u(json, ".fees.max_fee_per_gas");
        VERIFICATION_GAS_LIMIT = _u(json, ".userop.verification_gas_limit");
        CALL_GAS_LIMIT = _u(json, ".userop.call_gas_limit");
        PRE_VERIFICATION_GAS = _u(json, ".userop.provisional_pre_verification_gas");
        PM_VERIFICATION_GAS_LIMIT = _u(json, ".userop.paymaster_verification_gas_limit");
        PM_POST_OP_GAS_LIMIT = _u(json, ".userop.paymaster_post_op_gas_limit");
        SALT = _u(json, ".userop.account_salt");
        PAYMASTER_DEPOSIT = _u(json, ".funding.paymaster_deposit");
    }

    function _u(string memory json, string memory key) private pure returns (uint256) {
        return vm.parseUint(vm.parseJsonString(json, key));
    }

    // --- the one application action shared by all baselines ----------------

    /// @notice The W1 application call: ERC20.transfer(destination, AMOUNT).
    function applicationCalldata() internal view returns (bytes memory) {
        return abi.encodeCall(IERC20.transfer, (destination, AMOUNT));
    }

    /// @notice B1/B2 account callData: SimpleAccount.execute(token, 0, applicationCalldata)
    ///         (execute is inherited unchanged from v0.9.0 BaseAccount).
    function accountCalldata() internal view returns (bytes memory) {
        return abi.encodeCall(BaseAccount.execute, (address(token), 0, applicationCalldata()));
    }

    // --- UserOperation helpers ----------------------------------------------

    function counterfactualAccount(address owner) internal view returns (address) {
        return factory.getAddress(owner, SALT);
    }

    function initCodeFor(address owner) internal view returns (bytes memory) {
        return abi.encodePacked(address(factory), abi.encodeCall(SimpleAccountFactory.createAccount, (owner, SALT)));
    }

    function buildUserOp(address owner, bool withPaymaster) internal view returns (PackedUserOperation memory op) {
        return buildUserOp(owner, withPaymaster ? Sponsor.Allowlist : Sponsor.None);
    }

    /// @notice B2-Signature paymasterAndData with a 65-byte placeholder
    /// signature. Because paymasterDataKeccak excludes the signature bytes (but
    /// not the suffix), the userOpHash of this op equals the hash of the final
    /// op, so both parties can sign it before the real signature is inserted.
    function signaturePaymasterAndData(
        SignatureVerifyingPaymaster pm,
        uint48 validUntil,
        uint48 validAfter,
        bytes memory pmSignature
    ) internal view returns (bytes memory) {
        return abi.encodePacked(
            address(pm),
            uint128(PM_VERIFICATION_GAS_LIMIT),
            uint128(PM_POST_OP_GAS_LIMIT),
            abi.encode(validUntil, validAfter),
            pmSignature,
            uint16(pmSignature.length),
            PAYMASTER_SIG_MAGIC
        );
    }

    function buildUserOp(address owner, Sponsor mode) internal view returns (PackedUserOperation memory op) {
        op.sender = counterfactualAccount(owner);
        op.nonce = entryPoint.getNonce(op.sender, 0);
        op.initCode = initCodeFor(owner);
        op.callData = accountCalldata();
        op.accountGasLimits = bytes32((VERIFICATION_GAS_LIMIT << 128) | CALL_GAS_LIMIT);
        op.preVerificationGas = PRE_VERIFICATION_GAS;
        op.gasFees = bytes32((MAX_PRIORITY_FEE << 128) | MAX_FEE);
        if (mode == Sponsor.Allowlist) {
            op.paymasterAndData = abi.encodePacked(
                address(paymaster), uint128(PM_VERIFICATION_GAS_LIMIT), uint128(PM_POST_OP_GAS_LIMIT)
            );
        } else if (mode == Sponsor.Signature) {
            op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, 0, 0, new bytes(65));
        }
    }

    /// @notice Sponsor authorization: sign the EntryPoint's userOpHash with
    /// `key` (the same raw-hash ECDSA SimpleAccount uses) and insert it.
    function signPaymaster(PackedUserOperation memory op, uint256 key, uint48 validUntil, uint48 validAfter)
        internal
        view
        returns (PackedUserOperation memory)
    {
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, validUntil, validAfter, new bytes(65));
        bytes32 h = entryPoint.getUserOpHash(op);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, h);
        op.paymasterAndData = signaturePaymasterAndData(sigPaymaster, validUntil, validAfter, abi.encodePacked(r, s, v));
        return op;
    }

    function signPaymaster(PackedUserOperation memory op, uint256 key) internal view returns (PackedUserOperation memory) {
        return signPaymaster(op, key, 0, 0);
    }

    function sign(PackedUserOperation memory op, uint256 key) internal view returns (PackedUserOperation memory) {
        bytes32 h = entryPoint.getUserOpHash(op);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, h);
        op.signature = abi.encodePacked(r, s, v);
        return op;
    }

    function fundPaymasters() internal {
        vm.deal(sponsorOperator, 2 * PAYMASTER_DEPOSIT);
        vm.startPrank(sponsorOperator);
        paymaster.deposit{value: PAYMASTER_DEPOSIT}();
        sigPaymaster.deposit{value: PAYMASTER_DEPOSIT}();
        vm.stopPrank();
    }

    function requiredPrefund(bool withPaymaster) internal view returns (uint256) {
        uint256 gas = VERIFICATION_GAS_LIMIT + CALL_GAS_LIMIT + PRE_VERIFICATION_GAS;
        if (withPaymaster) gas += PM_VERIFICATION_GAS_LIMIT + PM_POST_OP_GAS_LIMIT;
        return gas * MAX_FEE;
    }

    function submit(PackedUserOperation memory op) internal {
        PackedUserOperation[] memory ops = new PackedUserOperation[](1);
        ops[0] = op;
        // handleOps requires tx.origin == msg.sender (EOA bundler).
        vm.prank(bundler, bundler);
        entryPoint.handleOps(ops, beneficiary);
    }

    /// @notice Decode the single UserOperationEvent from recorded logs.
    function userOpEvent(Vm.Log[] memory logs)
        internal
        view
        returns (bytes32 userOpHash, address sender, address pm, bool success, uint256 actualGasCost, uint256 actualGasUsed)
    {
        bytes32 topic = IEntryPoint.UserOperationEvent.selector;
        uint256 found;
        for (uint256 i = 0; i < logs.length; i++) {
            if (logs[i].emitter == address(entryPoint) && logs[i].topics[0] == topic) {
                userOpHash = logs[i].topics[1];
                sender = address(uint160(uint256(logs[i].topics[2])));
                pm = address(uint160(uint256(logs[i].topics[3])));
                uint256 nonce;
                (nonce, success, actualGasCost, actualGasUsed) = abi.decode(logs[i].data, (uint256, bool, uint256, uint256));
                found++;
            }
        }
        require(found == 1, "expected exactly one UserOperationEvent");
    }

    /// @notice Step 1 of W1, identical in every baseline: sender -> fresh account.
    function deliverAsset(address to) internal {
        vm.prank(assetSender);
        require(token.transfer(to, AMOUNT));
    }
}
