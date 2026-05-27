# CHANGELOG_PROMPTS.md — Histórico de versões dos system prompts

## v1.1 — ajustes de qualidade

### Prompts JavaScript (tests, smells, docs) — v1.0 → v1.1
**Motivação:** prompts JS anteriores eram superficiais comparados aos equivalentes Python.
Ausência de regras sobre mocks, async, estrutura de saída e smells específicos de JS.

- `tests_javascript.txt`: adicionadas regras para mock com jest.mock()/spyOn(), async/await
  com expect.assertions(), describe() blocks obrigatórios, test.each().
- `smells_javascript.txt`: adicionada lista explícita de smells JavaScript (floating promises,
  var, callback hell, sync I/O em handlers, eval). Mantido formato JSON idêntico ao Python.
- `docs_javascript.txt`: substituído por geração de JSDoc inline (retorna código documentado),
  com @fileoverview, @param com tipos, @returns, @throws e @example para funções públicas.

### Nenhuma mudança nos prompts Python (permanecem em v1.0)

---

## v1.0 — inicial

- `tests_python.txt`: geração de testes pytest com parametrize e mock
- `smells_python.txt`: detecção de code smells com saída JSON estruturada
- `docs_python.txt`: geração de docstrings Google-style

---

## Como versionar

1. Altere o arquivo de prompt desejado.
2. Incremente a versão no cabeçalho do arquivo (ex: v1.1 → v1.2).
3. Adicione uma entrada aqui descrevendo o que mudou e por quê.
4. Faça commit junto com o código que depende da nova versão.

Nunca apague versões antigas — crie um diretório `prompts/archive/` se necessário.
