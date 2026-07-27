# RSS de Valor

Agregador pessoal de feeds RSS para colunistas brasileiros e fontes de risco
climático. O projeto coleta artigos, preserva histórico entre execuções e
publica feeds padronizados para consumo no Feedbin.

[![Private feed publication](https://github.com/paulofeh/rss-de-valor/actions/workflows/private-feed-publication.yml/badge.svg)](https://github.com/paulofeh/rss-de-valor/actions/workflows/private-feed-publication.yml)
[![Legacy Pages publication](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml/badge.svg)](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml)

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

Em 27 de julho de 2026, o repositório tinha 108 fontes configuradas:

- 106 feeds gerados, cada um com seu histórico;
- dois RSS nativos, mantidos diretamente nos provedores;
- 213 objetos internos e 107 rotas no snapshot privado completo.

A migração do Feedbin foi concluída com 87 assinaturas privadas. As 87
assinaturas antigas que apontavam para o GitHub Pages foram removidas do
Feedbin.

O GitHub Pages, os arquivos em `feeds/` e `history/` e o workflow público ainda
existem como contingência temporária. Eles não são mais a origem canônica para
novas assinaturas. O corte público depende de uma autorização explícita
separada e não inclui reescrita do histórico Git.

## Fontes configuradas

| Grupo | Fontes |
|---|---:|
| Risco climático | 27 |
| Folha de S.Paulo | 25 |
| LinkedIn Newsletters | 19 |
| Estadão | 18 |
| O Globo | 11 |
| Valor Econômico | 4 |
| Outros | 3 |
| Banco Mundial | 1 |
| **Total** | **108** |

Os dois `ExistingRssScraper` são FT Climate Capital e Juliano Spyer. Eles
continuam apontando para os feeds originais e não são copiados para o R2.

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

`main.py` escreve em `feeds/` e `history/`. Sem `FEED_BASE_URL`, a execução
local preserva a origem legada do GitHub Pages. Para gerar self-links iguais aos
de produção sem publicar nada:

```bash
FEED_BASE_URL=https://feeds.paulofehlauer.com .venv/bin/python3 main.py
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
├── feeds/                         # artefatos legados ainda versionados
├── history/                       # estado legado ainda versionado
├── scripts/
│   ├── hydrate_private_state.py
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
    ├── workflow.yml
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

### Piloto

`private-feed-pilot.yml` permanece no repositório para diagnóstico controlado,
mas seu gate deve continuar desabilitado durante a operação completa. Ele não
pode substituir um snapshot completo por um snapshot de uma única rota.

### Rollback

`private-feed-rollback.yml` é manual, compartilha o mesmo grupo de concorrência
e só aceita snapshots em modo `full`. O rollback valida o destino antes de
trocar o ponteiro e restaura o anterior se o canário falhar.

### Publicação pública legada

`workflow.yml` continua rodando nominalmente em `0 */6 * * *` UTC, gerando e
commitando `feeds/` e `history/`. Ele será removido ou reduzido para
`contents: read` somente no gate de corte. Não cadastrar novas assinaturas nas
URLs do GitHub Pages.

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
2. Remova explicitamente o XML e o histórico locais quando isso fizer parte da
   mudança aprovada.
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
