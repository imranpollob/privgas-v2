// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title W1Token
/// @notice The single ERC-20 asset used by workload W1 in B0, B1 and B2.
/// @dev Deliberately the plain OpenZeppelin 5.6.1 ERC20 with no hooks, fees,
///      permits or allowlists: the application action must be identical
///      across baselines, so the token contributes no baseline-specific
///      behaviour. The whole fixed supply is minted once to `holder`.
contract W1Token is ERC20 {
    constructor(address holder, uint256 supply) ERC20("PrivGas W1 Token", "W1T") {
        _mint(holder, supply);
    }
}
