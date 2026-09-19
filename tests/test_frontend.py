"""Frontend regression tests: JS syntax + marker presence + no secrets.

Uses esprima (pip dev dependency) to syntax-check every shipped JS
file — a broken script blank-screens the whole terminal, so this is
load-bearing. No network, no browser required.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "terminal", "js")
JS_FILES = ["format.js", "api.js", "charts.js", "analysis.js", "pages.js", "app.js"]

try:
    import esprima

    HAS_ESPRIMA = True
except ImportError:
    HAS_ESPRIMA = False


class TestJsSyntax(unittest.TestCase):
    def test_all_shipped_js_parses(self):
        if not HAS_ESPRIMA:
            self.skipTest("esprima not installed")
        for name in JS_FILES:
            path = os.path.join(JS_DIR, name)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            try:
                esprima.parseScript(src)
            except Exception as exc:
                self.fail(f"{name} has a JS syntax error: {exc}")

    def test_no_template_literals_or_arrow_deps(self):
        # codebase standard: ES5-style for maximum engine compatibility.
        # strip comments + strings first so prose can't false-positive.
        for name in JS_FILES:
            path = os.path.join(JS_DIR, name)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
            code = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", code)
            code = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', code)
            self.assertNotIn("`", code, f"{name} must not use template literals")
            self.assertNotRegex(code, r"=>", f"{name} must not use arrow functions")


class TestFrontendHygiene(unittest.TestCase):
    def test_no_secrets_in_frontend(self):
        for name in JS_FILES + ["../index.html", "../styles.css"]:
            path = os.path.normpath(os.path.join(JS_DIR, name))
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            for token in ("API_KEY=", "apikey=", "sk-live", "BEGIN PRIVATE KEY"):
                self.assertNotIn(token, src, f"secret pattern in {name}")

    def test_no_hardcoded_financial_values(self):
        # spot-check: company pages must not embed literal prices
        path = os.path.join(JS_DIR, "pages.js")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("187.29", "1245.5", "490.30"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
