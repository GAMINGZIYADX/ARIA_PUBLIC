# Security Policy

ARIA runs locally with your user's privileges and has access to the microphone,
the filesystem, and shell execution. A bug that lets untrusted input reach the
tool-execution path is effectively remote code execution on the user's machine.
Security reports are taken seriously here.

---

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately by either:

- **Email:** znoucair@gmail.com
- **GitHub:** [Report a vulnerability](https://github.com/GAMINGZIYADX/ARIA_PUBLIC/security/advisories/new)
  via a private security advisory

Helpful things to include:

- What the issue is and roughly how severe you think it is
- Steps to reproduce, or a proof-of-concept
- The affected file and function, if you have it
- Your OS, Python version, and which model you were running

You do not need a polished writeup. A rough report of something real is far more
useful than a perfect report that never gets sent.

---

## What to expect

ARIA is maintained by one person, so responses are best-effort rather than
contractual:

- **Acknowledgement:** typically within a few days
- **Assessment:** an initial view on validity and severity once reproduced
- **Fix:** critical issues are prioritized over everything else in the project

You will be credited in the release notes and the advisory unless you would
rather stay anonymous — just say so.

---

## Supported versions

`main` is the supported branch and is where fixes land. There is no backporting
to older tags — if you are running an older checkout, update to current `main`
or the latest release.

---

## Scope

Reports that are especially valuable, in rough priority order:

- **Prompt injection reaching tool execution** — any path where model output or
  untrusted content (a web page, a file, a transcript) can cause a tool to run
  with attacker-controlled arguments
- **Shell or command injection** in tool dispatch or command construction
- **Path traversal or arbitrary writes** escaping the intended workspace in the
  file-writing tools
- **Allowlist escapes** in `open_app` or `open_url` (app allowlist, browser
  allowlist, URL scheme handling)
- **Authentication bypass** on the Flask UI or its API endpoints
- **Cross-origin attacks** reaching the local server — CORS is restricted to
  `localhost:5000` and the app binds `127.0.0.1`, so anything defeating that
  (DNS rebinding, a CORS or CSRF gap) is in scope
- **Secret leakage** — `.env` values, API keys, or credentials reaching logs,
  the model's context, or the web UI

---

## Out of scope

- **The default bootstrap password.** On first launch ARIA writes a `.env`
  containing `ARIA_PASSWORD=aria` and prints a warning telling you to change it.
  This is documented, local-only, and user-changeable. If you can show it being
  exploited from off-machine, that *is* in scope — report it.
- **Attacks requiring an already-compromised local account.** ARIA deliberately
  runs with your user's privileges; it is not a sandbox and does not claim to be
  a privilege boundary against code already running as you.
- **Upstream model behavior.** A local LLM saying something wrong or refusing a
  request is not a vulnerability here. A model output that causes ARIA to *do*
  something dangerous is — report that.
- **Vulnerabilities in dependencies** (Ollama, Flask, faster-whisper, PyQt6,
  etc.) with no ARIA-specific exploit path. Report those upstream; if ARIA's
  usage makes an upstream bug exploitable, that is in scope.
- **Local denial of service** — you already control the machine.
- **Missing hardening headers or scanner output** with no demonstrated impact.

---

## Disclosure

Please give a reasonable window to ship a fix before publishing — 90 days is a
fine default, and shorter is negotiable if a fix lands quickly or the issue is
already being exploited. Coordinated disclosure is preferred, and credit is
given by default.

---

## For contributors

If your change touches tool dispatch, command construction, file writes, or any
model-controlled input, run the security regression suite before opening a PR:

```bash
python3 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution process.
