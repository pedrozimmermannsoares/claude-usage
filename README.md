# claude-usage

Track your **Claude** subscription plan and rate-limit usage straight from the
terminal — per profile, with no dependencies.

`claude-usage` reads the OAuth credential that Claude Code already stores on your
machine, asks Anthropic's usage endpoint how much of each rate-limit window you
have left, and prints it. It is **read-only**: it never writes credentials, never
refreshes/rotates tokens, and never prints your token.

```
claude-usage  03/06 18:11:31

● personal  (/Users/you/.claude-personal)
   plan:   Pro     (pro · rateLimitTier=default_claude_ai)
   source: keychain «Claude Code-credentials-1a2b3c4d»
   5h window      ████████░░░░░░░░░░░░  42.0% left  03/06 19:10 (in 58m)
   7d window      ██████████████████░░  89.0% left  07/06 14:00 (in 3d19h)
   overage        enabled · 0/100 USD

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
   pass labels or paths explicitly.
2. **Read the credential.** On macOS it reads the Keychain item
   `Claude Code-credentials` (or the per-profile hashed variant
   `Claude Code-credentials-<first 8 hex of sha256(config_dir)>`). On other
   platforms it falls back to `<config_dir>/.credentials.json`.
   The first Keychain read pops a "Allow" dialog — choose **Always Allow**.
3. **Query usage.** `GET https://api.anthropic.com/api/oauth/usage` with
   `Authorization: Bearer <token>` and `anthropic-beta: oauth-2025-04-20`.
4. **Render.** Plan from `rateLimitTier`, and each rate-limit window as **% left**
   (green = plenty, red = nearly out) with its reset time.

### Plan detection

| `rateLimitTier`           | Plan     |
|---------------------------|----------|
| `default_claude_free`     | Free     |
| `default_claude_ai`       | Pro      |
| `default_claude_max_5x`   | Max 5x   |
| `default_claude_max_20x`  | Max 20x  |

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
claude-usage                 # all auto-discovered profiles
claude-usage personal work   # only these (label or path)
claude-usage --watch 60      # refresh every 60s
claude-usage --raw           # raw API JSON (useful when the schema changes)
claude-usage --all           # also show empty / internal windows
claude-usage --billing       # open the billing page in a browser
claude-usage --selftest      # test pure functions (no Keychain / no network)
```

| Flag         | What it does |
|--------------|--------------|
| `--watch N`  | Re-render every `N` seconds. Cache covers transient failures; use 60s+. |
| `--raw`      | Dump the unparsed usage JSON. |
| `--all`      | Show windows with no data and internal codename fields. |
| `--billing`  | Open the billing page (the prepaid balance is **not** in the API). |
| `--selftest` | Run the offline unit checks. |

## Caching (survives rate limits)

The usage endpoint is rate-limited. When a live call fails (HTTP 429, network
error, expired token), `claude-usage` falls back to the **last successful response**
and marks it as stale (`⚠ live fetch failed … — showing cache` / `⏁ cached 2m ago`).
You keep a view instead of an error. Cache files live under
`$XDG_CACHE_HOME/claude-usage` (default `~/.cache/claude-usage`) and contain only
the usage payload — never the token. Delete the directory any time to clear it.

## What it does *not* show: the prepaid balance

The "current balance" / auto-recharge figure you see on the billing page is a
**billing** concept. It is not exposed by the OAuth usage endpoint, the OAuth token
scopes do not include billing, and the public Admin API only reports usage/cost —
not a balance. So `--billing` simply opens the page where you can read it.

## Security & privacy

* **Read-only.** Never writes to the Keychain, never refreshes or rotates tokens
  (which would invalidate your Claude Code login).
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
