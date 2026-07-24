# Publicação privada de feeds com Cloudflare Worker

**Status:** implementação, base Cloudflare, deploy e commit/push iniciais concluídos; piloto técnico em validação, com GitHub Pages preservado
**Última revisão:** 2026-07-24
**Origem:** item “Publicação privada dos feeds com compatibilidade com o Feedbin” do [`BACKLOG.md`](../BACKLOG.md)

## 1. Resumo executivo

Esta especificação descreve a migração dos feeds gerados pelo projeto de uma
publicação pública no GitHub Pages para uma distribuição privada compatível com
o Feedbin.

A arquitetura de referência é:

- código e configuração permanecem no repositório atual;
- artefatos gerados e estado de execução deixam de ser versionados publicamente;
- o GitHub Actions continua executando os scrapers a cada seis horas;
- um bucket Cloudflare R2 privado armazena snapshots completos da publicação;
- um Cloudflare Worker é a única porta de leitura dos artefatos;
- o Worker exige HTTP Basic Auth sobre HTTPS;
- o Feedbin armazena as credenciais de cada assinatura protegida;
- a publicação pública atual só é desligada depois de um piloto e de uma
  migração verificada.

O Worker não executa os scrapers e não precisa ser reimplantado a cada
atualização dos feeds. A implantação do código de entrega e a publicação de
conteúdo são operações independentes.

## 2. Estado da decisão

### 2.1 Baseline recomendado

| Tema | Baseline |
|---|---|
| Topologia do repositório | Código público e artefatos privados |
| Serviço de entrega | Cloudflare Worker |
| Armazenamento | Cloudflare R2 Standard, bucket privado |
| Autenticação | HTTP Basic Auth sobre HTTPS |
| Domínio canônico | `paulofehlauer.com` |
| Domínio de produção dos feeds | `feeds.paulofehlauer.com` |
| Domínio de piloto | Subdomínio temporário `workers.dev` |
| Publicação | Snapshots versionados com ponteiro atômico |
| Estado do pipeline | Feeds anteriores e `history/` no R2 |
| Retenção | 28 snapshots, equivalentes a sete dias no ritmo atual |
| Feeds RSS nativos | Continuam apontando para os provedores originais |
| OPML | Privado, servido pelo mesmo Worker |
| Índice HTML | Desabilitado ou privado; nunca público com o inventário completo |
| Cache | Sem cache público; revalidação condicional com ETag |

### 2.2 Decisões resolvidas e gates restantes

Decisões aplicadas na implementação local:

1. o repositório continua público e os artefatos passam a ser privados somente
   no gate de corte;
2. os sete agregados legados e três feeds órfãos não entram na allowlist;
3. o OPML é privado e o índice HTML não é publicado;
4. uma credencial comum é aceita inicialmente, com duas senhas durante rotação;
5. não haverá reescrita de histórico;
6. os dois RSS nativos continuam apontando diretamente para os provedores.

Continuam como gates externos:

1. criar os recursos Cloudflare;
2. implantar e publicar um único feed piloto;
3. confirmar atualização automática, tags e estado de leitura no Feedbin;
4. inventariar a zona DNS completa;
5. autorizar nameservers, domínio definitivo, publicação completa e corte em
   decisões separadas.

### 2.3 Premissas

- O serviço é destinado ao uso pessoal de um único operador.
- O Feedbin é o cliente de leitura que define a compatibilidade mínima.
- Não haverá clientes anônimos para os feeds com conteúdo integral.
- O agendamento continuará no GitHub Actions.
- O volume permanecerá próximo da ordem de centenas, não milhões, de feeds.
- Uma credencial compartilhada é aceitável como ponto de partida, desde que
  exista procedimento de rotação.
- Privacidade reduz exposição, mas não transforma conteúdo de terceiros em
  conteúdo livre de restrições autorais.
- Preços, limites e recursos da Cloudflare serão revistos antes da execução.

### 2.4 Decisão de domínio

Decisão registrada em 2026-07-24:

- `paulofehlauer.com` é o domínio canônico;
- `feeds.paulofehlauer.com` será o endpoint definitivo dos feeds privados;
- o piloto usará uma URL temporária `workers.dev`;
- `paulofehlauer.com` continuará redirecionando para o Linktree durante a
  migração de DNS;
- a configuração do Worker não deve interferir no redirecionamento do domínio
  principal;
- `fehla.xyz` permanece como domínio legado até pelo menos seu vencimento em
  abril de 2027;
- não serão criadas URLs definitivas de feeds sob `fehla.xyz`;
- não é necessário adquirir outro domínio para esta implementação.

Antes de alterar os nameservers de `paulofehlauer.com`:

1. exportar ou registrar todos os DNS records existentes;
2. conferir especialmente `A`, `AAAA`, `CNAME`, `MX`, `TXT` e `CAA`;
3. documentar como o redirecionamento para o Linktree funciona atualmente;
4. recriar e validar esses comportamentos na Cloudflare;
5. somente então trocar a delegação DNS;
6. verificar o domínio principal antes de criar o Custom Domain do Worker.

