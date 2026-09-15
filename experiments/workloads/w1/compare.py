"""Cross-baseline fairness checks, the W1 cost comparison, and the profile effect.

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
* B3 Spend minus B2-Signature UserOperation gas. Confounded by account
  deployment (inside B2-Signature's measured op, inside B3's Bootstrap op
  instead), the proof bytes in preVerificationGas, the CreditPaymaster
  verification limit and nullifier write, and ecrecover vs Groth16.

``profile_effect`` compares the same variant and seed across evaluation
profiles (eip170_standard vs b3_compat_local) and reports every workflow
quantity that differs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import abi
from .config import B3_BASELINE_ID
from .userop import unpack

Variant = Tuple[str, str]
AA_COLD = [("B1", "W1-cold"), ("B2-Allowlist", "W1-cold"), ("B2-Signature", "W1-cold")]
B3C = (B3_BASELINE_ID, "W1-cold")


def _bundles(dump: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in dump["transactions"]
            if t["phase"] == "workflow" and t["tx"]["input"][:10] == abi.SELECTOR_HANDLE_OPS]


def _op(t: Dict[str, Any]) -> Dict[str, Any]:
    ops, beneficiary = abi.decode_handle_ops(abi.data_bytes(t["tx"]["input"]))
    return {**unpack(ops[0]), "beneficiary": beneficiary}


def _measured_op(dump: Dict[str, Any]) -> Dict[str, Any]:
    """The measured W1 application operation: the last workflow bundle
    (B1/B2: the only one; B3: Spend, after Bootstrap)."""
    return _op(_bundles(dump)[-1])


def fairness_checks(runs: Dict[Variant, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Checks over B1, B2-Allowlist, B2-Signature, B1 warm and B3 where present."""
    checks: List[Dict[str, Any]] = []

    def same(name: str, values: List[Any], scope: str) -> None:
        checks.append({"check": name, "scope": scope, "ok": len({repr(v) for v in values}) == 1})

    b3 = [B3C] if B3C in runs else []
    aa = ([v for v in AA_COLD if v in runs] + [v for v in (("B1", "W1-warm"),) if v in runs]
          + b3)
    cold = [v for v in AA_COLD if v in runs]
    dumps = {v: runs[v]["chain_dump"] for v in runs}
    privs = {v: runs[v]["private"] for v in runs}
    ops = {v: _measured_op(dumps[v]) for v in aa}

    same("same evaluation chain profile (all runs compared)",
         [(dumps[v].get("evaluation_profile") or {}).get("profile_id") for v in runs], "all")
    same("same anvil arguments apart from the port (all runs compared)",
         [dumps[v]["environment"]["anvil_args"] for v in runs], "all")
    same("same deployed contract set and addresses (identical setup)",
         [dumps[v]["contracts"] for v in runs], "all")
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
    b2 = [v for v in cold if v[0].startswith("B2")]
    checks.append({"check": "B2 variants use different Paymasters", "scope": "B2",
                   "ok": len(b2) < 2 or len({ops[v]["paymaster"] for v in b2}) == len(b2)})
    if b3:
        d = dumps[B3C]
        boot = _op(_bundles(d)[0])
        checks.append({"check": "B3 deploys the same counterfactual account inside its own "
                                "flow (Bootstrap op carries initCode, same factory)",
                       "scope": "B3", "ok": boot["init_code_length"] > 0
                       and boot["factory"] == d["contracts"]["SimpleAccountFactory"]
                       and boot["sender"] == ops[B3C]["sender"]})
        checks.append({"check": "B3 application op is sponsored by a different Paymaster "
                                "than every B2 variant", "scope": "B3",
                       "ok": all(ops[B3C]["paymaster"] != ops[v]["paymaster"]
                                 for v in cold if v[0].startswith("B2"))})
    return checks


