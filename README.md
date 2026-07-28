# RSS de Valor

Agregador pessoal de feeds RSS para colunistas brasileiros e fontes de risco
climático. O projeto coleta artigos, preserva histórico entre execuções e
publica feeds padronizados para consumo no Feedbin.

[![Private feed publication](https://github.com/paulofeh/rss-de-valor/actions/workflows/private-feed-publication.yml/badge.svg)](https://github.com/paulofeh/rss-de-valor/actions/workflows/private-feed-publication.yml)

## Estado atual

A publicação canônica é privada:

- endpoint: `https://feeds.paulofehlauer.com`;
- leitura protegida por HTTP Basic Auth sobre HTTPS;
- Cloudflare Worker como única porta de leitura privada;
- bucket R2 Standard privado, sem `r2.dev` ou domínio público;
- snapshots imutáveis, ativados atomicamente por `current.json`;
- atualização automática nominal a cada seis horas;
- 28 snapshots de retenção;
- suporte a `GET`, `HEAD`, ETag, `Last-Modified` e respostas `304`;
- OPML privado e nenhum índice HTML na superfície privada.

Em 28 de julho de 2026, a configuração e o snapshot privado ativo passaram a
ter 109 fontes:

- 108 feeds gerados, cada um com seu histórico;
- um RSS nativo mantido diretamente no provedor;
- 217 objetos internos e 109 rotas no snapshot privado completo.

O snapshot `30394804773-1-1204dfd6414d` encerrou a janela de estabilização
posterior à migração. O Feedbin acompanha os 108 feeds gerados pelo endpoint
privado; Juliano Spyer e Sérgio Rodrigues foram validados e suas assinaturas
nativas foram removidas. FT Climate Capital é a única assinatura que continua
diretamente no provedor. As 87 assinaturas antigas que apontavam para o GitHub
Pages já foram removidas.

No corte público de 28 de julho de 2026, o workflow legado foi retirado e
`feeds/` e `history/` deixaram de ser versionados. Esses diretórios continuam
sendo criados localmente e hidratados do R2 durante a publicação privada. O
histórico Git não foi reescrito.

## Fontes configuradas

| Grupo | Fontes |
|---|---:|
| Risco climático | 27 |
| Folha de S.Paulo | 26 |
| LinkedIn Newsletters | 19 |
| Estadão | 18 |
| O Globo | 11 |
| Valor Econômico | 4 |
| Outros | 3 |
| Banco Mundial | 1 |
| **Total** | **109** |

O único `ExistingRssScraper` é FT Climate Capital, que continua apontando para
o feed original e não é copiado para o R2. Juliano Spyer passou a usar a página
da coluna porque o RSS oficial ficou congelado; Sérgio Rodrigues usa o RSS
oficial com enriquecimento de conteúdo integral.

A fonte de transcrições do YouTube foi retirada da configuração ativa. A classe
`YouTubeTranscriptScraper` e sua dependência ainda existem como código legado,
mas nenhum feed configurado as utiliza.

## Como funciona

O fluxo privado é:

```text
R2/current.json
    ↓
hidratação do snapshot ativo
    ↓
main.py → scrapers → feeds + históricos + OPML
    ↓
allowlist + validações de XML, hashes, GUIDs, self-links e conteúdo
    ↓
upload de snapshot imutável
    ↓
releitura dos objetos e verificação do ponteiro observado
    ↓
troca atômica de current.json
    ↓
canários autenticados e anônimos
    ↓
retenção
```

O Worker autentica antes de resolver método ou caminho. Depois da autenticação,
ele lê o ponteiro, o manifesto e o objeto correspondente no binding privado do
R2. O Worker nunca executa scrapers e uma atualização de conteúdo não exige
redeploy.

As rotas privadas são:

```text
/feeds/<feed_file>
/feeds.opml
```

Credenciais não devem ser incluídas na URL. O Feedbin solicita e armazena o
usuário e a senha separadamente.

## Execução local

Use sempre o ambiente virtual local, nunca o Python do sistema:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 main.py
```

`main.py` escreve em `feeds/` e `history/`, que são diretórios locais ignorados
pelo Git. Sem `FEED_BASE_URL`, a execução usa o domínio canônico privado nos
self-links. A variável continua disponível para testes com outra origem HTTPS:

```bash
FEED_BASE_URL=https://feeds.example.invalid .venv/bin/python3 main.py
```

`FEED_BASE_URL` deve ser uma origem HTTPS sem caminho, porta explícita,
credenciais, query ou fragmento.

## Testes

Instale também as dependências da publicação privada:

```bash
.venv/bin/pip install -r requirements-private.txt
.venv/bin/python3 -m unittest discover -s tests -v
```

Para o Worker:

```bash
cd worker
npm ci
npm run check
npm test
npm run deploy -- --dry-run
```

O último comando apenas empacota e valida o Worker; não faz implantação.

## Estrutura

```text
rss-de-valor/
├── config/
│   ├── sources_config.json
│   └── private_publication_allowlist.json
├── docs/
│   ├── private-feed-publication-cloudflare-spec.md
│   └── private-feed-publication-runbook.md
├── scripts/
│   ├── hydrate_private_state.py
│   ├── repair_linkedin_baseline.py
│   ├── build_snapshot_manifest.py
│   ├── validate_snapshot.py
│   ├── publish_snapshot.py
│   └── rollback_snapshot.py
├── src/
│   ├── scrapers.py
│   └── utils.py
├── tests/
├── worker/
│   ├── src/
│   ├── test/
│   └── wrangler.jsonc
├── main.py
└── .github/workflows/
    ├── private-feed-pilot.yml
    ├── private-feed-publication.yml
    └── private-feed-rollback.yml
```

## Workflows

### Publicação privada completa

`private-feed-publication.yml` usa `contents: read` e o grupo de concorrência
`private-feed-r2-publication`. O cron nominal é `47 */6 * * *` em UTC. Cada
execução:

1. hidrata o snapshot ativo;
2. executa `main.py`;
3. valida e monta o conjunto completo;
4. publica e relê todos os objetos;
5. ativa `current.json` condicionalmente;
6. executa canários;
7. aplica retenção.

O input manual `repair_linkedin_baseline` existe apenas para transportar pela
hidratação os 12 pares feed/histórico completos identificados em 2026-07-27.
Ele exige confirmação da publicação completa, usa uma allowlist fixa e não é
executado pelo cron. Seu perfil de validação também pode substituir a data
sintética de um stub pela data real somente quando o mesmo item allowlisted
recupera simultaneamente autoria e conteúdo completos.

### Piloto

`private-feed-pilot.yml` permanece no repositório para diagnóstico controlado,
mas seu gate deve continuar desabilitado durante a operação completa. Ele não
pode substituir um snapshot completo por um snapshot de uma única rota.

### Rollback

`private-feed-rollback.yml` é manual, compartilha o mesmo grupo de concorrência
e só aceita snapshots em modo `full`. O rollback valida o destino antes de
trocar o ponteiro e restaura o anterior se o canário falhar.

### Corte da publicação pública

O workflow legado foi removido. A branch atual não contém `feeds/` nem
`history/`, e nenhum workflow ativo possui permissão para commitar artefatos
gerados. A publicação de conteúdo acontece somente pelo pipeline privado.

## Adicionar uma fonte

1. Adicione a entrada em `config/sources_config.json`.
2. Para uma fonte com RSS oficial, use `ExistingRssScraper`; ela continuará
   apontando diretamente ao provedor.
3. Para scraping novo, implemente uma classe em `src/scrapers.py`, registre-a em
   `get_scraper_class()` e prefira `get_articles(limit=...)`.
4. Se criar um grupo, atualize os dois mapas `group_display_names` em
   `src/utils.py`.
5. Rode os testes Python e valide a geração local.
6. Confirme que apenas os caminhos derivados da configuração e da política em
   `config/private_publication_allowlist.json` entram no snapshot.

Não faça upload indiscriminado de `feeds/*.xml`. Agregados e arquivos órfãos
exigem uma decisão e uma allowlist explícitas.

## Remover uma fonte

1. Remova a entrada da configuração.
2. Remova artefatos locais ignorados, se existirem, quando isso ajudar a
   validação da mudança.
3. Rode os testes de snapshot.
4. Confirme que a próxima publicação privada ignora os objetos legados durante
   a hidratação e não os inclui no novo manifesto.

## Segurança

- Nunca registre `Authorization`, usuário, senha ou tokens.
- Nunca coloque credenciais no Git, XML, OPML, logs ou URLs.
- Trate qualquer export do Feedbin como secreto: `subscriptions.xml` pode
  materializar credenciais dentro de `xmlUrl`.
- Mantenha o bucket R2 sem `r2.dev`, Custom Domain ou política anônima.
- Não use cache público para conteúdo autenticado.
- Ausência de credenciais e credenciais inválidas devem gerar a mesma resposta
  `401`.
- Publicação e rollback devem permanecer serializados.

## Documentação operacional

- [Especificação da publicação privada](docs/private-feed-publication-cloudflare-spec.md)
- [Runbook de operação e recuperação](docs/private-feed-publication-runbook.md)
- [Backlog e gates restantes](BACKLOG.md)
- [Guia para agentes de código](AGENTS.md)

## Licença

O código está disponível sob a [licença MIT](LICENSE). A licença do repositório
não altera os direitos sobre os artigos coletados de terceiros.
