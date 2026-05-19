# CHANGELOG_PROMPTS.md — Histórico de versões dos system prompts

## v1.0 — inicial

- `tests_python.txt`: geração de testes pytest com parametrize e mock
- `smells_python.txt`: detecção de code smells com saída JSON estruturada
- `docs_python.txt`: geração de docstrings Google-style

## Como versionar

1. Altere o arquivo de prompt desejado.
2. Incremente a versão no cabeçalho do arquivo (ex: v1.0 → v1.1).
3. Adicione uma entrada aqui descrevendo o que mudou e por quê.
4. Faça commit junto com o código que depende da nova versão.

Nunca apague versões antigas — crie um diretório `prompts/archive/` se necessário.
