"""Offline unit tests for tg.py (no network, no token needed)."""
import glob
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import tg  # noqa: E402

ROOT = Path("/workspace/trenches")
REPORT = ROOT / "report-v2.md"
BLOCKS = sorted(glob.glob(str(ROOT / "runs/blocks_*.md")), key=os.path.getmtime)[-1]
ANCHOR_RE = re.compile(r'<a href="[^"]*">.*?</a>', re.S)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


class Converter(unittest.TestCase):
    def test_escaping(self):
        h = tg.md_to_html("a < b && c > d, R&D <script>x</script>")
        self.assertEqual(h, "a &lt; b &amp;&amp; c &gt; d, R&amp;D &lt;script&gt;x&lt;/script&gt;")

    def test_links_and_href_escaping(self):
        h = tg.inline("[5tCj…pump](https://pump.fun/coin/5tCjpump) and [x](https://x.com/a?b=1&c=\"2\")")
        self.assertIn('<a href="https://pump.fun/coin/5tCjpump">5tCj…pump</a>', h)
        self.assertIn('<a href="https://x.com/a?b=1&amp;c=&quot;2&quot;">x</a>', h)

    def test_link_with_parens_and_brackets(self):
        h = tg.inline('[["quoted"] text](https://en.wikipedia.org/wiki/Foo_(bar))')
        self.assertEqual(h, '<a href="https://en.wikipedia.org/wiki/Foo_(bar)">["quoted"] text</a>')

    def test_unsafe_scheme_not_linked(self):
        h = tg.inline("[click](javascript:alert(1))")
        self.assertNotIn("<a", h)

    def test_bold_italic_code_strike(self):
        h = tg.inline("**bold** *it* `a<b>&` ~~gone~~ **[@x](https://x.com/x)**")
        self.assertEqual(h, '<b>bold</b> <i>it</i> <code>a&lt;b&gt;&amp;</code> <s>gone</s> '
                            '<b><a href="https://x.com/x">@x</a></b>')

    def test_code_is_literal(self):
        self.assertEqual(tg.inline("`**not bold** [a](b)`"), "<code>**not bold** [a](b)</code>")

    def test_underscore_handles_untouched(self):
        h = tg.inline("@_Shadow36 and @mitchiesol_ and 5_000")
        self.assertEqual(h, "@_Shadow36 and @mitchiesol_ and 5_000")

    def test_misnested_emphasis_falls_back(self):
        h = tg.inline("**a *b** c*")
        self.assertTrue(tg.well_formed(h))

    def test_headings_bullets_nested_ordered(self):
        md = "# Title **x**\n\n- one\n  - sub [l](https://dexscreener.com/a)\n- two\n\n1. first\n2. second"
        h = tg.md_to_html(md)
        self.assertIn("<b>Title x</b>", h)
        self.assertIn("• one\n    ◦ sub <a href=\"https://dexscreener.com/a\">l</a>\n• two", h)
        self.assertIn("1. first\n2. second", h)

    def test_tables_flattened_and_comments_removed(self):
        h = tg.md_to_html("<!-- hidden -->\n| a | b |\n|---|---|\n| 1 | **2** |")
        self.assertNotIn("|", h)
        self.assertNotIn("hidden", h)
        self.assertIn("a · b\n1 · <b>2</b>", h)

    def test_code_fence(self):
        h = tg.md_to_html("```\nx < y\n**z**\n```")
        self.assertEqual(h, "<pre>x &lt; y\n**z**</pre>")

    def test_utf16_length(self):
        self.assertEqual(tg.vlen("<b>🚀</b> &amp;"), 4)   # emoji = 2 UTF-16 units


