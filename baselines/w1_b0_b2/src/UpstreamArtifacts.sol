// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

// Compile-only import so `forge build` emits artifacts for the unmodified
// upstream eth-infinitism v0.9.0 contracts that B1 and B2 deploy. Nothing is
// subclassed or changed: the runner deploys EntryPoint and
// SimpleAccountFactory exactly as they are in
// account-abstraction@b36a1ed52ae00da6f8a4c8d50181e2877e4fa410.
import {EntryPoint} from "account-abstraction/core/EntryPoint.sol";
import {SimpleAccountFactory} from "account-abstraction/accounts/SimpleAccountFactory.sol";
import {SimpleAccount} from "account-abstraction/accounts/SimpleAccount.sol";