## 3. Objetivos

### 3.1 Objetivos funcionais

- Servir os feeds gerados por URLs HTTPS estáveis.
- Exigir autenticação antes de entregar conteúdo ou metadados dos feeds.
- Manter compatibilidade com o Feedbin.
- Continuar atualizando os feeds automaticamente a cada seis horas.
- Preservar a lógica que impede a substituição de conteúdo integral por stubs
  durante falhas transitórias.
- Permitir rollback rápido para a publicação anterior.
- Oferecer um OPML privado para cadastro e recuperação.
- Permitir adição e remoção de fontes sem alterar o código do Worker.

### 3.2 Objetivos não funcionais

- Nenhum segredo no Git, nos XMLs, no OPML ou nos logs.
- Nenhum bucket, endpoint alternativo ou origem pública que contorne o Worker.
- Publicação de todos os feeds como uma unidade consistente.
- URLs independentes do domínio `workers.dev` em produção.
- Self-links e OPML usando `https://feeds.paulofehlauer.com`.
- Operação compatível com a faixa gratuita da Cloudflare na escala atual.
- Diagnóstico que diferencie falha de coleta, validação, publicação,
  autenticação e entrega.
- Mudança reversível até o desligamento final do GitHub Pages.

### 3.3 Fora de escopo

- Alterar a frequência dos scrapers.
- Corrigir ou criar scrapers sem relação direta com a publicação privada.
- Usar Cloudflare Access, OAuth ou uma interface de login interativa.
- Reescrever o histórico Git sem autorização específica.
- Tratar a autenticação como solução completa para questões autorais.
- Tornar privados os RSS oficiais que continuarem sendo consumidos diretamente
  dos provedores.

## 4. Inventário e restrições atuais

Snapshot do repositório em 2026-07-24:

- 109 fontes configuradas;
- 107 fontes processadas pelo pipeline;
- 2 fontes com RSS nativo, não processadas pelo `main.py`;
- 119 XMLs presentes em `feeds/`;
- aproximadamente 5,3 MB de artefatos em `feeds/`;
- execução agendada quatro vezes ao dia;
- publicação atual por commit de `feeds/` e `history/`;
- URLs internas baseadas em
  `https://paulofeh.github.io/rss-de-valor`.
- `paulofehlauer.com` controlado pelo usuário e atualmente usado como
  redirecionamento para o Linktree;
- `fehla.xyz` mantido como domínio legado, sem receber as URLs definitivas dos
  feeds privados.

Os 119 XMLs incluem os 109 nomes de feed declarados na configuração, sete
agregados legados e três feeds órfãos de fontes removidas. O `main.py` atual
regenera 107 feeds e não regenera os sete agregados, os três órfãos nem as
cópias locais das duas fontes com RSS nativo. Portanto, o processo futuro
não deve publicar cegamente tudo o que encontrar em `feeds/*.xml`.

A lista de objetos publicáveis deve ser construída a partir de:

1. fontes geradas ativas em `config/sources_config.json`;
2. OPML e índice explicitamente habilitados;
3. feeds agregados explicitamente habilitados.

## 5. Arquitetura

```mermaid
flowchart LR
    A["GitHub Actions<br/>a cada seis horas"] --> B["Hidratação do estado atual"]
    B --> C["Scrapers e geração local"]
    C --> D["Validação do snapshot"]
    D --> E["Upload versionado para R2"]
    E --> F["Publicação de current.json"]

    G["Feedbin"] --> H["feeds.paulofehlauer.com"]
    H --> I["Cloudflare Worker<br/>Basic Auth"]
    I --> J["Manifesto do snapshot ativo"]
    J --> K["Objetos privados no R2"]
```

### 5.1 Componentes

#### GitHub Actions

Responsável por:

- hidratar feeds anteriores e estado;
- executar o pipeline existente;
- validar os artefatos;
- montar um snapshot;
- fazer upload ao R2;
- ativar o novo snapshot;
- testar o endpoint publicado;
- aplicar retenção somente depois da ativação bem-sucedida.

#### Cloudflare R2

Responsável por:

- armazenar snapshots imutáveis;
- armazenar o ponteiro para o snapshot ativo;
- fornecer os objetos ao Worker por binding privado;
- manter versões recentes suficientes para rollback.

O bucket não deve ter:

- domínio público conectado;
- URL pública `r2.dev` habilitada;
- permissão anônima;
- credencial compartilhada entre leitura pública e publicação.

#### Cloudflare Worker

Responsável por:

- terminar HTTPS;
- autenticar requisições;
- validar método e caminho;
- resolver o snapshot ativo;
- buscar o objeto no R2;
- responder com cabeçalhos RSS e cache condicional;
- ocultar a existência de caminhos para clientes não autenticados.

