"""Offline tests for claude-usage: parsing, percentages, reset times, profiles, cache.

Run with python3 -I test_core.py. Fixtures are synthetic; no Keychain, network or real config.
"""

import base64
import importlib.machinery
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock


def load_script(name):
    path = str(Path(__file__).resolve().parent / name)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cu = load_script("claude-usage")


def iso_in(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class ResetTimeTests(unittest.TestCase):
    def test_empty_and_garbage(self):
        self.assertEqual(cu.humanize_reset(None), "")
        self.assertEqual(cu.humanize_reset(""), "")
        self.assertEqual(cu.humanize_reset("not-a-date"), "not-a-date")

    def test_past_is_now(self):
        self.assertTrue(cu.humanize_reset(iso_in(-60)).endswith("(now)"))

    def test_minutes_hours_days(self):
        self.assertTrue(cu.humanize_reset(iso_in(30 * 60 + 5)).endswith("(in 30m)"))
        self.assertTrue(cu.humanize_reset(iso_in(2 * 3600 + 15 * 60 + 5)).endswith("(in 2h15m)"))
        self.assertTrue(cu.humanize_reset(iso_in(3 * 86400 + 4 * 3600 + 60)).endswith("(in 3d4h)"))

    def test_z_suffix_and_naive_are_utc(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)
        z = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        naive = future.strftime("%Y-%m-%dT%H:%M:%S")
        self.assertTrue(cu.humanize_reset(z).endswith("(in 1h29m)") or cu.humanize_reset(z).endswith("(in 1h30m)"))
        self.assertEqual(cu.humanize_reset(z), cu.humanize_reset(naive))

    def test_humanize_age(self):
        self.assertEqual(cu.humanize_age(None), "unknown age")
        self.assertEqual(cu.humanize_age(time.time() - 30), "30s ago")
        self.assertEqual(cu.humanize_age(time.time() - 90), "1m ago")
        self.assertEqual(cu.humanize_age(time.time() - 3 * 3600 - 120), "3h02m ago")
        self.assertEqual(cu.humanize_age(time.time() - 2 * 86400 - 5), "2d ago")


class PercentTests(unittest.TestCase):
    def test_percent_label(self):
        self.assertEqual(cu.percent_label(0), "0%")
        self.assertEqual(cu.percent_label(100), "100%")
        self.assertEqual(cu.percent_label(99.96), "100%")
        self.assertEqual(cu.percent_label(0.1), "0.1%")
        self.assertEqual(cu.percent_label(12.34), "12.3%")

    def test_fmt_window_remaining(self):
        line = cu.fmt_window({"utilization": 25.0, "resets_at": iso_in(3600 * 2 + 60)})
        self.assertIn(" 75.0% left", line)
        self.assertIn("(in 2h00m)", line)

    def test_fmt_window_alternative_reset_keys(self):
        for key in ("resets_at", "reset_at", "resetsAt"):
            line = cu.fmt_window({"utilization": 10, key: iso_in(1800 + 5)})
            self.assertIn("(in 30m)", line, key)

    def test_fmt_window_no_data(self):
        self.assertIsNone(cu.fmt_window({}))
        self.assertIsNone(cu.fmt_window({"utilization": None}))
        self.assertIsNone(cu.fmt_window({"utilization": "50"}))

    def test_fmt_window_zero_and_full(self):
        self.assertIn("100.0% left", cu.fmt_window({"utilization": 0}))
        self.assertIn("  0.0% left", cu.fmt_window({"utilization": 100}))

    def test_fmt_window_over_100_stays_in_bar_range(self):
        line = cu.fmt_window({"utilization": 120})
        self.assertIn("░" * 20, line)

    def test_fmt_extra_usage_without_limit(self):
        out = cu.fmt_extra_usage({"is_enabled": True, "used_credits": 250, "currency": "USD"})
        self.assertIn("2.50/∞ USD", out)

    def test_fmt_extra_usage_utilization(self):
        out = cu.fmt_extra_usage({"is_enabled": True, "used_credits": 5000, "monthly_limit": 10000,
                                  "currency": "USD", "utilization": 50.0})
        self.assertIn("50.00/100.00 USD", out)
        self.assertIn("50% used", out)

    def test_bar_clamps(self):
        self.assertEqual(cu.bar(-5).count("█"), 0)
        self.assertEqual(cu.bar(500).count("█"), 20)

    def test_render_windows(self):
        data = {
            "five_hour": {"utilization": 40.0, "resets_at": iso_in(3600)},
            "seven_day": {"utilization": None, "resets_at": None},
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": False},
            "novel_window": {"utilization": 90.0},
        }
        with mock.patch("builtins.print") as p:
            cu.render_windows(data)
        out = "\n".join(c.args[0] for c in p.call_args_list)
        self.assertIn("5h window", out)
        self.assertNotIn("7d window", out)
        self.assertIn("overage", out)
        self.assertIn("novel_window", out)
        with mock.patch("builtins.print") as p:
            cu.render_windows(data, show_all=True)
        out = "\n".join(c.args[0] for c in p.call_args_list)
        self.assertIn("7d window", out)
        self.assertIn("+ no data: seven_day_opus", out)


class PlanTests(unittest.TestCase):
    def test_tier_suffix_fallbacks(self):
        self.assertEqual(cu.plan_label({"rateLimitTier": "custom_max_20x"})[0], "Max 20x")
        self.assertEqual(cu.plan_label({"rateLimitTier": "custom_max_5x"})[0], "Max 5x")
        self.assertEqual(cu.plan_label({"subscriptionType": "free"})[0], "Free")

    def test_snake_case_keys(self):
        label, sub, tier = cu.plan_label({"subscription_type": "pro", "rate_limit_tier": "default_claude_ai"})
        self.assertEqual((label, sub, tier), ("Pro", "pro", "default_claude_ai"))

    def test_empty_credential(self):
        self.assertEqual(cu.plan_label({}), ("?", "?", "?"))

    def test_failure_reason(self):
        self.assertEqual(cu.failure_reason(0, "network error: x"), "network error: x")
        self.assertEqual(cu.failure_reason(500, {"error": {"message": "boom"}}), "HTTP 500: boom")
        self.assertEqual(cu.failure_reason(503, "<html>"), "HTTP 503")
        self.assertEqual(cu.failure_reason(500, {"error": "plain"}), "HTTP 500")


class CredentialParsingTests(unittest.TestCase):
    def test_parse_oauth(self):
        self.assertIsNone(cu.parse_oauth("[]"))
        self.assertIsNone(cu.parse_oauth('{"other": 1}'))
        self.assertIsNone(cu.parse_oauth('{"claudeAiOauth": "x"}'))
        self.assertEqual(cu.parse_oauth('{"claudeAiOauth": {"accessToken": "a"}}'), {"accessToken": "a"})

    def test_token_expired_snake_case_and_skew(self):
        self.assertTrue(cu.token_expired({"expires_at": (time.time() - 5) * 1000}))
        # inside the 60s skew counts as expired
        self.assertTrue(cu.token_expired({"expiresAt": (time.time() + 30) * 1000}))
        self.assertFalse(cu.token_expired({"expiresAt": "soon"}))

    def test_account_id_from_jwt(self):
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "u-123"}).encode()).decode().rstrip("=")
        self.assertEqual(cu.account_id({"accessToken": "h.%s.s" % payload}), "id:u-123")

    def test_account_id_opaque_token_hashes(self):
        a = cu.account_id({"accessToken": "opaque-a"})
        b = cu.account_id({"access_token": "opaque-b"})
        self.assertTrue(a.startswith("tok:") and b.startswith("tok:") and a != b)
        self.assertNotIn("opaque-a", a)
        self.assertIsNone(cu.account_id({}))

    def test_account_id_bad_jwt_payload_falls_back(self):
        self.assertTrue(cu.account_id({"accessToken": "a.!!!.c"}).startswith("tok:"))


