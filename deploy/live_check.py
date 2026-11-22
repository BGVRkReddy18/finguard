#!/usr/bin/env python3
"""End-to-end check of the live demo: does what a visitor does, and fails loudly.

UptimeRobot only pings /api/health/, which deliberately never touches the database (so Neon can sleep).
This runs once a day and covers the rest: console, login, cases, AI investigation, saved report.

Retries are narrow on purpose. Only waking up (health) and a degraded LLM answer (free-tier rate limit)
are retried. A 500 is never retried: a stale-connection bug often passes on the second attempt.

A full run writes one AI report (and its audit entry) to an unresolved case. --read-only skips that.
Standard library only.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.client import HTTPException

USER_AGENT = "live-demo-check/1.0"  # urllib's default agent is blocked by some CDNs


class CheckError(Exception):
    pass


def request(url: str, *, body: dict | None = None, headers: dict | None = None, method: str | None = None,
            timeout: float = 60):
    """Returns (status, headers, text). HTTP errors are returned; network errors raise CheckError."""
    if not url.startswith(("https://", "http://")):
        raise CheckError(f"Not an HTTP URL: {url}")
    data = None if body is None else json.dumps(body).encode()
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 (scheme checked)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 (scheme checked)
            return res.status, res.headers, res.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode(errors="replace")
    except (OSError, HTTPException) as exc:
        raise CheckError(f"{url}: {type(exc).__name__}: {exc}") from exc


class LiveCheck:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.api = args.api.rstrip("/")
        self.web = args.web.rstrip("/")
        self.auth: dict[str, str] = {}
        self.case: dict = {}

    def api_json(self, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        """Call the API as the browser would: 200, readable cross-origin, JSON object."""
        status, headers, text = request(self.api + path, body=body, timeout=timeout,
                                        method="POST" if body is not None else "GET",
                                        headers={"Origin": self.web, **self.auth})
        if status != 200:
            raise CheckError(f"{path} returned HTTP {status}: {text[:300]}")
        if headers.get("Access-Control-Allow-Origin") not in (self.web, "*"):
            raise CheckError(f"{path} has no CORS header for {self.web}, so the browser cannot read it")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise CheckError(f"{path} did not return JSON: {text[:300]}") from exc
        if not isinstance(data, dict):
            raise CheckError(f"{path} returned an unexpected shape: {text[:300]}")
        return data

    def backend_awake(self) -> str:
        start = time.monotonic()
        while True:
            try:
                status, _, _ = request(f"{self.api}/api/health/", timeout=30)
                if status == 200:
                    return f"up after {time.monotonic() - start:.0f}s"
                problem = f"HTTP {status}"
            except CheckError as exc:
                problem = str(exc)
            if time.monotonic() - start >= self.args.wake_timeout:
                raise CheckError(f"backend not up after {self.args.wake_timeout:.0f}s ({problem})")
            time.sleep(min(10, self.args.wake_timeout))

    def console(self) -> str:
        status, _, text = request(f"{self.web}/login")
        if status != 200 or "FinGuard" not in text:
            raise CheckError(f"login page returned HTTP {status} or is not the FinGuard console")
        return "login page served"

    def login(self) -> str:
        data = self.api_json("/api/auth/token/", {"username": self.args.username, "password": self.args.password})
        if not data.get("access"):
            raise CheckError("login response has no access token")
        self.auth = {"Authorization": f"Bearer {data['access']}"}
        return f"signed in as {self.args.username}"

    def model(self) -> str:
        version = self.api_json("/ml/model/info").get("version", "")
        if not version.startswith("xgb-"):
            raise CheckError(f"scoring is not using XGBoost (version: {version!r})")
        return version

    def cases(self) -> str:
        # Never re-investigate a resolved case: its report is part of a closed record.
        for status in ("OPEN", "INVESTIGATING"):
            found = self.api_json(f"/api/cases/?status={status}").get("results")
            if found:
                # Prefer a case without a report, so existing reports are rarely overwritten
                self.case = next((c for c in found if not c.get("ai_generated_at")), found[0])
                return f"using {status} case #{self.case['id']}"
        raise CheckError("no unresolved case to test with (open the dashboard for a few minutes to create some)")

    def investigation(self) -> str:
        path = f"/ai/investigate/{self.case['id']}"
        for attempt in range(2):
            if attempt:
                time.sleep(self.args.llm_retry_delay)
            report = self.api_json(path, {}, timeout=180).get("report") or {}
            model = report.get("model", "")
            # The agent hides LLM failures behind a template report with HTTP 200
            if report.get("recommendation") and model and not model.startswith("offline"):
                return f"{report['recommendation']} from {model}"
        raise CheckError(f"no real AI report after 2 attempts (got {model or 'no model'!r}): "
                         "check the Groq key, quota and whether the model was retired")

    def report_saved(self) -> str:
        after = self.api_json(f"/api/cases/{self.case['id']}/")
        stamp = after.get("ai_generated_at")
        if not stamp or stamp == self.case.get("ai_generated_at"):
            raise CheckError("the AI answered, but its report was not saved to the case")
        return f"saved at {stamp}"

    def run(self) -> bool:
        steps = [("Backend awake", self.backend_awake), ("Console", self.console), ("Login", self.login),
                 ("Fraud model", self.model), ("Cases (database)", self.cases)]
        if not self.args.read_only:
            steps += [("AI investigation", self.investigation), ("Report saved", self.report_saved)]
        results = []
        for name, step in steps:
            start = time.monotonic()
            try:
                ok, detail = True, step()
            except CheckError as exc:
                ok, detail = False, str(exc)
            except Exception as exc:  # a malformed response must still produce a readable failure
                ok, detail = False, f"unexpected response ({type(exc).__name__}: {exc})"
            detail = " ".join(detail.split())  # one line: response bodies must not inject workflow commands
            print(f"{'PASS' if ok else 'FAIL'}  {name:<18} {time.monotonic() - start:6.1f}s  {detail}", flush=True)
            results.append((name, ok, detail))
            if not ok:  # later steps depend on earlier ones
                if os.environ.get("GITHUB_ACTIONS"):
                    print(f"::error title=Live demo: {name}::{detail.replace('%', '%25')}")
                break
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as out:
                out.write("| Step | Result | Detail |\n|---|---|---|\n")
                for name, ok, detail in results:
                    out.write(f"| {name} | {'pass' if ok else '**FAIL**'} | {detail.replace('|', '/')} |\n")
        return all(ok for _, ok, _ in results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="https://finguard-api-qblt.onrender.com")
    parser.add_argument("--web", default="https://finguard-swart.vercel.app")
    parser.add_argument("--username", default="analyst")
    parser.add_argument("--password", default="finguard123")  # the public demo login shown on the login page
    parser.add_argument("--wake-timeout", type=float, default=300)
    parser.add_argument("--llm-retry-delay", type=float, default=75)  # past Groq's per-minute window
    parser.add_argument("--read-only", action="store_true", help="skip the AI investigation (no writes)")
    return 0 if LiveCheck(parser.parse_args()).run() else 1


if __name__ == "__main__":
    sys.exit(main())