O Worker preserva `ETag`, `Last-Modified`, `HEAD` e `304`. Como respostas
streaming do runtime podem usar transferência em blocos, `Content-Length` é
opcional; quando presente, o canário exige que seja correto, e o tamanho e o
SHA-256 do corpo são verificados independentemente.

O Worker não deve:

- executar scraping;
- escrever feeds;
- aceitar uploads públicos;
- listar objetos do bucket para o cliente;
- registrar o cabeçalho `Authorization`;
- depender do GitHub Pages como origem.

#### Feedbin

Responsável por:

- armazenar a URL e as credenciais do feed;
- buscar o XML periodicamente;
- reutilizar ETag ou `Last-Modified` quando suportado;
- manter a experiência de leitura.

## 6. Estrutura de armazenamento

### 6.1 Chaves do R2

```text
current.json

snapshots/
  2026-07-24T18-00-00Z-<sha>/
    manifest.json
    feeds/
      drauzio_feed.xml
      ...
    metadata/
      feeds.opml
      index.html
    history/
      drauzio_varella_history.json
      ...
```

O identificador do snapshot deve incluir:

- data e hora UTC;
- um identificador único ou SHA curto do commit;
- apenas caracteres seguros para chaves e logs.

### 6.2 `current.json`

Exemplo:

```json
{
  "schema_version": 1,
  "run_id": "2026-07-24T18-00-00Z-a1b2c3d",
  "manifest_key": "snapshots/2026-07-24T18-00-00Z-a1b2c3d/manifest.json",
  "manifest_sha256": "<sha256>",
  "published_at": "2026-07-24T18:14:32Z"
}
```

Esse arquivo é o único objeto mutável necessário durante a publicação normal.
Ele só pode ser atualizado depois que o snapshot estiver completo e validado.

### 6.3 `manifest.json`

Exemplo reduzido:

```json
{
  "schema_version": 1,
  "run_id": "2026-07-24T18-00-00Z-a1b2c3d",
  "created_at": "2026-07-24T18:13:58Z",
  "source_revision": "a1b2c3d",
  "canary_path": "/feeds/drauzio_feed.xml",
  "counts": {
    "feeds": 107,
    "history_files": 107,
    "metadata_files": 1,
    "objects": 215,
    "routes": 108
  },
  "objects": {
    "feeds/drauzio_feed.xml": {
      "key": "snapshots/2026-07-24T18-00-00Z-a1b2c3d/feeds/drauzio_feed.xml",
      "content_type": "application/rss+xml; charset=utf-8",
      "size": 43125,
      "sha256": "<sha256>",
      "last_modified": "2026-07-24T18:13:51Z"
    }
  },
  "routes": {
    "/feeds/drauzio_feed.xml": {
      "object_path": "feeds/drauzio_feed.xml"
    }
  }
}
```

Regras:

- o Worker só entrega caminhos presentes no manifesto;
- o manifesto não é servido diretamente;
- cada arquivo tem tamanho e hash;
- contagens esperadas fazem parte da validação;
- o manifesto é imutável depois de ativado.

## 7. Contrato HTTP

### 7.1 Rotas

| Método | Caminho | Comportamento |
|---|---|---|
| `GET` | `/feeds/<feed_file>` | Entrega um RSS autenticado |
| `HEAD` | `/feeds/<feed_file>` | Mesmos cabeçalhos, sem corpo |
| `GET` | `/feeds.opml` | Entrega o OPML privado |
| `HEAD` | `/feeds.opml` | Mesmos cabeçalhos, sem corpo |
| `GET` | `/` | Índice privado, se habilitado; caso contrário `404` |
| `GET`, `HEAD` | `/healthz` | Verificação autenticada do Worker, ponteiro, manifesto e canário |

Qualquer caminho deve passar pela autenticação antes da resolução do objeto.

### 7.2 Respostas de autenticação

