"""Security regression tests for aria.py's tool-execution hardening.

Covers the aria.py CSO-audit fixes (follow-up to app.py commit 9f4036f):
  - open_app: allowlist only, list-form, no shell, no raw fallback
  - open_url: http/https only, browser allowlist, list-form, no shell
  - dispatch: arg-shape validation before execution
  - static: no shell=True anywhere in aria.py

Run:  python3 -m unittest tests.test_aria_security -v   (from repo root)

aria.py runs heavy side effects at import (PortAudio, pygame.mixer.init,
Whisper, OpenWakeWord, edge-tts), so those modules are stubbed in sys.modules
before import to keep the test deterministic and headless-safe.

NOTE: sys.platform is 'linux' here, so run_open_app/run_open_url exercise the
Linux branches. The Windows shutil.which resolution path is logic-verified but
not runtime-tested from this environment (flagged as needs-manual-verification
on Windows).
"""

import os
import sys
import unittest
from unittest import mock

# ── Stub heavy/hardware modules BEFORE importing aria ────────────────────────
for _name in ["pyaudio", "pygame", "faster_whisper",
              "openwakeword", "openwakeword.model", "edge_tts"]:
    sys.modules.setdefault(_name, mock.MagicMock())
# aria does `from openwakeword.model import Model`
sys.modules["openwakeword"].model = sys.modules["openwakeword.model"]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_devnull = open(os.devnull, "w")
_real_stderr, sys.stderr = sys.stderr, _devnull
import aria  # noqa: E402
sys.stderr = _real_stderr

ARIA_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aria.py")


class TestOpenAppAllowlist(unittest.TestCase):
    def test_allowlisted_app_launches_listform_no_shell(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            out = aria.run_open_app("chrome")
        self.assertEqual(spy.call_count, 1, out)
        args, kwargs = spy.call_args
        self.assertIsInstance(args[0], list, "Popen must be called list-form")
        self.assertNotIn("shell", kwargs)          # never shell=True
        self.assertTrue(out.startswith("Launching"))

    def test_second_allowlisted_app(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            aria.run_open_app("gimp")
        self.assertEqual(spy.call_count, 1)
        self.assertIsInstance(spy.call_args.args[0], list)

    def test_unknown_app_not_executed(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            out = aria.run_open_app("totally-unknown-app")
        self.assertEqual(spy.call_count, 0)
        self.assertIn("not recognized", out)

    def test_injection_shaped_names_not_executed(self):
        for payload in ("x & calc.exe", "chrome; rm -rf ~", "$(rm -rf ~)", "a | nc evil 1"):
            with mock.patch.object(aria.subprocess, "Popen") as spy:
                out = aria.run_open_app(payload)
            self.assertEqual(spy.call_count, 0, f"payload executed: {payload!r}")
            self.assertIn("not recognized", out)


class TestOpenUrlScheme(unittest.TestCase):
    def test_default_valid_https_listform(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            out = aria.run_open_url("https://example.com")
        self.assertEqual(spy.call_count, 1, out)
        self.assertEqual(spy.call_args.args[0], ["xdg-open", "https://example.com"])
        self.assertNotIn("shell", spy.call_args.kwargs)

    def test_bare_host_gets_https(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            aria.run_open_url("youtube.com")
        self.assertEqual(spy.call_args.args[0], ["xdg-open", "https://youtube.com"])

    def test_file_scheme_blocked(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            out = aria.run_open_url("file:///etc/passwd")
        self.assertEqual(spy.call_count, 0)
        self.assertTrue(out.startswith("Blocked:"))

    def test_javascript_and_data_schemes_blocked(self):
        for bad in ("javascript:alert(1)", "data:text/html,<script>x</script>", "ftp://x/y"):
            with mock.patch.object(aria.subprocess, "Popen") as spy:
                out = aria.run_open_url(bad)
            self.assertEqual(spy.call_count, 0, bad)
            self.assertTrue(out.startswith("Blocked:"), bad)

    def test_injection_url_stays_single_argv_no_second_process(self):
        # Payload keeps a valid https scheme so it passes the filter; the '&'
        # must NOT split into a second command (no shell). Unknown browser 'foo'
        # falls back to the safe default opener.
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            aria.run_open_url("https://x.com & calc.exe", browser="foo")
        self.assertEqual(spy.call_count, 1, "injection spawned an extra process")
        self.assertEqual(spy.call_args.args[0], ["xdg-open", "https://x.com & calc.exe"])
        self.assertNotIn("shell", spy.call_args.kwargs)

    def test_valid_named_browser_listform(self):
        with mock.patch.object(aria.subprocess, "Popen") as spy:
            aria.run_open_url("https://x.com", browser="firefox")
        self.assertEqual(spy.call_count, 1)
        args = spy.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertEqual(args[-1], "https://x.com")
        self.assertNotIn("shell", spy.call_args.kwargs)


class TestArgShapeValidation(unittest.TestCase):
    def test_valid(self):
        ok, _ = aria._validate_tool_args("open_app", {"app_name": "chrome"})
        self.assertTrue(ok)

    def test_non_dict_rejected(self):
        ok, _ = aria._validate_tool_args("open_app", "chrome")
        self.assertFalse(ok)

    def test_extra_key_rejected(self):
        ok, _ = aria._validate_tool_args("open_url", {"url": "https://x", "evil": "y"})
        self.assertFalse(ok)

    def test_non_string_value_rejected(self):
        ok, _ = aria._validate_tool_args("open_app", {"app_name": 123})
        self.assertFalse(ok)

    def test_missing_required_rejected(self):
        ok, _ = aria._validate_tool_args("open_url", {"browser": "firefox"})
        self.assertFalse(ok)

    def test_unknown_tool_rejected(self):
        ok, _ = aria._validate_tool_args("run_shell", {"cmd": "x"})
        self.assertFalse(ok)


class TestDispatchRejectsMalformed(unittest.TestCase):
    def _reply(self, content):
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock()]
        resp.choices[0].message.content = content
        return resp

    def setUp(self):
        aria.conversation_history.clear()

    def test_malformed_tool_call_not_executed(self):
        # Non-string arg value → validation rejects → tool never runs.
        reply = self._reply('{"tool":"open_app","args":{"app_name":123}}')
        with mock.patch.object(aria.client.chat.completions, "create", return_value=reply), \
             mock.patch.object(aria.subprocess, "Popen") as spy:
            out = aria.ask_claude("open the thing")
        self.assertEqual(spy.call_count, 0)
        self.assertIn("Rejected", out)

    def test_valid_tool_call_still_executes(self):
        reply = self._reply('{"tool":"open_app","args":{"app_name":"chrome"}}')
        with mock.patch.object(aria.client.chat.completions, "create", return_value=reply), \
             mock.patch.object(aria.subprocess, "Popen") as spy:
            aria.ask_claude("open chrome")
        self.assertEqual(spy.call_count, 1)


class TestNoShellTrueInSource(unittest.TestCase):
    def test_no_shell_true_anywhere(self):
        with open(ARIA_SRC, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("shell = True", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
