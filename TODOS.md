# TODOs

- [ ] **Security: audit `aria.py` `shell=True` calls (~lines 313, 343).** Same bug class as the model-reachable shell RCE fixed in `app.py` (commit 9f4036f) — arbitrary shell execution — but in the standalone CLI, which has its own model loop and was out of scope for that fix. Not yet audited or patched.
