# claude-usage

Track your **Claude** subscription plan and rate-limit usage straight from the
terminal — per profile, with no dependencies.

`claude-usage` reads the OAuth credential that Claude Code already stores on your
machine, asks Anthropic's usage endpoint how much of each rate-limit window you
have left, and prints it. It never prints your token. When the access token has
**expired** (a profile you haven't used in hours) it refreshes it the same way
Claude Code does and writes the rotated credential back where it found it, so
your login keeps working — see [Token refresh](#token-refresh). Disable with
`--no-refresh` for strictly read-only behavior.

```
claude-usage  03/06 18:11:31

● personal  (/Users/you/.claude-personal)
   plan:   Pro     (pro · rateLimitTier=default_claude_ai)
   source: keychain «Claude Code-credentials-1a2b3c4d»
   5h window      ████████░░░░░░░░░░░░  42.0% left  03/06 19:10 (in 58m)
   7d window      ██████████████████░░  89.0% left  07/06 14:00 (in 3d19h)
   overage        enabled · 12.50/100.00 USD  (13% used)
   ─ local usage · last 30d · estimated from Claude Code logs at API rates ─
   today          $21.43 · 11M tokens
   yesterday      $8.35 · 6.6M tokens
   last 30d       $102.33 · 108M tokens
   trend          ▁▁▁▂▆▆▅█▅▃▃▂▂▄▂▂▃▂▁▁▁▁▂▃▁▁▂▃▃▄  peak 41M tok/day
   models         opus-4-8 42.2% · sonnet-4-6 21.7% · fable-5 5.1%

● work      (/Users/you/.claude-work)
   plan:   Max 5x  (max · rateLimitTier=default_claude_max_5x)
   source: keychain «Claude Code-credentials-5e6f7a8b»
   5h window      █████████░░░░░░░░░░░░  45.0% left  03/06 20:10 (in 1h58m)
   7d window      █████████████░░░░░░░  65.0% left  06/06 06:00 (in 2d11h)
   overage        disabled
```

## Why

I built this because I couldn't find any tool that shows Claude usage **per
profile** — that is, per `CLAUDE_CONFIG_DIR` / per config path. On my machine I run
two separate Claude logins side by side: a personal one and my company one, each in
its own config directory. I wanted to watch each one's limits independently, in one
place. If you juggle more than one Claude account on the same computer, you probably
have the same problem — and most tools assume a single account.

On top of that, Claude Code's `/status` doesn't tell you which Max tier you're on,
and neither a CLI flag nor any local config file records it. That information lives
in the OAuth credential (`rateLimitTier`) and behind an authenticated usage
endpoint. `claude-usage` surfaces both, for every profile you have, in one command.

## How it works

1. **Find profiles.** A "profile" is a `CLAUDE_CONFIG_DIR`. The tool auto-discovers
   `$CLAUDE_CONFIG_DIR`, `~/.claude`, and any `~/.claude-*` directory. You can also
   pass labels or paths explicitly. (When you have named `~/.claude-*` profiles, the
   bare `~/.claude` is hidden by default — see [Profiles & accounts](#profiles--accounts).)
2. **Read the credential.** On macOS it reads the Keychain item
   `Claude Code-credentials` (or the per-profile hashed variant
   `Claude Code-credentials-<first 8 hex of sha256(config_dir)>`). On other
   platforms it falls back to `<config_dir>/.credentials.json`.
   The first Keychain read pops a "Allow" dialog — choose **Always Allow**.
3. **Query usage.** `GET https://api.anthropic.com/api/oauth/usage` with
   `Authorization: Bearer <token>` and `anthropic-beta: oauth-2025-04-20`, plus
   `GET …/api/oauth/profile` for the account's current plan tier.
4. **Render.** Plan from `rate_limit_tier`, and each rate-limit window as **% left**
   (green = plenty, red = nearly out) with its reset time.

### Plan detection

| `rate_limit_tier`         | Plan     |
|---------------------------|----------|
| `default_claude_free`     | Free     |
| `default_claude_ai`       | Pro      |
| `default_claude_max_5x`   | Max 5x   |
| `default_claude_max_20x`  | Max 20x  |

The tier is taken **live** from the profile endpoint (`organization.rate_limit_tier`),
because the `rateLimitTier` stored in the credential goes stale when you change
plans — Claude Code only rewrites it when you log in again. When the credential
disagrees with the live value, a note marks it as stale; when the profile call
fails, the tool falls back to the cached tier, then to the credential. Only the
tier string is kept from the profile response (names/emails are discarded).

## Token refresh

Claude Code access tokens expire after a few hours. If you haven't used Claude
Code in a profile since then, the stored token is dead and the usage call fails —
you'd only ever see stale cache for that profile. So when (and only when) the
stored token is past its `expiresAt`, `claude-usage` refreshes it exactly like
Claude Code does:

- `POST https://platform.claude.com/v1/oauth/token` with `grant_type=refresh_token`
  and Claude Code's own public `client_id`.
- Anthropic refresh tokens are **single-use (rotating)**: the response carries a
  new refresh token and the old one is invalidated server-side. The refreshed
  credential is therefore written back to the **same** Keychain item / credentials
  file Claude Code reads (same service, same account, minified JSON, Claude Code's
  own format) — skipping that step is what *would* break your login.
- A valid token is never refreshed, so a profile you're actively using in Claude
  Code is never touched. `--no-refresh` disables all of this (strictly read-only;
  expired profiles then show cached data with the failure reason).

If the refresh token itself is rejected (you logged out / revoked the session),
the tool tells you to run Claude Code in that profile to log in again.

## Local cost & usage (the OpenUsage/ccusage block)

Each profile also shows what its usage **would cost at API rates** — today,
yesterday, the last 30 days, a daily token trend, and the per-model token share.
This is computed **entirely locally** from Claude Code's own transcripts
(`<config_dir>/projects/**/*.jsonl`), the same approach ccusage and OpenUsage use:

- Each assistant message's token counts (input, output, cache write, cache read)
  are priced per model at current API rates. Cache writes are priced at 1.25×
  input (5-minute TTL) or 2× (1-hour TTL — what Claude Code actually uses, so
  numbers can run slightly above tools that price all cache writes at 1.25×);
  cache reads at 0.1×.
- Entries are de-duplicated by `message.id` + `requestId` — resumed/branched
  sessions rewrite the same messages into new transcript files.
- **Incremental**: per-file results are cached under `~/.cache/claude-usage`
  keyed by mtime+size. The first run indexes everything (a big profile can take
  a few seconds); subsequent runs only re-parse transcripts that changed, which
  keeps `--watch` cheap.
- The hidden bare `~/.claude` still accrues transcripts (it's the same login as
  one of your named profiles); its usage is folded into the matching account,
  found via the `accountUuid` in Claude Code's local `.claude.json` — no extra
  API call.

It's an **estimate**, not a bill — subscription usage isn't billed per token.
Model prices live in the `MODEL_PRICES` table at the top of the script; add new
models there as they launch. Skip the whole section with `--no-local`.

## Profiles & accounts

If you run more than one Claude login on a machine, several config dirs can point
at the **same account** — most commonly the bare `~/.claude` (default) and a named
`~/.claude-<name>` you created on purpose. `claude-usage` keeps the view tidy:

- **The bare `~/.claude` is hidden by default** when any named `~/.claude-*` profile
  exists — you made the named path because that's the one you want. Show it with
  `--include-default`, or query it directly with `claude-usage default`.
- **Same-account de-duplication.** Profiles are grouped by the `accountUuid` that
  Claude Code records locally in each profile's `.claude.json` — exact and offline.
  When that file is missing, the fallback is a fingerprint built from the usage
  **reset timestamps** (microsecond precision → effectively unique per account),
  remembered under `~/.cache/claude-usage`; the last resort is the token hash.
  Profiles that share an account collapse into one line under the named (path) label.
- **No wrong merges, no lost data.** Until a shared account is confirmed by a matching
  fingerprint, profiles are shown separately rather than guessed-merged — so the tool
  never prints one account's numbers under another's label.

## Install

Requires Python 3.8+ (standard library only). macOS for the Keychain path; Linux/
Windows use the `.credentials.json` fallback.

```sh
# copy onto your PATH
install -m 0755 claude-usage ~/.local/bin/claude-usage
# or symlink it
ln -s "$PWD/claude-usage" ~/.local/bin/claude-usage
```

## Usage

```sh
claude-usage                 # auto-discovered profiles (bare ~/.claude hidden if named ones exist)
claude-usage personal work   # only these (label or path)
claude-usage --include-default  # also show the bare ~/.claude profile
claude-usage --watch 60      # refresh every 60s
claude-usage --raw           # raw API JSON (useful when the schema changes)
claude-usage --all           # also show empty / internal windows
claude-usage --billing       # open the billing page in a browser
claude-usage --no-refresh    # strictly read-only: never refresh expired tokens
claude-usage --no-local      # skip the local cost/usage section
claude-usage --selftest      # test pure functions (no Keychain / no network)
```

| Flag                | What it does |
|---------------------|--------------|
| `--include-default` | Also show the bare `~/.claude` profile (hidden by default when named profiles exist). |
| `--watch N`         | Re-render every `N` seconds. Cache covers transient failures; use 60s+. |
| `--raw`             | Dump the unparsed usage JSON. |
| `--all`             | Show windows with no data and internal codename fields. |
| `--billing`         | Open the billing page (the prepaid balance is **not** in the API). |
| `--no-refresh`      | Never refresh expired tokens (strictly read-only; expired profiles show stale cache). |
| `--no-local`        | Skip the local cost/usage block (no transcript parsing). |
| `--debug-accounts`  | Diagnose how profiles map to accounts (prints only field names + short hashes, never secrets). |
| `--selftest`        | Run the offline unit checks. |

## Caching (survives rate limits)

The usage endpoint is rate-limited. When a live call fails (HTTP 429, network
error, rejected token), `claude-usage` falls back to the **last successful response**
and marks it as stale with the failure reason (`⏁ cached 2m ago — rate limited (429)`).
You keep a view instead of an error. Cache files live under
`$XDG_CACHE_HOME/claude-usage` (default `~/.cache/claude-usage`) and contain only
the usage payload — never the token. Delete the directory any time to clear it.

## What it does *not* show: the prepaid balance

The "current balance" / auto-recharge figure you see on the billing page is a
**billing** concept. It is not exposed by the OAuth usage endpoint, the OAuth token
scopes do not include billing, and the public Admin API only reports usage/cost —
not a balance. So `--billing` simply opens the page where you can read it.

## Security & privacy

* **Reads, except one case.** Credentials are only read while the access token is
  valid. The single write path is the expired-token refresh described above, which
  updates the same item Claude Code uses, in Claude Code's own format (because
  refresh tokens rotate, *not* saving it back is what would invalidate the login).
  `--no-refresh` removes that path entirely.
* **Never prints your token.** Only plan, source service name, and usage windows.
* **Stays local.** The only network call is to Anthropic's usage endpoint, with
  your own token. Any tool that can read this Keychain item is effectively
  authenticated as your Claude Code session — install only tools you trust.

## Disclaimer

Unofficial and not affiliated with Anthropic. It calls an **undocumented** endpoint
that Anthropic's own apps use; it may change or break at any time. Use `--raw` to
inspect the current payload and open an issue/PR if the schema drifts.

## License

[MIT](LICENSE) — free for any use, including commercial. You may copy, modify, and
redistribute it; just keep the copyright and license notice.
