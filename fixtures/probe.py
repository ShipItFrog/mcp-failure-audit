"""Wire-level probe for the audit fixtures.

Launches an MCP server over stdio, speaks raw JSON-RPC to it (standard library only,
no MCP SDK on the client side), and records exactly what a client -- and so the
model -- receives for each call, plus any stray non-JSON lines the server writes to
stdout.

Usage:
    python probe.py <server-python> <server-script> <cases.json> [--out results.json]

cases.json is a list of {"method": "...", "params": {...}, "note": "..."} objects,
sent in order after the initialize handshake.
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_S = 20


def _pump(stream, q, tag):
    for raw in iter(stream.readline, b""):
        q.put((tag, raw.decode("utf-8", errors="replace").rstrip("\r\n")))
    q.put((tag, None))


class Probe:
    def __init__(self, python, script):
        # absolute paths: Windows CreateProcess does not resolve relative
        # executable paths written with forward slashes
        self.proc = subprocess.Popen(
            [os.path.abspath(python), os.path.abspath(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.q = queue.Queue()
        self.stray = []  # non-JSON lines on stdout: stream corruption
        self.notifications = []  # valid JSON-RPC notifications (e.g. log messages)
        self.after_shutdown = []  # stdout lines that only appeared once the server exited
        self.stderr = []
        self.closed = False
        threading.Thread(target=_pump, args=(self.proc.stdout, self.q, "out"), daemon=True).start()
        threading.Thread(target=_pump, args=(self.proc.stderr, self.q, "err"), daemon=True).start()
        self._next_id = 1

    def _send(self, msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def request(self, method, params):
        rid = self._next_id
        self._next_id += 1
        stray_before = len(self.stray)
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        except OSError as exc:
            return {"transport_error": f"write failed: {exc}"}, []
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                tag, line = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                if tag == "out":
                    self.closed = True
                    return {"transport_error": "server closed stdout"}, self.stray[stray_before:]
                continue
            if tag == "err":
                self.stderr.append(line)
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.stray.append(line)
                continue
            if msg.get("id") == rid:
                return msg, self.stray[stray_before:]
            self.notifications.append(msg)
        return {"transport_error": f"no response within {TIMEOUT_S}s"}, self.stray[stray_before:]

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        # drain what is left; buffered print() output often only lands here
        time.sleep(0.5)
        while True:
            try:
                tag, line = self.q.get_nowait()
            except queue.Empty:
                break
            if line is None:
                continue
            if tag == "err":
                self.stderr.append(line)
            else:
                self.after_shutdown.append(line)


def _placeholders():
    """Local paths to scrub from saved results, longest first."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    home = os.path.expanduser("~")
    pairs = []
    for real, tag in ((repo, "<repo>"), (home, "<home>")):
        for variant in {real, real.replace("\\", "/"), real.replace("\\", "\\\\")}:
            pairs.append((variant, tag))
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def scrub(obj, pairs):
    """Replace machine-specific paths so results can be published."""
    if isinstance(obj, str):
        for real, tag in pairs:
            # case-insensitive: Windows reports the same path as C:\Users or c:\users
            obj = re.sub(re.escape(real), lambda _m, t=tag: t, obj, flags=re.IGNORECASE)
        return obj
    if isinstance(obj, list):
        return [scrub(x, pairs) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v, pairs) for k, v in obj.items()}
    return obj


def summarize(resp):
    """One-line view of what the client got."""
    if "transport_error" in resp:
        return "TRANSPORT ERROR: " + resp["transport_error"]
    if "error" in resp:
        e = resp["error"]
        return f"JSON-RPC error {e.get('code')}: {e.get('message')}"
    result = resp.get("result", {})
    if "isError" in result or "content" in result:
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return f"isError={result.get('isError', False)} | {' / '.join(texts)[:200]}"
    if "contents" in result:
        return f"contents={len(result['contents'])} item(s)"
    return json.dumps(result)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("python")
    ap.add_argument("script")
    ap.add_argument("cases")
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)

    p = Probe(args.python, args.script)
    records = []
    init, stray = p.request("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "mcp-failure-audit-probe", "version": "0.1.0"},
    })
    records.append({"method": "initialize", "summary": summarize(init), "stray_stdout": stray,
                    "negotiated": init.get("result", {}).get("protocolVersion")})
    if "result" in init:
        p.notify("notifications/initialized")
        for case in cases:
            if p.closed:
                records.append({**case, "summary": "SKIPPED: server already closed stdout"})
                continue
            params = json.loads(json.dumps(case.get("params", {})))
            # "repeat_args": {"msg": 900} repeats that string argument 900 times, to push
            # large output through a server without writing 9 KB literals into cases.json
            for key, times in case.get("repeat_args", {}).items():
                params["arguments"][key] = params["arguments"][key] * times
            resp, stray = p.request(case["method"], params)
            records.append({**case, "summary": summarize(resp), "stray_stdout": stray, "raw": resp})
    p.close()

    report = {
        "script": args.script,
        "records": records,
        "notifications": p.notifications,
        "stdout_after_shutdown": p.after_shutdown,
        "stderr_tail": p.stderr[-120:],
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(scrub(report, _placeholders()), f, indent=2, ensure_ascii=False)
    for r in records:
        label = r.get("note") or r["method"]
        stray = r.get("stray_stdout") or []
        extra = f"  [STRAY STDOUT x{len(stray)}: {stray[0][:60]!r}...]" if stray else ""
        print(f"- {label}: {r['summary']}{extra}")
    print(f"- notifications received: {len(p.notifications)}")
    shown = [line[:60] for line in p.after_shutdown[:3]]
    print(f"- stdout lines that appeared only after shutdown: {len(p.after_shutdown)} {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