class RealFiles(unittest.TestCase):
    def check(self, path, limit):
        md = Path(path).read_text()
        full = tg.md_to_html(md)
        chunks = tg.convert(md, limit)
        full_anchors = set(ANCHOR_RE.findall(full))
        for c in chunks:
            self.assertLessEqual(tg.vlen(c), limit)
            self.assertTrue(tg.well_formed(c), c)
            for a in ANCHOR_RE.findall(c):
                self.assertIn(a, full_anchors, "an anchor was broken by the splitter")
            last = c.rstrip().split("\n")[-1]
            self.assertFalse(re.fullmatch(r"<b>[^<]*</b>", last) and len(chunks) > 1
                             and c is not chunks[-1] and last in {f"<b>{h}</b>" for h in
                             re.findall(r"^#+\s+(.*)$", md, re.M)}, "heading orphaned at chunk end")
        self.assertEqual(norm(" ".join(tg.visible(c) for c in chunks)), norm(tg.visible(full)))
        self.assertEqual(sum(len(ANCHOR_RE.findall(c)) for c in chunks), len(ANCHOR_RE.findall(full)))
        return chunks, full

    def test_report_default_limit(self):
        chunks, full = self.check(REPORT, 4096)
        for host in ("https://pump.fun/coin/", "https://dexscreener.com/", "https://x.com/"):
            self.assertIn(f'<a href="{host}', full)
        self.assertNotIn("**", full)
        self.assertNotIn("](", full)

    def test_blocks_default_limit(self):
        chunks, full = self.check(BLOCKS, 4096)
        self.assertGreater(len(chunks), 1)

    def test_long_report_splits_cleanly(self):
        long_md = "\n\n".join([REPORT.read_text()] * 6)        # ~30k chars
        tmp = Path(tempfile.mkdtemp()) / "long.md"
        tmp.write_text(long_md)
        chunks, _ = self.check(tmp, 4096)
        self.assertGreaterEqual(len(chunks), 6)

    def test_small_limits_force_hard_splits(self):
        for limit in (1000, 400, 250):
            self.check(REPORT, limit)
            self.check(BLOCKS, limit)

    def test_hard_split_never_cuts_inside_link(self):
        line = "**Bold " + " ".join(f"[word{i} more](https://x.com/u/status/{i})" for i in range(200)) + "**"
        pieces = tg.hard_split(tg.inline(line), 300)
        self.assertGreater(len(pieces), 5)
        for p in pieces:
            self.assertTrue(tg.well_formed(p))
            self.assertLessEqual(tg.vlen(p), 300)
            self.assertTrue(p.startswith("<b>") and p.endswith("</b>"))   # bold reopened/closed