Sem credenciais ou com credenciais inválidas:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="Private feeds", charset="UTF-8"
Cache-Control: no-store
Content-Type: text/plain; charset=utf-8
```

O corpo deve ser curto e genérico. Ausência de credencial, usuário inexistente e
senha incorreta devem produzir a mesma resposta observável.

### 7.3 Resposta de feed

```http
HTTP/1.1 200 OK
Content-Type: application/rss+xml; charset=utf-8
Cache-Control: private, no-cache
ETag: "<sha256-ou-etag-do-objeto>"
Last-Modified: <data HTTP>
X-Content-Type-Options: nosniff
```

Regras:

- `If-None-Match` válido retorna `304 Not Modified`;
- `If-Modified-Since` pode ser usado como fallback;
- `HEAD` retorna os mesmos cabeçalhos de `GET`;
- feeds inexistentes retornam `404` somente depois da autenticação;
- métodos não suportados retornam `405` somente depois da autenticação;
- respostas de erro não incluem nomes de bucket, chaves internas ou stack
  traces.

### 7.4 Saúde

`/healthz` deve testar:

1. leitura de `current.json`;
2. leitura e parsing do manifesto;
3. existência de ao menos um objeto canário declarado.

Resposta autenticada:

```json
{
  "status": "ok",
  "run_id": "2026-07-24T18-00-00Z-a1b2c3d"
}
```

Não deve retornar lista de feeds nem detalhes de credenciais.

## 8. Autenticação e segredos

### 8.1 Modelo inicial

Usar:

- um usuário;
- uma senha atual;
- opcionalmente uma segunda senha durante rotação;
- comparação em tempo constante;
- senha com mínimo operacional de 24 bytes e usuário Basic sem `:`;
- HTTPS obrigatório.

O Worker deve aceitar:

```text
usuário correto AND (senha atual OR senha de transição)
```

### 8.2 Segredos do Worker

| Nome | Tipo | Uso |
|---|---|---|
| `BASIC_AUTH_USERNAME` | Secret | Usuário aceito |
| `BASIC_AUTH_PASSWORD_CURRENT` | Secret | Senha principal |
| `BASIC_AUTH_PASSWORD_NEXT` | Secret opcional | Janela de rotação |

O binding do R2 é configurado no Worker, mas não concede acesso público ao
bucket.

### 8.3 Segredos do GitHub Actions

| Nome | Escopo |
|---|---|
| `R2_ACCOUNT_ID` | Variable da conta Cloudflare |
| `R2_ACCESS_KEY_ID` | Token S3 limitado ao bucket |
| `R2_SECRET_ACCESS_KEY` | Token S3 limitado ao bucket |
| `R2_BUCKET` | Variable com o nome do bucket |
| `PRIVATE_FEED_PILOT_ENDPOINT` | Variable com a origem `workers.dev` |
| `PRIVATE_FEED_USERNAME` | Teste canário autenticado |
| `PRIVATE_FEED_PASSWORD` | Teste canário autenticado |

Valores não sensíveis podem ser variables em vez de secrets. Para produção:

```text
FEED_BASE_URL=https://feeds.paulofehlauer.com
```

No piloto, `FEED_BASE_URL` usa a origem temporária `workers.dev` para que o
self-link reflita o endpoint realmente testado. Snapshots completos recusam
qualquer origem diferente de `https://feeds.paulofehlauer.com`.

Se o Worker for implantado por GitHub Actions, usar um token separado e
restrito à edição do Worker. A credencial de publicação de objetos não deve
poder alterar o Worker ou configurações de domínio.

### 8.4 Rotação sem indisponibilidade

1. Gerar nova senha.
2. Configurá-la como `BASIC_AUTH_PASSWORD_NEXT`.
3. Confirmar que senha antiga e nova funcionam.
4. Atualizar as credenciais no Feedbin.
5. Aguardar ao menos uma atualização automática de todos os feeds.
6. Promover a nova senha para `BASIC_AUTH_PASSWORD_CURRENT`.
7. Remover a senha antiga.
8. Confirmar `401` com a senha revogada.

O piloto deve verificar se o Feedbin permite atualização em lote. Até haver
evidência, planejar a rotação como operação potencialmente individual por
assinatura.

## 9. Pipeline de publicação

### 9.1 Fase 1 — checkout e ambiente

1. Entrar no mesmo grupo de concorrência usado por publicação e rollback, sem
   cancelar uma execução já em andamento.
   Usar `queue: max` para não descartar uma publicação pendente.
2. Checkout do código com permissão `contents: read`.
3. Instalação das dependências Python.
4. Configuração das credenciais R2 somente no ambiente do job.
5. Geração de `run_id`.

Publicações concorrentes devem ser serializadas. Caso contrário, uma execução
mais antiga que termine por último pode substituir `current.json` de uma
execução mais nova.

### 9.2 Fase 2 — hidratação

Se existir `current.json`:

1. baixar o manifesto ativo;
2. baixar os feeds gerados ativos para `feeds/`;
3. baixar os arquivos de `history/`;
4. verificar hashes e tamanhos;
5. abortar se o estado obrigatório estiver corrompido ou incompleto.

No primeiro bootstrap, a hidratação pode partir da árvore pública atual, mas
isso deve ser uma operação explícita e única.

Essa fase é obrigatória porque
`merge_articles_with_existing_feed()` depende do XML anterior para impedir
regressões de conteúdo.

### 9.3 Fase 3 — geração

1. Executar `main.py`.
2. Preservar feeds anteriores quando uma fonte falhar, de acordo com as regras
   específicas já existentes.
3. Não ativar um snapshot que elimine silenciosamente feeds por falha de
   coleta.
4. Gerar URLs internas a partir de `FEED_BASE_URL`, não de uma constante do
   GitHub Pages.

### 9.4 Fase 4 — validação local

Validações obrigatórias:

- XML bem-formado;
- raiz RSS esperada;
- `Content-Type` mapeado corretamente;
- quantidade de feeds dentro do intervalo esperado;
- todos os feeds ativos presentes;
- nenhum arquivo fora da allowlist;
- self-link sob o domínio privado;
- GUIDs preservados;
- nenhum segredo em XML, OPML ou HTML;
- nenhum feed vazio;
- limite máximo de tamanho definido;
- hashes e tamanhos calculados;
- `history/` parseável;
- manifesto consistente com os arquivos.

Validações específicas para feeds enriquecidos:

- item conhecido não pode diminuir de conteúdo integral para stub;
- autor e data conhecidos não podem ser substituídos por fallback inválido;
- uma edição nova incompleta pode ser adiada em vez de publicada.

Qualquer falha aborta antes do primeiro upload ativável.

### 9.5 Fase 5 — upload do snapshot

1. Fazer upload de todos os objetos sob a chave do novo `run_id`.
2. Enviar `manifest.json` por último dentro do snapshot.
3. Baixar novamente todos os objetos e verificar hash.
4. Confirmar que o número de objetos corresponde ao manifesto.

Objetos do snapshot são imutáveis. Uma repetição do mesmo `run_id` deve falhar
ou confirmar conteúdo idêntico; nunca sobrescrever silenciosamente conteúdo
diferente.

### 9.6 Fase 6 — ativação

1. Salvar uma cópia local do `current.json` anterior.
2. Confirmar que o ponteiro remoto ainda é o mesmo observado na hidratação.
3. Abortar se outra operação tiver alterado o ponteiro.
4. Escrever o novo `current.json`.
5. Consultar `/healthz`.
6. Consultar um feed canário autenticado.
7. Confirmar `401` sem autenticação.
8. Confirmar XML válido e `200` com autenticação.

Se a verificação pós-ativação falhar:

1. restaurar o `current.json` anterior;
2. repetir o teste canário;
3. marcar o workflow como falho;
4. manter o snapshot defeituoso para diagnóstico até a retenção ou remoção
   manual.

### 9.7 Fase 7 — retenção

Depois da ativação bem-sucedida:

- manter o snapshot ativo;
- manter pelo menos os 27 snapshots anteriores;
- nunca remover o snapshot apontado por `current.json`;
- nunca remover o snapshot anterior durante a mesma execução que publicou um
  novo;
- excluir snapshots excedentes somente depois de listar e validar os
  identificadores.

Com quatro execuções por dia, 28 snapshots correspondem a aproximadamente sete
dias.

## 10. Rollback

### 10.1 Rollback manual

Entrada:

- `run_id` de destino.

Procedimento:

1. confirmar que o snapshot existe;
2. validar o manifesto;
3. validar a allowlist, a modalidade e os hashes de todos os objetos;
4. registrar o `run_id` atualmente ativo;
5. atualizar `current.json`;
6. testar `/healthz`, `401` anônimo e feed canário autenticado;
7. registrar o resultado no resumo do workflow.

### 10.2 Rollback automático

O workflow de publicação pode restaurar o ponteiro anterior apenas quando os
testes pós-ativação da própria execução falharem.

Não deve haver rollback automático baseado em falha de scraping antes da
ativação, pois nesse caso o snapshot anterior já permanece ativo.

## 11. Gerenciamento de fontes

### 11.1 Adicionar

1. Adicionar configuração e scraper conforme o processo atual.
2. Escolher um `feed_file` estável.
3. Validar localmente.
4. Publicar no próximo snapshot.
5. Confirmar a URL autenticada.
6. Cadastrar no Feedbin.
7. Atualizar o OPML privado.

O Worker não exige alteração quando o manifesto controla os caminhos.

### 11.2 Remover

1. Retirar a fonte da configuração.
2. Gerar snapshot sem o caminho.
3. Confirmar `404` autenticado.
4. Retirar a assinatura do Feedbin.
5. Permitir que a retenção elimine o objeto antigo.

Não é necessário apagar imediatamente snapshots históricos.

### 11.3 Renomear

- O nome editorial pode mudar.
- O `feed_file` deve permanecer o mesmo.
- Alterar o caminho equivale a criar uma nova URL de assinatura.

### 11.4 RSS nativos

Baseline:

- `FT Climate Capital` continua usando o RSS da FT;
- `Juliano Spyer` continua usando o RSS oficial da Folha;
- o OPML privado pode misturar URLs upstream e URLs privadas;
- cópias locais antigas desses feeds não entram no manifesto.

Passar fontes nativas pelo Worker exige uma decisão específica, pois adiciona
dependência sem tornar privado o conteúdo já público no upstream.

### 11.5 Feeds agregados

Os extras atualmente presentes são:

- sete agregados legados:
  `estadao_feed.xml`, `folha_feed.xml`, `linkedin_feed.xml`,
  `oglobo_feed.xml`, `outros_feed.xml`, `poder360_feed.xml` e
  `valor_feed.xml`;