class ProfileTests(unittest.TestCase):
    def test_label_for(self):
        self.assertEqual(cu.label_for("/home/u/.claude"), "default")
        self.assertEqual(cu.label_for("/home/u/.claude/"), "default")
        self.assertEqual(cu.label_for("/home/u/.claude-work"), "work")
        self.assertEqual(cu.label_for("/home/u/.other"), "other")
        self.assertEqual(cu.label_for("/home/u/plain"), "plain")

    def test_discover_profiles_order_and_dedup(self):
        with tempfile.TemporaryDirectory() as home:
            for d in (".claude", ".claude-b", ".claude-a", ".claude-file-not-dir"):
                if d == ".claude-file-not-dir":
                    Path(home, d).write_text("x")
                else:
                    Path(home, d).mkdir()
            env = {"CLAUDE_CONFIG_DIR": os.path.join(home, ".claude-b")}
            with mock.patch.object(cu, "HOME", home), mock.patch.dict(os.environ, env, clear=True):
                found = cu.discover_profiles()
            self.assertEqual([l for l, _ in found], ["b", "a", "default"])
            self.assertEqual(len({d for _, d in found}), 3)

    def test_discover_profiles_env_outside_home_and_missing(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as ext:
            Path(home, ".claude").mkdir()
            env = {"CLAUDE_CONFIG_DIR": ext}
            with mock.patch.object(cu, "HOME", home), mock.patch.dict(os.environ, env, clear=True):
                found = cu.discover_profiles()
            self.assertEqual(found[0][1], os.path.abspath(ext))
            env = {"CLAUDE_CONFIG_DIR": os.path.join(home, "nope")}
            with mock.patch.object(cu, "HOME", home), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual([l for l, _ in cu.discover_profiles()], ["default"])

    def test_load_credentials_from_file(self):
        with tempfile.TemporaryDirectory() as cdir:
            Path(cdir, ".credentials.json").write_text(json.dumps(
                {"claudeAiOauth": {"accessToken": "synthetic", "subscriptionType": "pro"}}))
            oauth, source, store = cu.load_credentials(cdir)
        self.assertEqual(oauth["accessToken"], "synthetic")
        self.assertEqual(store["kind"], "file")
        self.assertIn(".credentials.json", source)

    def test_load_credentials_not_found(self):
        with tempfile.TemporaryDirectory() as cdir, mock.patch.object(cu, "read_keychain", return_value=None):
            oauth, reason, store = cu.load_credentials(cdir)
        self.assertIsNone(oauth)
        self.assertIsNone(store)
        self.assertIn("not found", reason)

    def test_account_uuid_for(self):
        with tempfile.TemporaryDirectory() as home:
            named = Path(home, ".claude-x")
            named.mkdir()
            (named / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-x"}}))
            default = Path(home, ".claude")
            default.mkdir()
            Path(home, ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-d"}}))
            self.assertEqual(cu.account_uuid_for(str(named)), "uuid-x")
            self.assertEqual(cu.account_uuid_for(str(default)), "uuid-d")
            Path(home, ".claude.json").write_text("{broken")
            self.assertIsNone(cu.account_uuid_for(str(default)))

    def test_group_key_falls_back_to_dir(self):
        self.assertEqual(cu.group_key({"config_dir": "/a/b"}), "cfg:/a/b")


class CacheTests(unittest.TestCase):
    def test_roundtrip_and_miss(self):
        with tempfile.TemporaryDirectory() as base, mock.patch.dict(os.environ, {"XDG_CACHE_HOME": base}):
            self.assertEqual(cu.read_cache("/x/.claude"), (None, None, None))
            cu.write_cache("/x/.claude", {"five_hour": {"utilization": 1}}, "tier")
            data, ts, tier = cu.read_cache("/x/.claude")
            self.assertEqual(data, {"five_hour": {"utilization": 1}})
            self.assertEqual(tier, "tier")
            self.assertLess(time.time() - ts, 5)
            self.assertEqual(cu.read_cache("/y/.claude"), (None, None, None))
            Path(cu.cache_file("/x/.claude")).write_text("{broken")
            self.assertEqual(cu.read_cache("/x/.claude"), (None, None, None))

    def test_cache_dir_default_home(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(cu, "HOME", "/h"):
            self.assertEqual(cu.cache_dir(), "/h/.cache/claude-usage")

    def test_fingerprint_variants(self):
        self.assertIsNone(cu.fingerprint(None))
        self.assertIsNone(cu.fingerprint({"a": {"utilization": 1}}))
        a = cu.fingerprint({"five_hour": {"reset_at": "t1"}})
        self.assertEqual(a, cu.fingerprint({"five_hour": {"resetsAt": "t1"}}))
        self.assertNotEqual(a, cu.fingerprint({"seven_day": {"reset_at": "t1"}}))


def transcript_line(ts, model="claude-sonnet-4-6", mid="m1", rid="r1", usage=None, typ="assistant", **extra):
    obj = {"type": typ, "timestamp": ts, "requestId": rid,
           "message": {"id": mid, "model": model,
                       "usage": usage if usage is not None else {"input_tokens": 100, "output_tokens": 50}}}
    obj.update(extra)
    return json.dumps(obj)


def now_iso(delta_hours=0):
    return (datetime.now(timezone.utc) - timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TranscriptTests(unittest.TestCase):
    def write(self, tmp, name, lines):
        p = Path(tmp, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    def test_parse_transcript_filters(self):
        cutoff = time.time() - 86400
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "a.jsonl", [
                transcript_line(now_iso()),
                transcript_line(now_iso(), typ="user"),
                transcript_line(now_iso(), model="<synthetic>"),
                transcript_line(now_iso(), usage={"input_tokens": 0, "output_tokens": 0}),
                transcript_line(now_iso(48)),                       # before cutoff
                transcript_line("garbage"),                         # bad timestamp
                "{not json but has \"assistant\" and \"usage\"",    # bad json
                transcript_line(now_iso(), usage="oops"),
                transcript_line(now_iso(), mid=None, rid=None, costUSD=0.5),
            ])
            out = cu.parse_transcript(path, cutoff)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][3], 150)
        self.assertTrue(out[0][0])      # uid present
        self.assertIsNone(out[1][0])    # no ids -> uid None
        self.assertEqual(out[1][4], 0.5)

    def test_parse_transcript_missing_file(self):
        self.assertEqual(cu.parse_transcript("/nonexistent/x.jsonl", 0), [])

    def test_local_usage_dedupes_across_files(self):
        with tempfile.TemporaryDirectory() as cdir, tempfile.TemporaryDirectory() as cache:
            line = transcript_line(now_iso(), mid="dup", rid="dup")
            self.write(cdir, "projects/p1/a.jsonl", [line])
            self.write(cdir, "projects/p2/b.jsonl", [line, transcript_line(now_iso(), mid="o", rid="o")])
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}):
                loc = cu.local_usage(cdir)
        self.assertEqual(sum(loc["day_tokens"].values()), 300)
        self.assertEqual(loc["model_tokens"], {"claude-sonnet-4-6": 300})

    def test_local_usage_no_projects_dir_and_empty(self):
        with tempfile.TemporaryDirectory() as cdir, tempfile.TemporaryDirectory() as cache:
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}):
                self.assertIsNone(cu.local_usage(cdir))
                Path(cdir, "projects").mkdir()
                self.assertIsNone(cu.local_usage(cdir))

    def test_local_usage_cache_reparses_changed_file(self):
        with tempfile.TemporaryDirectory() as cdir, tempfile.TemporaryDirectory() as cache:
            path = self.write(cdir, "projects/p/a.jsonl", [transcript_line(now_iso(), mid="1", rid="1")])
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}):
                first = cu.local_usage(cdir)
                with mock.patch.object(cu, "parse_transcript", side_effect=AssertionError("cached")):
                    again = cu.local_usage(cdir)
                self.assertEqual(first, again)
                with open(path, "a") as fh:
                    fh.write(transcript_line(now_iso(), mid="2", rid="2") + "\n")
                third = cu.local_usage(cdir)
        self.assertEqual(sum(third["day_tokens"].values()), 300)

    def test_merge_local_handles_none(self):
        a = {"day_tokens": {"d": 1}, "day_cost": {"d": 1.0}, "model_tokens": {"m": 1}}
        self.assertIs(cu.merge_local(a, None), a)
        merged = cu.merge_local(None, a)
        self.assertEqual(merged, a)
        self.assertIsNot(merged["day_tokens"], a["day_tokens"])

    def test_entry_cost_5m_and_1h_cache_write(self):
        # 1M 5m cache write = 1.25x input; 1M 1h = 2x input (sonnet input = $3)
        cost = cu.entry_cost("claude-sonnet-4-6", {"cache_creation": {
            "ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}})
        self.assertAlmostEqual(cost, 3.0 * 1.25 + 3.0 * 2.0)

    def test_entry_cost_legacy_cache_creation_total(self):
        cost = cu.entry_cost("claude-sonnet-4-6", {"cache_creation_input_tokens": 1_000_000})
        self.assertAlmostEqual(cost, 3.0 * 1.25)

    def test_entry_cost_unknown_model_is_zero(self):
        self.assertEqual(cu.entry_cost("gpt-4o", {"input_tokens": 1_000_000}), 0.0)


class FormatTests(unittest.TestCase):
    def test_fmt_tokens_edges(self):
        self.assertEqual(cu.fmt_tokens(0), "0")
        self.assertEqual(cu.fmt_tokens(999), "999")
        self.assertEqual(cu.fmt_tokens(1000), "1K")
        self.assertEqual(cu.fmt_tokens(12_345), "12K")
        self.assertEqual(cu.fmt_tokens(1_234_567_890), "1.2B")
        self.assertEqual(cu.fmt_tokens(-1500), "-1.5K")

    def test_shorten_model(self):
        self.assertEqual(cu.shorten_model(None), "")
        self.assertEqual(cu.shorten_model("custom-model"), "custom-model")
        self.assertEqual(cu.shorten_model("claude-opus-4-7"), "opus-4-7")

    def test_sparkline_empty(self):
        self.assertEqual(cu.sparkline([]), "")


if __name__ == "__main__":
    unittest.main()
