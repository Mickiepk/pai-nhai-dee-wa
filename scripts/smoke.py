"""Post-deploy smoke test for the webhook Function URL.

Sends only *empty-event* webhooks (the same shape LINE's "Verify" button sends), so nothing is
queued, the worker is never invoked, and no Gemini / Places / LINE API call is made.

Checks:
  1. validly signed body           -> 200
  2. wrong signature               -> 401
  3. missing signature header      -> 401

Usage:
  python -m scripts.smoke --url https://xxxx.lambda-url.ap-southeast-1.on.aws/ --secret-from-env
  LINE_CHANNEL_SECRET=... python -m scripts.smoke --url URL --secret-from-env
  python -m scripts.smoke --url URL --secret-ssm /pai-nhai-dee-wa/dev/line-channel-secret   # needs aws CLI login
  python -m scripts.smoke --url URL --secret-from-env --expect-only-reachable            # skip sig checks

Exit code 0 = all checks passed, 1 = at least one failed, 2 = bad arguments.
The secret is never printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BODY = json.dumps({"destination": "Usmoketest", "events": []}).encode()


def sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def post(url: str, body: bytes, signature: str | None, timeout: float) -> tuple[int, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "pai-nhai-dee-wa-smoke/1"}
    if signature is not None:
        headers["X-Line-Signature"] = signature
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(200).decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode(errors="replace")


def post_retry(url: str, body: bytes, signature: str | None, timeout: float) -> tuple[int, str]:
    """One retry: the first call can hit a Lambda cold start or a transient network error."""
    try:
        return post(url, body, signature, timeout)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        time.sleep(2)
        return post(url, body, signature, timeout)


def load_secret(args: argparse.Namespace) -> str:
    if args.secret_ssm:
        out = subprocess.run(
            ["aws", "ssm", "get-parameter", "--with-decryption", "--name", args.secret_ssm,
             "--query", "Parameter.Value", "--output", "text"],
            capture_output=True, text=True, check=False)
        if out.returncode != 0:
            sys.exit(f"cannot read SSM parameter (aws login? name?): {out.stderr.strip()[:200]}")
        return out.stdout.strip()
    return os.environ.get("LINE_CHANNEL_SECRET", "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="WebhookUrl from `sam deploy` outputs")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--secret-from-env", action="store_true", help="read LINE_CHANNEL_SECRET from the environment")
    src.add_argument("--secret-ssm", metavar="NAME", help="read the secret from SSM via the aws CLI")
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--expect-only-reachable", action="store_true",
                    help="no secret: only check the URL answers 401 to an unsigned request")
    args = ap.parse_args(argv)

    if not args.url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        print("URL must start with https:// (LINE requires HTTPS; http://localhost is allowed only for local tests)")
        return 2

    results: list[tuple[str, bool, str]] = []

    def check(name: str, got: int, want: int) -> None:
        results.append((name, got == want, f"got {got}, want {want}"))

    try:
        code, _ = post_retry(args.url, BODY, None, args.timeout)
        check("unsigned request is rejected", code, 401)
        code, _ = post_retry(args.url, BODY, sign("definitely-not-the-secret", BODY), args.timeout)
        check("wrong signature is rejected", code, 401)

        if not args.expect_only_reachable:
            secret = load_secret(args)
            if not secret:
                print("no secret: use --secret-from-env (with LINE_CHANNEL_SECRET set) or --secret-ssm NAME")
                return 2
            code, _ = post_retry(args.url, BODY, sign(secret, BODY), args.timeout)
            check("correctly signed empty webhook returns 200", code, 200)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        print(f"FAIL cannot reach {args.url}: {type(e).__name__}")
        return 1

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name} ({detail})")
    ok_all = all(ok for _, ok, _ in results)
    print("SMOKE OK" if ok_all else "SMOKE FAILED - see docs/DEPLOY.md section Troubleshooting")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
