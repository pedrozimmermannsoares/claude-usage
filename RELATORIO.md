# Relatório — agent-usage

Visão unificada de uso/cota das ferramentas de agente do Pedro, num único comando read-only.

## Como rodar

```sh
# no repo (ou após install -m 0755 agent-usage ~/.local/bin/agent-usage)
./agent-usage

./agent-usage --watch 60      # refresh a cada 60s
./agent-usage --include-default  # inclui ~/.claude além dos ~/.claude-*
./agent-usage --selftest      # checks offline
```

Requisitos: Python 3.8+, macOS Keychain (Claude + Cursor), `ccusage` no PATH (Homebrew) para tokens Codex/OpenCode.

## O que cada provider expõe

### Claude (claude-usage embutido)

| Superfície | Disponível | Evidência |
|------------|------------|-----------|
| Plano (Pro / Max 5x / Max 20x) | ✅ | OAuth `rateLimitTier` no Keychain |
| Janelas 5h / 7d (% restante) | ✅ | `GET https://api.anthropic.com/api/oauth/usage` |
| Tokens/custo por dia | ✅ (via ccusage) | Logs locais do Claude Code |
| Saldo pré-pago billing | ❌ | Não está no endpoint OAuth; só no browser |

**Fonte:** lógica existente em `claude-usage` — não reconstruída.

### Cursor

| Superfície | Disponível | Evidência |
|------------|------------|-----------|
| `cursor-agent --help` | ❌ sem subcomando usage/quota | Só `about`, `status`, `models`, `login`, etc. |
| `cursor-agent about --format json` | ⚠️ parcial | Retorna `subscriptionTier`, `model`, `userEmail` — **sem % de cota** |
| `~/.cursor/ai-tracking/ai-code-tracking.db` | ⚠️ atribuição | Tabelas `ai_code_hashes`, `scored_commits` — rastreia código gerado, **não assinatura** |
| `GET https://api2.cursor.sh/auth/usage-summary` | ✅ | Bearer do Keychain `cursor-access-token` / `cursor-user` |
| `GET https://api2.cursor.sh/auth/usage` | ⚠️ legado | HTTP 200 mas campos zerados (`numRequests: 0`) |
| Dashboard web | ✅ | https://cursor.com/settings |

**Implementado:** leitura de `/auth/usage-summary` com token do Keychain (mesmo padrão do claude-usage). Mostra ciclo de billing, créditos incluídos, % auto/API/total. Cache em `~/.cache/agent-usage/cursor-usage-summary.json` em falha de rede.

**Não exposto via CLI local:** tokens/custo por sessão do Cursor Agent — ccusage não cobre Cursor; `ai-code-tracking.db` não tem custo.

### Codex (ChatGPT subscription)

| Superfície | Disponível | Evidência |
|------------|------------|-----------|
| `codex --help` | ❌ sem quota | Subcomandos: exec, login, doctor, mcp — nenhum `usage` |
| `codex doctor --json` | ❌ sem quota | Checa auth, rede, sandbox — sem rate-limit |
| `~/.codex/sessions/**/*.jsonl` | ✅ | Eventos `token_count` com `rate_limits.primary/secondary` |
| `ccusage codex daily` | ✅ tokens/custo | Agrega logs locais |

**Estrutura do rate_limit nos logs** (exemplo real de `2026-07-11`):

```json
"rate_limits": {
  "primary": {"used_percent": 100.0, "window_minutes": 43200, "resets_at": 1786374892},
  "plan_type": "go"
}
```

Janelas observadas: `300` (5h), `10080` (7d), `43200` (30d). O script converte `used_percent` → **% restante** e mostra o snapshot mais recente dos logs.

**Limitação:** quota Codex só aparece **após uma sessão recente** (o CLI grava no JSONL). Sem sessão recente, só tokens via ccusage.

### OpenCode

| Superfície | Disponível | Evidência |
|------------|------------|-----------|
| Rate-limit / cota | ❌ | Nenhum endpoint ou campo nos logs |
| Tokens por dia | ✅ | `ccusage opencode daily --json` |

Seção só aparece quando ccusage detecta logs.

## Arquitetura do script

```
agent-usage
├── CLAUDE    → importa claude-usage (mesmo diretório)
├── CURSOR    → Keychain + api2.cursor.sh/auth/usage-summary
├── CODEX     → ~/.codex/sessions JSONL (rate_limits) + ccusage
└── OPENCODE  → ccusage (se houver dados)
```

Segurança: read-only, zero dependências, **nunca imprime token**. Cache separado em `~/.cache/agent-usage/`.

## TODOs conhecidos

1. **Cursor tokens/custo** — ccusage não cobre; não há CLI equivalente. Workaround: dashboard web ou futura integração com `ai-code-tracking.db` (só volume de código, sem $).
2. **Codex quota sem sessão** — depende do último `token_count` nos logs; considerar cache do último snapshot (já implícito ao reler logs).
3. **Cursor endpoint não documentado** — `/auth/usage-summary` pode mudar; usar cache + `--selftest`.
