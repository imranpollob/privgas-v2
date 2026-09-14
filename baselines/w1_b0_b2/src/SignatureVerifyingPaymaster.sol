// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {BasePaymaster} from "account-abstraction/core/BasePaymaster.sol";
import {IEntryPoint} from "account-abstraction/interfaces/IEntryPoint.sol";
import {PackedUserOperation} from "account-abstraction/interfaces/PackedUserOperation.sol";
import {UserOperationLib} from "account-abstraction/core/UserOperationLib.sol";
import {_packValidationData} from "account-abstraction/core/Helpers.sol";

/// @title SignatureVerifyingPaymaster (baseline B2-Signature)
/// @notice An ordinary, non-private Paymaster that sponsors a UserOperation
/// carrying a valid ECDSA authorization from one public sponsor key.
///
/// NOTHING NEW IS DESIGNED HERE. Every piece is taken from the pinned
/// eth-infinitism account-abstraction v0.9.0 tree
/// (commit b36a1ed52ae00da6f8a4c8d50181e2877e4fa410):
///
///  * WHAT IS SIGNED: the `userOpHash` the EntryPoint passes to
///    `validatePaymasterUserOp` -- i.e. `EntryPoint.getUserOpHash(userOp)`,
///    the v0.9.0 EIP-712 digest
///        keccak256(0x1901 || domainSeparator || structHash)
///    with domain {name "ERC4337", version "1", chainId, verifyingContract =
///    EntryPoint} and structHash over
///        PackedUserOperation(sender, nonce, keccak(initCode), keccak(callData),
///        accountGasLimits, preVerificationGas, gasFees,
///        paymasterDataKeccak(paymasterAndData)).
///    This is the same digest SimpleAccount v0.9.0 verifies with
///    `ECDSA.recover(userOpHash, signature)`; the sponsor signs it the same way.
///  * HOW THE SIGNATURE IS CARRIED: v0.9.0's paymaster-signature suffix
///        paymasterAndData = paymaster || pmVerificationGasLimit || pmPostOpGasLimit
///                           || signedPaymasterData || pmSignature
///                           || uint16(len(pmSignature)) || PAYMASTER_SIG_MAGIC
///    parsed with UserOperationLib.getSignedPaymasterData /
///    getPaymasterSignature. `paymasterDataKeccak` hashes everything up to the
///    signature and then the magic, so the signature bytes are EXCLUDED from
///    userOpHash while its presence is not -- which is what lets the sponsor
///    sign the final hash (the pattern upstream's TestPaymasterWithSig
///    exercises with a toy check).
///  * signedPaymasterData = abi.encode(uint48 validUntil, uint48 validAfter),
///    returned through upstream `_packValidationData`, which the EntryPoint
///    enforces (AA32 when outside the window). 0/0 means no time bound.
///  * FAILURE MODE: a wrong, missing or malformed signature returns
///    SIG_VALIDATION_FAILED (upstream convention), which the EntryPoint turns
///    into `FailedOp(i, "AA34 signature error")`. Malformed signed data reverts
///    (`AA33 reverted`).
///
/// Bound by the signature (through userOpHash): chain id, EntryPoint address,
/// sender, full 256-bit nonce, initCode, callData, all account gas limits,
/// preVerificationGas, both fee fields, this paymaster's address, both
/// paymaster gas limits, and validUntil/validAfter. Replay protection comes
/// from the EntryPoint nonce (a used nonce cannot be included again, and any
/// other nonce yields a different hash); this contract keeps no replay state.
///
/// Human review of this binding is still required (docs/research-plan.md
/// Sec. 18). Not a privacy mechanism; the paymaster address is public.
contract SignatureVerifyingPaymaster is BasePaymaster {
    /// @notice The sponsor's authorization key. Immutable: validation reads no storage.
    address public immutable verifyingSigner;

    uint256 private constant SIGNED_PAYMASTER_DATA_LENGTH = 64;

    error InvalidVerifyingSigner();
    error InvalidSignedPaymasterDataLength(uint256 length);

    constructor(IEntryPoint entryPoint_, address owner_, address verifyingSigner_)
        BasePaymaster(entryPoint_, owner_)
    {
        if (verifyingSigner_ == address(0)) revert InvalidVerifyingSigner();
        verifyingSigner = verifyingSigner_;
    }

    function _validatePaymasterUserOp(PackedUserOperation calldata userOp, bytes32 userOpHash, uint256)
        internal
        view
        override
        returns (bytes memory context, uint256 validationData)
    {
        bytes calldata signedData = UserOperationLib.getSignedPaymasterData(userOp.paymasterAndData);
        if (signedData.length != SIGNED_PAYMASTER_DATA_LENGTH) {
            revert InvalidSignedPaymasterDataLength(signedData.length);
        }
        (uint48 validUntil, uint48 validAfter) = abi.decode(signedData, (uint48, uint48));

        bytes calldata signature = UserOperationLib.getPaymasterSignature(userOp.paymasterAndData);
        (address recovered, ECDSA.RecoverError err,) = ECDSA.tryRecover(userOpHash, signature);
        bool sigFailed = err != ECDSA.RecoverError.NoError || recovered != verifyingSigner;
        return ("", _packValidationData(sigFailed, validUntil, validAfter));
    }
}
