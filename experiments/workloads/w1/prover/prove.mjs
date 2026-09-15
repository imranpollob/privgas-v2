// Real Semaphore v4 / Groth16 prover for the frozen B3 (PrivGas v1) evaluation.
//
// Uses exactly the library calls of the frozen B3 fixture generators
// (baselines/b3_privgas_v1/script/proof/generateSemaphoreFixture.mjs and
// generateFunctionalCorrectnessProofs.mjs): new Identity(secret), new Group(members),
// generateProof(identity, group, message, scope, merkleTreeDepth), verifyProof(proof).
// Nothing about the circuit, the scope, the message binding or the verifier is chosen
// here. The only difference is plumbing: the trusted-setup artifacts are passed as local
// files whose sha256 the Python side pins (artifacts-pin.json), instead of being fetched
// into the OS temp directory on every run.
//
// Protocol: one JSON object per stdin line, one JSON object per stdout line.
//   request  {"id", "op": "commitment", "identity_secret"}
//   request  {"id", "op": "prove", "identity_secret", "members": [dec...],
//             "message": dec, "scope": dec, "merkle_tree_depth": n,
//             "wasm": path, "zkey": path}
//   response {"id", "ok": true, ...} or {"id", "ok": false, "error"}
// The identity secret arrives on stdin only (never argv, never disk).

import { createInterface } from "node:readline"
import { Identity, Group, generateProof, verifyProof } from "@semaphore-protocol/core"

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity })

function reply(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`)
}

for await (const line of rl) {
  if (!line.trim()) continue
  let req
  try {
    req = JSON.parse(line)
  } catch (e) {
    reply({ id: null, ok: false, error: `bad request: ${e}` })
    continue
  }
  try {
    const identity = new Identity(req.identity_secret)
    if (req.op === "commitment") {
      reply({ id: req.id, ok: true, commitment: identity.commitment.toString() })
      continue
    }
    if (req.op !== "prove") throw new Error(`unknown op ${req.op}`)
    const group = new Group(req.members.map((m) => BigInt(m)))
    const message = BigInt(req.message)
    const scope = BigInt(req.scope)
    const started = process.hrtime.bigint()
    const proof = await generateProof(identity, group, message, scope, req.merkle_tree_depth, {
      wasm: req.wasm,
      zkey: req.zkey
    })
    const proveNs = process.hrtime.bigint() - started
    const vStarted = process.hrtime.bigint()
    const verified = await verifyProof(proof)
    const verifyNs = process.hrtime.bigint() - vStarted
    if (!verified) throw new Error("generated proof failed off-chain verification")
    if (BigInt(proof.message) !== message) throw new Error("proof message mismatch")
    if (BigInt(proof.merkleTreeRoot) !== group.root) throw new Error("proof root mismatch")
    reply({
      id: req.id,
      ok: true,
      proof,
      group_root: group.root.toString(),
      verified_off_chain: verified,
      prove_ms: Number(proveNs) / 1e6,
      verify_off_chain_ms: Number(verifyNs) / 1e6
    })
  } catch (e) {
    reply({ id: req.id, ok: false, error: String(e && e.stack ? e.stack : e) })
  }
}
// snarkjs keeps worker threads alive; stdin closed means the caller is done.
process.exit(0)