- três feeds órfãos:
  `alice_ferraz_feed.xml`, `andre_derviche_feed.xml` e
  `felipe_salto_feed.xml`.

A allowlist atual exclui todos. Uma decisão futura de regenerar agregados
exigirá implementação e allowlist explícitas.

## 12. OPML e índice

### 12.1 OPML

O OPML privado:

- é gerado a partir da configuração ativa;
- usa o domínio privado para feeds gerados;
- mantém URLs upstream para RSS nativos;
- não contém usuário ou senha;
- exige Basic Auth para download;
- deve ser validado em um piloto de importação no Feedbin.

Não assumir que o Feedbin aplicará uma credencial a todos os itens importados.

### 12.2 Índice HTML

Baseline recomendado: não publicar índice HTML.

Se mantido:

- deve exigir autenticação;
- não deve conter credenciais embutidas;
- deve listar apenas itens do manifesto ativo;
- não deve ser indexável;
- deve usar links relativos ou URLs privadas.

## 13. Observabilidade

### 13.1 GitHub Actions

O resumo de cada execução deve registrar:

- `run_id`;
- commit do código;
- snapshot anterior e novo;
- quantidade de fontes;
- quantidade de feeds gerados, preservados, adiados e com erro;
- quantidade e tamanho dos objetos;
- resultado das validações;
- resultado do canário;
- retenção aplicada;
- rollback, se houver.

Nunca registrar:

- credenciais;
- cabeçalhos `Authorization`;
- corpo integral de artigos;
- conteúdo de secrets;
- URLs com credenciais.

### 13.2 Worker

Métricas úteis:

- total de `200`, `304`, `401`, `404` e `5xx`;
- latência;
- falhas de leitura de `current.json`;
- falhas de leitura do manifesto;
- falhas de leitura de objetos.

Evitar logs personalizados por caminho quando não forem necessários, pois os
caminhos revelam o inventário de assinaturas.

### 13.3 Alertas mínimos

- workflow agendado sem sucesso por mais de 12 horas;
- canário pós-publicação falhou;
- Worker retornando `5xx`;
- `current.json` apontando para snapshot inválido;
- uso ou custo da Cloudflare acima do limite definido.

## 14. Ameaças e controles

| Ameaça | Controle |
|---|---|
| Contornar o Worker pelo bucket | Bucket privado, sem domínio e sem `r2.dev` |
| Descobrir feeds por enumeração | Autenticação antes de resolver caminhos |
| Roubo da senha de leitura | Senha forte, HTTPS e rotação em duas fases |
| Ataque de timing | Comparação em tempo constante |
| Vazamento em logs | Nunca registrar `Authorization` ou secrets |
| Token da Action comprometido | Token R2 restrito ao bucket |
| Publicação parcial | Snapshot imutável e `current.json` atualizado por último |
| Stub sobrescrever conteúdo integral | Hidratação obrigatória e validação anti-regressão |
| Cache entregar conteúdo antigo | Sem cache público e revalidação por ETag |
| Path traversal | Lookup apenas em caminhos normalizados presentes no manifesto |
| Exclusão acidental | Retenção e rollback por ponteiro |
| Execuções concorrentes | Grupo de concorrência único e verificação do ponteiro antes da ativação |
| XML permanecer público no Git | Remoção da árvore e desligamento do Pages após migração |
| Conteúdo permanecer no histórico | Decisão separada sobre reescrita de histórico |

## 15. Estimativa de escala e custo

Estimativa conservadora para a implementação atual:

- 107 objetos de feed, 107 históricos e um OPML por execução;
- 215 objetos internos, mais manifesto e ponteiro;
- quatro execuções por dia;
- aproximadamente 26 mil escritas e menos de 31 mil operações Class A por mês,
  incluindo as listagens conservadoras de retenção;
- aproximadamente 800 mil leituras internas por mês, antes das consultas do
  Feedbin;
- aproximadamente 5,3 MB por snapshot;
- aproximadamente 150 MB para 28 snapshots;
- menos de 100 mil requisições mensais do Feedbin em uma hipótese de consulta
  horária dos feeds individuais;
- menos de 300 mil leituras R2 mensais se cada consulta fria ler
  `current.json`, o manifesto e o objeto do feed.

Essa carga deve permanecer dentro das faixas gratuitas atuais de Workers e R2.
Ainda assim:

- usar R2 Standard, não Infrequent Access;
- habilitar alertas de uso;
- revisar preços e limites imediatamente antes da implementação;
- não usar a estimativa como garantia contratual.

## 16. Migração

### Fases 0–4 — concluídas localmente

- auditoria e confirmação do desenho;
- Worker, scripts, testes de falha e allowlist;
- `FEED_BASE_URL` configurável;
- workflows paralelos de piloto e rollback, desabilitados por padrão;
- Actions dos workflows privados fixadas em commits verificados;
- GitHub Pages e workflow público inalterados.

