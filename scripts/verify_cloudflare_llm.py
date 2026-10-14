"""Live Cloudflare Workers AI verification for the RazorGrowth text-LLM provider.

This is the ONLY way to prove the provider works end to end. Everything in
tests/ is mocked at the OpenAI-SDK boundary and therefore proves nothing about
the hosted model itself.

WHAT IT CHECKS
  1. API token is active
  2. The configured model is reachable
  3. Ordinary text generation
  4. Structured JSON output (response_format)
  5. Tool / function calling
  6. Streaming

SECURITY
  * Credentials are read from the root .env and NEVER printed.
  * Any provider output is scrubbed of the token and account id before it is
    printed, so a failure cannot leak a credential into a terminal, a log or a
    CI transcript.

EXIT CODES
  0  every check passed
  1  at least one check failed (most often: the account's DAILY FREE
     ALLOCATION is exhausted, which is a real, documented Cloudflare limit
     that resets at 00:00 UTC — not a code defect)

Usage
  python scripts/verify_cloudflare_llm.py
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Later definitions win, matching python-dotenv.
            env[key] = value.strip()
    return env


ENV = load_env()
ACCOUNT = ENV.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
TOKEN = ENV.get("CLOUDFLARE_API_TOKEN", "").strip()
MODEL = ENV.get("CLOUDFLARE_TEXT_MODEL", "").strip() or "@cf/zai-org/glm-4.7-flash"

BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/v1"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

results: list[tuple[str, bool, str]] = []


def scrub(text: str) -> str:
    for secret in (TOKEN, ACCOUNT):
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return text


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, scrub(detail)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {scrub(detail)}" if detail else ""))


def main() -> int:
    print("Cloudflare Workers AI — live text-LLM verification")
    print(f"  account : {'set' if ACCOUNT else 'MISSING'}")
    print(f"  token   : {'set' if TOKEN else 'MISSING'}")
    print(f"  model   : {MODEL}\n")

    if not ACCOUNT or not TOKEN:
        record("configuration present", False, "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN missing")
        return 1

    # 1 — token ------------------------------------------------------------
    try:
        r = httpx.get("https://api.cloudflare.com/client/v4/user/tokens/verify",
                      headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30)
        body = r.json()
        record("API token active", body.get("success") is True,
               str(body.get("result", {}).get("status", body.get("errors"))))
    except Exception as exc:
        record("API token active", False, f"{type(exc).__name__}")

    # 2 — plain text -------------------------------------------------------
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, timeout=120,
                       json={"model": MODEL,
                             "messages": [
                                 {"role": "system", "content": "You are terse."},
                                 {"role": "user", "content": "In one sentence, what is a merchant?"}],
                             "temperature": 0.2, "max_tokens": 200})
        body = r.json()
        if r.status_code == 200:
            content = (body["choices"][0]["message"].get("content") or "").strip()
            record("text generation", bool(content),
                   f"usage={body.get('usage')} content={content[:160]!r}")
        else:
            record("text generation", False, _err(r, body))
    except Exception as exc:
        record("text generation", False, f"{type(exc).__name__}")

    # 3 — structured JSON --------------------------------------------------
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, timeout=120,
                       json={"model": MODEL,
                             "messages": [
                                 {"role": "system", "content": "Respond ONLY with valid JSON."},
                                 {"role": "user", "content": 'Give 2 tea-shop product names as {"names": ["..."]}'}],
                             "temperature": 0.1, "max_tokens": 900,
                             "response_format": {"type": "json_object"}})
        body = r.json()
        if r.status_code == 200:
            raw = body["choices"][0]["message"].get("content") or ""
            try:
                parsed = json.loads(raw)
                ok = isinstance(parsed, dict) and "names" in parsed
                record("structured JSON output", ok, f"parsed={str(parsed)[:160]}")
            except Exception as exc:
                record("structured JSON output", False, f"unparseable: {exc} raw={raw[:120]!r}")
        else:
            record("structured JSON output", False, _err(r, body))
    except Exception as exc:
        record("structured JSON output", False, f"{type(exc).__name__}")

    # 4 — tool calling -----------------------------------------------------
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, timeout=120,
                       json={"model": MODEL,
                             "messages": [{"role": "user", "content": "Weather in Mumbai? Use the tool."}],
                             "max_tokens": 500,
                             "tools": [{"type": "function", "function": {
                                 "name": "get_weather",
                                 "description": "Get weather for a city",
                                 "parameters": {"type": "object",
                                                "properties": {"city": {"type": "string"}},
                                                "required": ["city"]}}}],
                             "tool_choice": "auto"})
        body = r.json()
        if r.status_code == 200:
            calls = body["choices"][0]["message"].get("tool_calls")
            record("tool / function calling", bool(calls), f"tool_calls={json.dumps(calls)[:200]}")
        else:
            record("tool / function calling", False, _err(r, body))
    except Exception as exc:
        record("tool / function calling", False, f"{type(exc).__name__}")

    # 5 — streaming --------------------------------------------------------
    try:
        chunks = 0
        text = ""
        with httpx.stream("POST", f"{BASE}/chat/completions", headers=HEADERS, timeout=120,
                          json={"model": MODEL,
                                "messages": [{"role": "user", "content": "Say hi."}],
                                "max_tokens": 50, "stream": True}) as resp:
            if resp.status_code == 200:
                for line in resp.iter_lines():
                    if line.startswith("data:") and line.strip() != "data: [DONE]":
                        chunks += 1
                        try:
                            text += json.loads(line[5:].strip())["choices"][0]["delta"].get("content") or ""
                        except Exception:
                            pass
                record("streaming", chunks > 0, f"chunks={chunks} text={text[:80]!r}")
            else:
                record("streaming", False, f"HTTP {resp.status_code}")
    except Exception as exc:
        record("streaming", False, f"{type(exc).__name__}")

    # summary --------------------------------------------------------------
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        print(
            "\nIf every failure is HTTP 429 with Cloudflare error code 4006\n"
            "(\"you have used up your daily free allocation ... neurons\"), the\n"
            "provider is correctly configured but the account has exhausted its\n"
            "DAILY FREE ALLOCATION. That limit resets at 00:00 UTC. It is not a\n"
            "code defect and it is not an unlimited service."
        )
    return 0 if passed == len(results) else 1


def _err(resp: httpx.Response, body) -> str:
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        codes = ",".join(str(e.get("code")) for e in errors if isinstance(e, dict))
        messages = " | ".join(str(e.get("message")) for e in errors if isinstance(e, dict))
        return f"HTTP {resp.status_code} codes=[{codes}] {messages}"
    return f"HTTP {resp.status_code}"


if __name__ == "__main__":
    raise SystemExit(main())
