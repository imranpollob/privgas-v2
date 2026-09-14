"""Cross-baseline fairness checks and the W1 cost comparison.

Input: the (chain dump, private role file, reconciliation) of each variant.
Output: booleans and numbers only -- no addresses or role labels -- so the
comparison can be written under results/ without leaking who is who.

Derived quantities are identified BY DIFFERENCE and carry their confounds:

* account deployment component = B1 W1-cold minus B1 W1-warm. Confounded by
  the EntryPoint nonce write (sequence 0 -> 1 is a zero-to-non-zero SSTORE in
  cold; 1 -> 2 in warm), by initCode calldata inside the calibrated
  preVerificationGas, and by warm's non-empty EntryPoint deposit.
* signature-authorization overhead = B2-Signature minus B2-Allowlist
  UserOperation gas. Confounded by the extra paymasterAndData bytes (in
  preVerificationGas) and by the allowlist paymaster's cold storage read.
  B2-Allowlist's on-chain authorization cost is its separate setSponsored
  transaction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import abi
from .userop import unpack

Variant = Tuple[str, str]
AA_COLD = [("B1", "W1-cold"), ("B2-Allowlist", "W1-cold"), ("B2-Signature", "W1-cold")]


def _measured_op(dump: Dict[str, Any]) -> Dict[str, Any]:
    t = next(t for t in dump["transactions"]
             if t["phase"] == "workflow" and t["tx"]["input"][:10] == abi.SELECTOR_HANDLE_OPS)
    ops, beneficiary = abi.decode_handle_ops(abi.data_bytes(t["tx"]["input"]))
    return {**unpack(ops[0]), "beneficiary": beneficiary}


def fairness_checks(runs: Dict[Variant, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every check compares B1, B2-Allowlist and B2-Signature (and B1 warm where stated)."""
    checks: List[Dict[str, Any]] = []

    def same(name: str, values: List[Any], scope: str) -> None:
        checks.append({"check": name, "scope": scope, "ok": len({repr(v) for v in values}) == 1})

    aa = [v for v in AA_COLD if v in runs] + [v for v in (("B1", "W1-warm"),) if v in runs]
    cold = [v for v in AA_COLD if v in runs]
    dumps = {v: runs[v]["chain_dump"] for v in runs}
    privs = {v: runs[v]["private"] for v in runs}
    ops = {v: _measured_op(dumps[v]) for v in aa}

    same("same EntryPoint address", [dumps[v]["contracts"]["EntryPoint"] for v in aa], "AA")
    same("same EntryPoint bytecode", [dumps[v]["artifacts"]["EntryPoint"] for v in aa], "AA")
    same("same SimpleAccount implementation address",
         [dumps[v]["contracts"]["SimpleAccount_implementation"] for v in aa], "AA")
    same("same SimpleAccount implementation bytecode",
         [dumps[v]["artifacts"]["SimpleAccount"] for v in aa], "AA")
    same("same factory", [dumps[v]["contracts"]["SimpleAccountFactory"] for v in aa], "AA")
    same("same recipient smart account",
         [privs[v]["roles"]["recipient_account"] for v in aa], "AA")
    same("same token (all baselines)", [dumps[v]["contracts"]["W1Token"] for v in runs], "all")
    same("same token amount (all baselines)",
         [dumps[v]["config"]["token"]["transfer_amount"] for v in runs], "all")
    same("same destination (all baselines)", [privs[v]["roles"]["destination"] for v in runs], "all")
    same("same application call (execute calldata)", [ops[v]["call_data"] for v in aa], "AA")
    same("same account gas limits",
         [(ops[v]["verification_gas_limit"], ops[v]["call_gas_limit"]) for v in aa], "AA")
    same("same fee fields",
         [(ops[v]["max_fee_per_gas"], ops[v]["max_priority_fee_per_gas"]) for v in aa], "AA")
    same("same fee environment (base fee pinned, one fee policy)",
         [dumps[v]["config"]["fees"] for v in runs], "all")
    same("same deployment mode within the cold comparison (initCode present)",
         [ops[v]["init_code_length"] > 0 for v in cold] + [True], "AA cold")
    checks.append({"check": "warm comparison op carries no initCode", "scope": "B1 warm",
                   "ok": ("B1", "W1-warm") not in ops
                   or ops[("B1", "W1-warm")]["init_code_length"] == 0})
    same("same bundler implementation", [dumps[v]["bundler"]["bundler_id"] for v in aa], "AA")
    same("same preVerificationGas method",
         [dumps[v]["bundler"]["pre_verification_gas_method"] for v in aa], "AA")
    same("same beneficiary", [ops[v]["beneficiary"] for v in aa], "AA")
    same("same paymaster gas limits for both B2 variants",
         [(ops[v]["paymaster_verification_gas_limit"], ops[v]["paymaster_post_op_gas_limit"])
          for v in cold if v[0].startswith("B2")], "B2")
    checks.append({"check": "B2 variants use different Paymasters", "scope": "B2",
                   "ok": len({ops[v]["paymaster"] for v in cold if v[0].startswith("B2")}) == 2})
    return checks


def unavoidable_differences(runs: Dict[Variant, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    ops = {v: _measured_op(runs[v]["chain_dump"]) for v in runs if v[0] != "B0"}
    for v, op in ops.items():
        out.append({"variant": f"{v[0]} {v[1]}",
                    "pre_verification_gas": op["pre_verification_gas"],
                    "paymaster_and_data_present": op["paymaster"] is not None,
                    "paymaster_signature_present": op["paymaster_signature_present"],
                    "init_code_present": op["init_code_length"] > 0})
    return out


def derived(costs: Dict[Variant, Dict[str, Any]]) -> Dict[str, Any]:
    def g(v, key, section="summary"):
        return int(costs[v][section][key])

    out: Dict[str, Any] = {}
    if ("B1", "W1-cold") in costs and ("B1", "W1-warm") in costs:
        c, w = ("B1", "W1-cold"), ("B1", "W1-warm")
        out["account_deployment_component_by_difference"] = {
            "userop_gas": g(c, "recipient_action_gas_used") - g(w, "recipient_action_gas_used"),
            "pre_verification_gas": g(c, "pre_verification_gas") - g(w, "pre_verification_gas"),
            "bundle_transaction_gas": (g(c, "bundle_transaction_gas_used")
                                       - g(w, "bundle_transaction_gas_used")),
            "confounds": "EntryPoint nonce first write (0->1) in cold vs 1->2 in warm; "
                         "initCode calldata; warm account starts with a non-zero deposit",
        }
    if ("B2-Allowlist", "W1-cold") in costs and ("B2-Signature", "W1-cold") in costs:
        a, s = ("B2-Allowlist", "W1-cold"), ("B2-Signature", "W1-cold")
        out["signature_authorization_overhead_by_difference"] = {
            "userop_gas": g(s, "recipient_action_gas_used") - g(a, "recipient_action_gas_used"),
            "of_which_pre_verification_gas": (g(s, "pre_verification_gas")
                                              - g(a, "pre_verification_gas")),
            "of_which_validation_and_execution": (
                (g(s, "recipient_action_gas_used") - g(s, "pre_verification_gas"))
                - (g(a, "recipient_action_gas_used") - g(a, "pre_verification_gas"))),
            "allowlist_authorization_transaction_gas": next(
                int(t["gas_used"]) for t in costs[a]["transactions"]
                if t["label"] == "w2_sponsor_allowlist"),
            "confounds": "signature suffix calldata (in preVerificationGas); allowlist "
                         "storage read vs ecrecover and ABI decoding",
        }
    return out
