# AGENTS.md — claude-usage

Dois scripts Python sem dependência (stdlib, Python 3.8+), macOS, mais um módulo comum:

- `claude-usage`: mostra plano e janelas de limite (5h/7d) de cada perfil do Claude Code, mais custo local estimado dos logs. Detalhes no `README.md`.
- `agent-usage`: visão unificada de cota de Claude, Cursor, Codex e OpenCode. Notas de pesquisa no `RELATORIO.md`.
- `usage_http.py`: cliente HTTP dos dois scripts. Segue redirecionamento só dentro da mesma origem, para o token não ir a outro host. Deve ficar ao lado dos scripts em qualquer cópia instalada.

## Instalar e rodar

`~/.local/bin/claude-usage` e `~/.local/bin/agent-usage` são symlinks para os arquivos deste repo: editar aqui muda o comando instalado.

```sh
./claude-usage                 # uso atual
./claude-usage --selftest      # checks offline, sem Keychain nem rede
./agent-usage --selftest
python3 -I test_redirects.py   # redirecionamentos HTTP, servidor local
```

O CI (`.github/workflows/ci.yml`) roda esses três comandos em push na `main` e em PR.

## Travas que o código mostra

- Nunca imprimir token nem segredo (`--debug-accounts` mostra só nomes de campo e hashes curtos).
- O `claude-usage` renova token expirado e grava o credencial rotacionado de volta onde achou. `--no-refresh` desliga isso (somente leitura).
- Lê credenciais do Keychain do macOS e chama endpoints não documentados da Anthropic e do Cursor; podem mudar. `--raw` mostra o JSON cru.
- Cache em `$XDG_CACHE_HOME/claude-usage` (padrão `~/.cache`), fora do repo.
- Repo com licença MIT.
