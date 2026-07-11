# TODOs

- [x] **Security: audit + fix `aria.py` `shell=True` calls.** Audited and hardened: removed both `shell=True` command-injection sinks (open_app, open_url), dropped the raw-string APP_MAP fallback for an allowlist, restricted open_url to http/https, and added arg-shape validation at the tool dispatch. Follow-up to `app.py` commit 9f4036f. Tests in `tests/test_aria_security.py`. Windows `shutil.which` app resolution is logic-only (not runtime-tested from Linux) — verify on Windows.