### Fases 5–9 — infraestrutura concluída; publicação piloto em validação

- bucket Standard privado, token restrito, Worker, secrets e ambiente GitHub
  criados com autorização;
- Worker implantado inicialmente em `workers.dev`;
- implementação paralela enviada à `main` com autorização;
- duas execuções manuais do feed piloto realizadas: a primeira parou antes do
  upload; a segunda enviou um snapshot imutável, ativou-o e restaurou a ausência
  do ponteiro quando o canário falhou;
- correções de compatibilidade e diagnóstico validadas localmente antes de nova
  ativação;
- manter GitHub Pages inalterado;

- Confirmar `401` sem credenciais.
- Confirmar `200` e XML válido com credenciais.
- Cadastrar a nova URL no Feedbin.
- Aguardar pelo menos uma atualização automática.
- Publicar uma edição nova e confirmar ingestão.
- Testar senha incorreta.
- Testar rotação de senha.
- Verificar tags, não lidos, duplicação e comportamento do OPML.

O piloto só termina depois de uma atualização automática, não apenas de uma
requisição manual bem-sucedida.

Parar aqui e aguardar confirmação.

### Fases 10–12 — DNS e domínio definitivo

- exportar e inventariar todos os registros da zona atual;
- conferir `A`, `AAAA`, `CNAME`, `MX`, `TXT`, `CAA`, serviços de e-mail e
  DNSSEC;
- reproduzir o redirect atual para o Linktree;
- obter autorização explícita antes dos nameservers;
- depois da troca, confirmar primeiro o redirect do domínio principal;
- somente então criar o Custom Domain `feeds.paulofehlauer.com`;
- validar o Custom Domain e desabilitar `workers.dev` na configuração de
  produção, eliminando a origem temporária alternativa.

### Fase 13 — publicação completa em paralelo

- Hidratar o snapshot privado ativo do piloto; não reiniciar pelo estado
  público se `current.json` já existir.
- Publicar todas as fontes geradas no endpoint privado.
- Validar contagens e URLs.
- Rodar pelo menos um ciclo agendado completo.
- Migrar assinaturas em lotes.
- Manter as URLs públicas antigas durante a verificação.

### Fase 14 — migração e corte

- Confirmar que todas as assinaturas privadas atualizaram.
- Interromper commits de `feeds/` e `history/`.
- Reduzir a permissão do workflow para `contents: read`.
- Remover os artefatos atuais da árvore pública.
- Desativar GitHub Pages.
- Confirmar que as URLs antigas não entregam XML.
- Atualizar README e documentação operacional.

### Fase 15 — pós-migração

- Observar ao menos dois ciclos agendados.
- Confirmar retenção e rollback.
- Fazer uma rotação documentada de credencial em ambiente real.
- Decidir separadamente sobre o histórico Git.
- Encerrar o endpoint paralelo antigo somente depois das verificações.

## 17. Plano de testes

### 17.1 Worker

- Basic Auth ausente, malformado, inválido e válido.
- Comparação de usuário e ambas as senhas.
- `GET`, `HEAD`, método inválido e caminho inválido.
- `200`, `304`, `401`, `404`, `405` e `503`.
- ETag e `Last-Modified`.
- manifesto ausente ou inválido;
- objeto ausente;
- path traversal e variantes de encoding;
- ausência de vazamento em mensagens de erro.
- hash real de `current.json` e do manifesto divergente da metadata.

### 17.2 Publicação

- bootstrap sem snapshot;
- hidratação normal;
- hash divergente;
- scraper com falha;
- feed conhecido com enriquecimento incompleto;
- upload interrompido antes de `current.json`;
- falha depois da ativação;
- rollback automático;
- rollback manual;
- rollback com revalidação semântica do snapshot de destino;
- retenção sem excluir snapshot ativo.

### 17.3 Integração

- Feedbin cadastra com Basic Auth.
- Feedbin busca atualização automaticamente.
- Feedbin recebe `304`.
- Feedbin continua atualizando durante rotação.
- OPML importa URLs esperadas.
- self-links usam o domínio privado.
- GUIDs permanecem estáveis.
- URL pública antiga deixa de responder após o corte.

### 17.4 Evidência local em 2026-07-24

- 29 testes do Worker aprovados;
- 39 testes Python aprovados;
- typecheck TypeScript aprovado;
- `npm audit` sem vulnerabilidades conhecidas e `pip check` sem dependências
  quebradas;
- pacote do Worker aprovado em `wrangler deploy --dry-run` (18,28 KiB,
  4,51 KiB comprimidos, somente o binding privado do R2);
- 107 feeds, 107 históricos e um OPML derivados da allowlist;
- bucket R2 Standard privado e Worker em `workers.dev` criados;
- secrets do Worker, token R2 restrito e ambiente GitHub do piloto configurados
  sem expor seus valores;
