"""Minimal JSON-RPC client and a throwaway anvil process.

Stdlib only (urllib), so the transport is fully visible: no provider
middleware silently fills gas, fees or nonces.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
from typing import Any, List, Optional


class RpcError(RuntimeError):
    def __init__(self, method: str, error: Any) -> None:
        self.method = method
        self.error = error
        message = error.get("message") if isinstance(error, dict) else str(error)
        super().__init__(f"{method}: {message}")

    @property
    def data(self) -> Optional[str]:
        if isinstance(self.error, dict):
            d = self.error.get("data")
            if isinstance(d, str):
                return d
            if isinstance(d, dict):
                return d.get("data")
        return None


class Rpc:
    def __init__(self, url: str) -> None:
        self.url = url
        self._id = 0
        self.calls = 0

    def call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        self._id += 1
        self.calls += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method,
                           "params": params or []}).encode()
        req = urllib.request.Request(self.url, data=body,
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
        if "error" in payload:
            raise RpcError(method, payload["error"])
        return payload["result"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


ANVIL_HARDFORK = "prague"


class AnvilProcess:
    """A private anvil for exactly one run. Torn down on exit.

    Flags are explicit so the chain environment is part of the record:
    chain id from the W1 config, pinned hardfork, EIP-170 code-size limit left
    at its default (enforced), automine (one transaction per block).
    """

    def __init__(self, chain_id: int, base_fee: int) -> None:
        self.port = _free_port()
        self.args = ["anvil", "--port", str(self.port), "--chain-id",
                     str(chain_id), "--hardfork", ANVIL_HARDFORK,
                     "--block-base-fee-per-gas", str(base_fee), "--silent"]
        self.proc: Optional[subprocess.Popen] = None
        self.rpc = Rpc(f"http://127.0.0.1:{self.port}")
        self.version: Optional[str] = None

    def __enter__(self) -> "AnvilProcess":
        self.version = subprocess.run(["anvil", "--version"], capture_output=True,
                                      text=True, check=True).stdout.strip()
        self.proc = subprocess.Popen(self.args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"anvil exited early: {self.proc.stderr.read().decode()[:400]}")
            try:
                self.rpc.call("eth_chainId")
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("anvil did not start within 30s")

    def __exit__(self, *exc) -> bool:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self.proc.kill()
                self.proc.wait()
            if self.proc.stderr is not None:
                self.proc.stderr.close()
        return False
