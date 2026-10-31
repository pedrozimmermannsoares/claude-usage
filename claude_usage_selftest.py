# Offline checks for claude-usage (no Keychain / no network / no personal data).
# `claude-usage --selftest` executes this file in its own globals, so the names
# below resolve to claude-usage's functions.


def run_selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))

    cands = candidate_services("/tmp/example-config")
    check("service name = prefix + 8 hex",
          any(re.match(r"^Claude Code-credentials-[0-9a-f]{8}$", c) for c in cands))
    check("default (plain) service present", KEYCHAIN_PREFIX in cands)

    check("plan Max 20x", plan_label({"rateLimitTier": "default_claude_max_20x"})[0] == "Max 20x")
    check("plan Max 5x", plan_label({"rateLimitTier": "default_claude_max_5x"})[0] == "Max 5x")
    check("plan Pro", plan_label({"subscriptionType": "pro", "rateLimitTier": "default_claude_ai"})[0] == "Pro")
    check("plan unknown tier falls back to sub", plan_label({"subscriptionType": "team"})[0] == "team")
    check("plan live tier beats stale credential",
          plan_label({"rateLimitTier": "default_claude_max_5x"}, "default_claude_max_20x")[0] == "Max 20x")
    check("plan no live tier -> stored", plan_label({"rateLimitTier": "default_claude_max_5x"}, None)[0] == "Max 5x")
    check("live_tier extracts org tier",
          live_tier({"organization": {"rate_limit_tier": "default_claude_max_20x"}}) == "default_claude_max_20x")
    check("live_tier none on junk", live_tier({"organization": {}}) is None and live_tier("x") is None)

    check("parse_oauth wrapper", (parse_oauth('{"claudeAiOauth":{"accessToken":"x"}}') or {}).get("accessToken") == "x")
    check("parse_oauth flat", (parse_oauth('{"access_token":"y"}') or {}).get("access_token") == "y")
    check("parse_oauth junk -> None", parse_oauth("not json") is None)

    check("fmt_window null -> None", fmt_window({"utilization": None}) is None)
    check("fmt_window numeric -> str", isinstance(fmt_window({"utilization": 42.0, "resets_at": "2030-01-01T00:00:00Z"}), str))
    check("fmt_extra_usage disabled", "disabled" in fmt_extra_usage({"is_enabled": False}))
    check("fmt_extra_usage enabled",
          "enabled" in fmt_extra_usage({"is_enabled": True, "used_credits": 0.0, "monthly_limit": 100, "currency": "USD"}))
    check("fmt_extra_usage cents -> currency units",
          "199.21/550.00 BRL" in fmt_extra_usage(
              {"is_enabled": True, "used_credits": 19921.0, "monthly_limit": 55000, "currency": "BRL"}))

    check("fmt_tokens 11M", fmt_tokens(11_000_000) == "11M")
    check("fmt_tokens 6.6M", fmt_tokens(6_600_000) == "6.6M")
    check("fmt_tokens 2M (no .0)", fmt_tokens(2_000_000) == "2M")
    check("fmt_tokens 1.5K", fmt_tokens(1_500) == "1.5K")
    check("fmt_tokens plain", fmt_tokens(950) == "950")
    check("percent_label 56.1%", percent_label(56.123) == "56.1%")
    check("percent_label 19%", percent_label(19.0) == "19%")
    check("percent_label <0.1%", percent_label(0.05) == "<0.1%")
    check("shorten_model strips prefix+date",
          shorten_model("claude-haiku-4-5-20251001") == "haiku-4-5")
    check("sparkline shape", sparkline([0, 5, 10]) == "▁▅█")
    check("group_key by account uuid", group_key({"account": "u1", "fp": "x"}) == "acct:u1")
    check("sparkline all zero", sparkline([0, 0]) == "▁▁")
    check("model_price opus-4-7", model_price("claude-opus-4-7") == (5.0, 25.0))
    check("model_price fable", model_price("claude-fable-5") == (10.0, 50.0))
    check("model_price unknown", model_price("gpt-4o") is None)
    check("entry_tokens sums all kinds",
          entry_tokens({"input_tokens": 1, "output_tokens": 2,
                        "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4}) == 10)
    check("entry_cost plain in/out",
          abs(entry_cost("claude-sonnet-4-6", {"input_tokens": 1_000_000}) - 3.0) < 1e-9)
    check("entry_cost cache rates",  # 1M cache-read = 0.1x input; 1M 1h-write = 2x input
          abs(entry_cost("claude-sonnet-4-6",
                         {"cache_read_input_tokens": 1_000_000,
                          "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}) - 6.3) < 1e-9)
    check("entry_cost precomputed wins",
          entry_cost("claude-sonnet-4-6", {"input_tokens": 1_000_000}, 1.23) == 1.23)
    check("merge_local sums",
          merge_local({"day_tokens": {"d": 1}, "day_cost": {"d": 1.0}, "model_tokens": {"m": 1}},
                      {"day_tokens": {"d": 2}, "day_cost": {"d": 0.5}, "model_tokens": {"m": 2}}
                      )["day_tokens"]["d"] == 3)

    check("token_expired past", token_expired({"expiresAt": (time.time() - 10) * 1000}))
    check("token_expired future", not token_expired({"expiresAt": (time.time() + 3600) * 1000}))
    check("token_expired unknown -> False", not token_expired({}))
    check("keychain acct quoted", parse_keychain_account('    "acct"<blob>="pedro"') == "pedro")
    check("keychain acct hex", parse_keychain_account('"acct"<blob>=0x706564726f  "pedro"') == "pedro")
    check("keychain acct missing", parse_keychain_account("nothing here") is None)

    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("input") or ""))
        return subprocess.CompletedProcess(cmd, 0, '    "acct"<blob>="pedro"\n', "")

    real_run, subprocess.run = subprocess.run, fake_run
    try:
        marker = 'SELFTEST-TOKEN "q" \\ end'
        saved = persist_credentials({"kind": "keychain", "service": "svc", "full": {}},
                                    {"accessToken": marker})
    finally:
        subprocess.run = real_run
    check("keychain write ok", saved == (True, None))
    check("keychain write keeps credential out of argv",
          calls and not any("SELFTEST-TOKEN" in a for cmd, _ in calls for a in cmd))
    check("keychain write sends credential on stdin",
          calls and calls[-1][0] == ["security", "-i"] and "SELFTEST-TOKEN" in calls[-1][1])
    check("security -i line quoting",
          keychain_command_line(["-a", 'x"y\\z']) == '"-a" "x\\"y\\\\z"\n')
    check("security -i rejects newline / oversize",
          keychain_command_line(["a\nb"]) is None and keychain_command_line(["x" * SECURITY_LINE_MAX]) is None)

    check("failure_reason 429", "429" in failure_reason(429, {}))
    check("failure_reason 401", "401" in failure_reason(401, {}))
    check("humanize_age str", isinstance(humanize_age(time.time() - 120), str))

    fp1 = fingerprint({"five_hour": {"resets_at": "2030-01-01T00:00:00.111+00:00"}})
    fp3 = fingerprint({"five_hour": {"resets_at": "2030-01-01T00:00:00.222+00:00"}})
    check("fingerprint stable", bool(fp1) and fp1 == fingerprint({"five_hour": {"resets_at": "2030-01-01T00:00:00.111+00:00"}}))
    check("fingerprint differs by reset", fp1 != fp3)
    check("fingerprint none without windows", fingerprint({"subscriptionType": "pro"}) is None)
    check("group_key by fingerprint", group_key({"fp": "abc"}) == "fp:abc")
    check("group_key by token when no fp", group_key({"oauth": {"accessToken": "t"}}).startswith("tok:"))
    check("group_key distinct tokens differ",
          group_key({"oauth": {"accessToken": "a"}}) != group_key({"oauth": {"accessToken": "b"}}))

    print("\n%s" % ("ALL OK" if ok else "FAILED"))
    return 0 if ok else 1