- um snapshot imutável de diagnóstico armazenado, sem `current.json` ativo;
- nenhum nameserver, domínio definitivo ou corte executado.

## 18. Critérios de aceite

A implementação só pode ser considerada concluída quando:

- [ ] O Worker é a única origem dos feeds gerados.
- [ ] O bucket R2 não tem acesso público alternativo.
- [ ] Requisições anônimas recebem `401` sem metadados do feed.
- [ ] Requisições autenticadas recebem XML válido e cabeçalhos corretos.
- [ ] O Feedbin executou ao menos uma atualização automática autenticada.
- [ ] O pipeline hidratou estado, publicou snapshot e ativou ponteiro.
- [ ] Uma falha antes da ativação manteve o snapshot anterior.
- [ ] Um rollback foi testado.
- [ ] A proteção contra downgrade de conteúdo foi validada.
- [ ] Nenhum segredo apareceu no Git ou nos logs.
- [ ] OPML e índice não expõem o inventário publicamente.
- [ ] `feeds.paulofehlauer.com` é o domínio definitivo dos feeds.
- [ ] `paulofehlauer.com` continua redirecionando corretamente para o Linktree.
- [ ] Nenhuma URL definitiva de feed usa `fehla.xyz` ou `workers.dev`.
- [ ] O workflow não tem mais permissão de escrita no repositório.
- [ ] `feeds/` e `history/` não são mais commitados publicamente.
- [ ] O GitHub Pages foi desativado.
- [ ] As URLs públicas antigas não entregam XML.
- [ ] Existe procedimento testado de rotação.
- [ ] Existem pelo menos 28 snapshots ou a retenção aprovada.
- [ ] README e runbook refletem a operação real.

## 19. Estrutura implementada

Estrutura local:

```text
worker/
  src/
    index.ts
    auth.ts
    storage.ts
    types.ts
  test/
  wrangler.jsonc
  package.json

scripts/
  private_feed_common.py
  hydrate_private_state.py
  build_snapshot_manifest.py
  validate_snapshot.py
  publish_snapshot.py
  rollback_snapshot.py

config/
  private_publication_allowlist.json

.github/workflows/
  private-feed-pilot.yml
  private-feed-rollback.yml

tests/
  ...
```

Mudanças aplicadas no projeto existente:

- tornar `FEED_BASE_URL` configurável e usar
  `https://feeds.paulofehlauer.com` em produção;
- separar lista de artefatos publicáveis da presença de arquivos no disco;
- adicionar hidratação antes do `main.py`;
- adicionar validação antes do upload;
- adicionar publicação paralela no R2 sem remover o commit/push atual;
- usar `contents: read` nos workflows privados;
- deixar de versionar `feeds/` e `history/` depois do corte;
- atualizar README apenas quando a migração estiver concluída.

## 20. Sequência recomendada de implementação

1. ~~Testes e contrato do Worker.~~
2. ~~Worker local com R2 simulado.~~
3. ~~Scripts de manifesto, validação, hidratação, publicação e rollback.~~
4. ~~Testes locais de falhas e concorrência.~~
5. ~~Workflow paralelo de piloto, desabilitado por padrão.~~
6. ~~Criar recursos Cloudflare após autorização.~~
7. ~~Implantar em `workers.dev` e configurar o ambiente GitHub do piloto.~~
8. Publicar um feed piloto e testar no Feedbin.
9. Parar e aguardar confirmação de atualização automática.
10. Inventariar DNS e obter gate de nameservers.
11. Configurar `feeds.paulofehlauer.com`.
12. Validar o Custom Domain e desabilitar `workers.dev` na configuração de
    produção.
13. Obter gate de publicação completa.
14. Obter gate separado de migração e corte.

Cada fase deve terminar com evidência verificável antes de avançar para a
seguinte. Nenhuma fase autoriza automaticamente a remoção da publicação pública
ou a reescrita do histórico Git.

## 21. Referências externas

Referências revalidadas em 2026-07-24 e que devem ser conferidas novamente
antes da implantação:

- [Feedbin — Password Protected Feeds](https://feedbin.com/help/password-protected-feeds/)
- [Cloudflare Workers — HTTP Basic Authentication](https://developers.cloudflare.com/workers/examples/basic-auth/)
- [Cloudflare Workers — Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
- [Cloudflare Workers — Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Cloudflare Workers — Pricing](https://developers.cloudflare.com/workers/platform/pricing/)
- [Cloudflare R2 — Authentication and API tokens](https://developers.cloudflare.com/r2/api/tokens/)
- [Cloudflare R2 — Consistency model](https://developers.cloudflare.com/r2/reference/consistency/)
- [Cloudflare R2 — Public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [Cloudflare R2 — Pricing](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare DNS — Full setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Cloudflare DNS — Import and export](https://developers.cloudflare.com/dns/manage-dns-records/how-to/import-and-export/)
- [GitHub Actions — Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