def unavoidable_differences(runs: Dict[Variant, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    ops = {v: _measured_op(runs[v]["chain_dump"]) for v in runs if v[0] != "B0"}
    for v, op in ops.items():
        row = {"variant": f"{v[0]} {v[1]}",
               "pre_verification_gas": op["pre_verification_gas"],
               "paymaster_and_data_present": op["paymaster"] is not None,
               "paymaster_signature_present": op["paymaster_signature_present"],
               "paymaster_and_data_bytes": len(op["paymaster_and_data"]),
               "paymaster_verification_gas_limit": op["paymaster_verification_gas_limit"],
               "init_code_present": op["init_code_length"] > 0}
        if v == B3C:
            boot = _op(_bundles(runs[v]["chain_dump"])[0])
            row.update({
                "workflow_userops": len(_bundles(runs[v]["chain_dump"])),
                "bootstrap_init_code_present": boot["init_code_length"] > 0,
                "bootstrap_call_gas_limit": boot["call_gas_limit"],
                "bootstrap_pre_verification_gas": boot["pre_verification_gas"],
                "bootstrap_and_spend_same_sender": boot["sender"] == op["sender"],
                "announcement_transaction": True})
        out.append(row)
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
    if B3C in costs and ("B2-Signature", "W1-cold") in costs:
        s = ("B2-Signature", "W1-cold")
        out["b3_spend_minus_b2_signature_by_difference"] = {
            "userop_gas": g(B3C, "spend_userop_gas_used") - g(s, "recipient_action_gas_used"),
            "of_which_pre_verification_gas": (g(B3C, "spend_pre_verification_gas")
                                              - g(s, "pre_verification_gas")),
            "b3_whole_workflow_sponsor_cost_minus_b2_signature": (
                g(B3C, "sponsor_cost") - g(s, "sponsor_cost")),
            "b3_whole_workflow_gas_fees_minus_b2_signature": (
                g(B3C, "total_eth_consumed_by_workflow")
                - g(s, "total_eth_consumed_by_workflow")),
            "confounds": "account deployment is inside B2-Signature's measured op but inside "
                         "B3's Bootstrap op; proof bytes vs signature bytes in "
                         "preVerificationGas; Groth16 verification and nullifier write vs "
                         "ecrecover; B3 also pays an announcement transaction and a burned "
                         "admission fee",
        }
    return out


#: Summary keys that are pure environment bookkeeping and legitimately differ
#: between profiles (the compat setup deploys and funds more contracts).
PROFILE_SETUP_KEYS = ("setup_gas_used",)


def profile_effect(standard: Dict[Variant, Dict[str, Any]],
                   compat: Dict[Variant, Dict[str, Any]]) -> Dict[str, Any]:
    """Same seed, same variant, two evaluation profiles: what changed?

    ``standard``/``compat`` map variant -> {"chain_dump", "costs"}. Compares every
    reconciliation summary value, every workflow transaction's gas and status,
    the measured UserOperation fields and the calibrated overheads.
    """
    out: Dict[str, Any] = {"variants": {}, "any_workflow_difference": False}
    for v in sorted(set(standard) & set(compat)):
        s, c = standard[v], compat[v]
        diffs = {k: {"eip170_standard": s["costs"]["summary"].get(k),
                     "b3_compat_local": c["costs"]["summary"].get(k)}
                 for k in sorted(set(s["costs"]["summary"]) | set(c["costs"]["summary"]))
                 if k not in PROFILE_SETUP_KEYS
                 and s["costs"]["summary"].get(k) != c["costs"]["summary"].get(k)}

        def wf(dump):
            return [(int(t["receipt"]["gasUsed"], 16), int(t["receipt"]["status"], 16),
                     t["tx"]["input"][:10], int(t["tx"]["value"], 16))
                    for t in dump["transactions"] if t["phase"] in ("workflow", "warmup")]

        def op_fields(dump):
            if v[0] == "B0":
                return None
            op = _measured_op(dump)
            return {k: op[k] for k in ("pre_verification_gas", "verification_gas_limit",
                                       "call_gas_limit", "max_fee_per_gas",
                                       "paymaster_verification_gas_limit", "init_code_length")}

        def overheads(dump):
            return {label: rec.get("entrypoint_unmeasured_overhead")
                    for label, rec in dump["pvg_records"].items()}

        same_wf = wf(s["chain_dump"]) == wf(c["chain_dump"])
        same_op = op_fields(s["chain_dump"]) == op_fields(c["chain_dump"])
        same_o = overheads(s["chain_dump"]) == overheads(c["chain_dump"])
        entry = {
            "summary_differences_excluding_setup": diffs,
            "workflow_transactions_identical_gas_status_selector_value": same_wf,
            "measured_userop_fields_identical": same_op,
            "calibrated_overhead_identical": same_o,
            "setup_gas_used": {"eip170_standard": s["costs"]["summary"]["setup_gas_used"],
                               "b3_compat_local": c["costs"]["summary"]["setup_gas_used"]},
            "reconciliation_checks": {
                "eip170_standard": f"{sum(x['ok'] for x in s['costs']['checks'])}/"
                                   f"{len(s['costs']['checks'])}",
                "b3_compat_local": f"{sum(x['ok'] for x in c['costs']['checks'])}/"
                                   f"{len(c['costs']['checks'])}"},
        }
        out["variants"][f"{v[0]} {v[1]}"] = entry
        if diffs or not (same_wf and same_op and same_o):
            out["any_workflow_difference"] = True
    return out