class Sending(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = self.dir / "config.json"
        self.md = self.dir / "r.md"
        self.md.write_text("# Hi\n\nSome **text** [x](https://x.com/a).\n\nNot financial advice.")

    def run_cli(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        env = {"TELEGRAM_BOT_TOKEN": "123456789:AAFakeTokenFakeTokenFakeTokenFake"} if env is None else env
        with mock.patch.dict(os.environ, env, clear=False), redirect_stdout(out), redirect_stderr(err):
            try:
                tg.main(["--config", str(self.cfg), *argv])
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_refuses_when_disabled(self):
        self.cfg.write_text(json.dumps({"chat_id": -100123, "thread_id": None, "enabled": False}))
        with mock.patch.object(tg, "call") as c:
            code, out, err = self.run_cli("send", "--file", str(self.md))
        self.assertEqual(code, 1)
        self.assertIn("disabled", err)
        c.assert_not_called()

    def test_refuses_unapproved_chat(self):
        self.cfg.write_text(json.dumps({"chat_id": -100123, "thread_id": None, "enabled": True}))
        with mock.patch.object(tg, "call") as c:
            code, _, err = self.run_cli("send", "--chat", "-100999", "--file", str(self.md))
        self.assertEqual(code, 1)
        c.assert_not_called()

    def test_require_text(self):
        self.cfg.write_text(json.dumps({"chat_id": -1, "thread_id": None, "enabled": True}))
        self.md.write_text("no disclaimer here")
        with mock.patch.object(tg, "call") as c:
            code, _, err = self.run_cli("send", "--file", str(self.md), "--require", "Not financial advice")
        self.assertEqual(code, 1)
        c.assert_not_called()

    def test_dry_run_needs_no_token_and_sends_nothing(self):
        with mock.patch.object(tg, "call") as c:
            code, out, _ = self.run_cli("send", "--file", str(self.md), "--dry-run",
                                        env={"TELEGRAM_BOT_TOKEN": ""})
        self.assertEqual(code, 0)
        self.assertIn('<a href="https://x.com/a">x</a>', out)
        c.assert_not_called()

    def test_send_with_429_retry_thread_and_ids(self):
        self.cfg.write_text(json.dumps({"chat_id": -100123, "thread_id": 7, "enabled": True}))
        calls = []

        def fake(method, params=None, timeout=30):
            calls.append((method, params))
            if len(calls) == 1:
                raise tg.TgError(429, "Too Many Requests: retry after 2", {"retry_after": 2})
            return {"message_id": 40 + len(calls)}

        with mock.patch.object(tg, "call", side_effect=fake), mock.patch.object(tg.time, "sleep") as sl:
            code, out, _ = self.run_cli("send", "--file", str(self.md))
        self.assertEqual(code, 0)
        res = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(res["message_ids"], [42])
        sl.assert_any_call(3)
        p = calls[-1][1]
        self.assertEqual((p["chat_id"], p["message_thread_id"], p["parse_mode"]), (-100123, 7, "HTML"))
        self.assertEqual(p["link_preview_options"], {"is_disabled": True})

    def test_parse_error_falls_back_to_plain(self):
        self.cfg.write_text(json.dumps({"chat_id": -1, "thread_id": None, "enabled": True}))
        seen = []

        def fake(method, params=None, timeout=30):
            seen.append(dict(params))
            if "parse_mode" in params:
                raise tg.TgError(400, "Bad Request: can't parse entities")
            return {"message_id": 5}

        with mock.patch.object(tg, "call", side_effect=fake), mock.patch.object(tg.time, "sleep"):
            code, out, _ = self.run_cli("send", "--file", str(self.md))
        self.assertEqual(code, 0)
        self.assertNotIn("<b>", seen[-1]["text"])

    def test_migrate_hint_and_partial_ids(self):
        self.cfg.write_text(json.dumps({"chat_id": -5, "thread_id": None, "enabled": True}))
        err_ = tg.TgError(400, "Bad Request: group chat was upgraded to a supergroup chat",
                          {"migrate_to_chat_id": -1001234})
        with mock.patch.object(tg, "call", side_effect=err_), mock.patch.object(tg.time, "sleep"):
            code, out, err = self.run_cli("send", "--file", str(self.md))
        self.assertEqual(code, 2)
        self.assertIn("-1001234", err)

    def test_token_scrubbed(self):
        tok = "123456789:AAFakeTokenFakeTokenFakeTokenFake"
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": tok}):
            self.assertNotIn(tok, tg.scrub(f"https://api.telegram.org/bot{tok}/getMe failed"))
            self.assertNotIn("AAFake", tg.scrub("bot987654321:AAOtherTokenOtherTokenOtherToken1"))

    def test_missing_token_message(self):
        code, _, err = self.run_cli("whoami", env={"TELEGRAM_BOT_TOKEN": ""})
        self.assertEqual(code, 1)
        self.assertIn("not set", err)

    def test_config_command(self):
        code, out, _ = self.run_cli("config", "--chat", "-1001", "--thread", "3", "--enable")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.cfg.read_text()), {"chat_id": -1001, "thread_id": 3, "enabled": True})


class FanOutTest(unittest.TestCase):
    def test_send_goes_to_primary_and_extras(self):
        import tempfile, io, contextlib
        from unittest import mock
        d = Path(tempfile.mkdtemp())
        cfgp = d / "c.json"; cfgp.write_text(json.dumps({"chat_id": -100, "thread_id": None, "enabled": True,
                                                         "extra_chat_ids": [-200]}))
        md = d / "r.md"; md.write_text("hello\n\nNot financial advice.")
        sent = []
        def fake(method, params=None, **k):
            sent.append(params["chat_id"]); return {"message_id": len(sent)}
        out = io.StringIO()
        with mock.patch.object(tg, "call_with_retry", fake), mock.patch.object(tg.time, "sleep"), \
                contextlib.redirect_stdout(out):
            tg.main(["--config", str(cfgp), "send", "--file", str(md), "--require", "Not financial advice"])
        self.assertEqual([str(c) for c in sent], ["-100", "-200"])
        last = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertTrue(last["ok"]); self.assertEqual(len(last["results"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
