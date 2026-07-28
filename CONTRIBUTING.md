# Contributing to ARIA

ARIA is an open-source project originally created and maintained by **Ziyad Noucair**.
Contributions are welcome — bug reports, fixes, features, and documentation alike.

Please also read the [Code of Conduct](CODE_OF_CONDUCT.md), which applies to all
issues, pull requests, and discussions.

---

## What's welcome

- Bug fixes and stability improvements
- STT / TTS engine improvements
- New tool integrations (apps, browser, terminal, automation)
- Performance optimizations for local inference
- Documentation improvements and translations

## What's out of scope

- Modifications intended for surveillance or tracking individuals without consent
- Using ARIA as a base for spyware, keyloggers, or malicious automation
- Removing or bypassing the offline-first principle (no forced cloud dependency)

---

## Reporting security issues

**Do not open a public issue for security vulnerabilities.**

ARIA executes tools and shell commands on the user's machine, so security bugs
here can be serious. Report them privately to **znoucair@gmail.com** or via a
[GitHub security advisory](https://github.com/GAMINGZIYADX/ARIA_PUBLIC/security/advisories/new).

See [SECURITY.md](SECURITY.md) for scope, what to include, and disclosure
expectations.

---

## Development setup

**Prerequisites:** Python 3.11 or 3.12, [Ollama](https://ollama.com) installed and running.
A CUDA-capable GPU is recommended (developed and tested on RTX series), but ARIA
falls back to CPU.

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/ARIA_PUBLIC.git
cd ARIA_PUBLIC

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Pull a model
ollama pull qwen2.5:7b

# 5. Run the configuration wizard — this generates your .env
python setup.py

# 6. Launch
python app.py
```

ARIA is then available at **http://localhost:5000**.

> `setup.py` creates `.env` for you. Use `.env.example` only as a reference for
> what each variable does — you do not need to copy it manually.

**Optional — native desktop window.** `launch.py` wraps the web UI in a native
window instead of a browser tab. It needs extra packages that ARIA does not
otherwise require:

```bash
pip install -r requirements-desktop.txt
```

On Linux the rendering backend (GTK/WebKit2) comes from system packages rather
than pip — see the comments in `requirements-desktop.txt`. Without pywebview
installed, `launch.py` falls back to serving in the browser.

---

## Before opening a pull request

Run the test suite, especially the security tests:

```bash
# from the repo root
python3 -m unittest discover -s tests -v
```

The suite uses the stdlib `unittest` runner — there is no pytest dependency, and
heavy hardware modules (PortAudio, pygame, Whisper, OpenWakeWord) are stubbed so
it runs headless.

ARIA's tool-execution path has been hardened against shell injection and prompt
injection. If your change touches tool dispatch, command construction, or any
model-controlled input, `tests/test_aria_security.py` and
`tests/test_security_patch.py` must still pass — and new attack surface should
come with new tests.

---

## Pull request process

1. Create a branch — `feature/your-feature-name` or `fix/issue-description`
2. Keep changes focused; one logical change per PR
3. Match the surrounding code style
4. Write commit messages in [Conventional Commits](https://www.conventionalcommits.org)
   form, as used throughout this repo:

   ```
   fix(security): close shell-injection RCE in tool execution
   feat(tts): add Piper voice selection
   docs: clarify Windows Whisper cache setup
   ```

5. Open a PR describing **what** changed and **why**

For large or architectural changes, open an issue to discuss before writing code —
it saves everyone time if the approach needs to change.

---

## Licensing of contributions

ARIA is licensed under the [Apache License 2.0](LICENSE).

Contributions are accepted under that same license. This is not a separate
agreement you need to sign — Apache 2.0 §5 states that any contribution you
intentionally submit for inclusion in the work is licensed under its terms
unless you explicitly say otherwise. That section also covers the patent grant.

Two things are on you as a contributor:

1. **You own what you submit.** Your contribution must be your own original work.
   Do not submit code copied from proprietary sources or from projects under
   licenses incompatible with Apache 2.0. If you are contributing work created
   for an employer, make sure you have the right to license it.

2. **Attribution stays intact.** Apache 2.0 requires that the copyright notice
   and the [NOTICE](NOTICE) file be preserved in redistributions, and that
   significant modifications be stated. Do not remove them.

You retain copyright in your contribution.
