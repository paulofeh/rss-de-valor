# Backlog

## Publicação privada dos feeds com compatibilidade com o Feedbin

**Status:** migração e corte público concluídos; os 108 feeds gerados são
servidos apenas pelo endpoint privado, o GitHub Pages está desativado e somente
FT Climate Capital permanece diretamente no provedor
**Prioridade:** antes de ampliar a publicação de feeds com conteúdo integral
**Registrado em:** 2026-07-20
**Especificação detalhada:** [`docs/private-feed-publication-cloudflare-spec.md`](docs/private-feed-publication-cloudflare-spec.md)
**Especificação revisada em:** 2026-07-28
**Domínio decidido:** `feeds.paulofehlauer.com`; `workers.dev` foi usado apenas no piloto e está desabilitado

### Objetivo

Substituir a publicação pública dos feeds gerados por uma distribuição privada, mantendo URLs HTTPS estáveis e compatibilidade com o Feedbin.

Privatizar a entrega reduz a exposição e reforça o caráter de uso pessoal, mas não elimina automaticamente questões autorais relacionadas à reprodução de conteúdo integral.

### Situação atual

- Os 108 feeds gerados e o OPML são publicados somente em
  `https://feeds.paulofehlauer.com`, com Basic Auth e R2 privado.
- O workflow público foi removido; `feeds/` e `history/` são estado de runtime
  ignorado pelo Git e hidratado do R2 antes da coleta.
- O GitHub Pages está desativado e as URLs antigas não entregam XML. Os
  artefatos continuam recuperáveis nos commits anteriores porque o histórico
  Git não foi reescrito.
- O snapshot completo ativo é `30398410821-1-ed9924f6e9ad`, com 217 objetos
  internos e 109 rotas privadas.
- O Feedbin confirmou atualização automática autenticada no domínio definitivo,
  com revalidação condicional `304`.
- As 86 assinaturas atuais que ainda apontavam para o GitHub Pages foram
  recriadas manualmente com URLs privadas em cinco lotes de 5, 20, 21, 18 e 22
  itens. Com o piloto de Drauzio, o Feedbin passou a ter 87 assinaturas
  privadas, todas confirmadas como `OK` pelo usuário no cadastro inicial.
- Depois da conferência dos lotes, as 87 assinaturas antigas do GitHub Pages
  foram removidas do Feedbin: 86 correspondiam à configuração atual e uma era
  o órfão legado `futuro_marketing_b2b_linkedin_feed.xml`.
- O export bruto `subscriptions.xml`, que continha credenciais Basic nas URLs
  exportadas pelo Feedbin, foi removido de Downloads e movido para o Lixo pelo
  usuário. Nenhuma credencial foi registrada no repositório; o par atual foi
  deliberadamente mantido sem rotação.
- A credencial de transição foi promovida, os bindings `*_NEXT` foram removidos
  e a origem temporária `workers.dev` foi desabilitada.
- Quatro execuções agendadas de 2026-07-26 foram puladas antes de qualquer
  etapa porque `PRIVATE_FEED_FULL_ENABLED=true` existia somente no Environment,
  indisponível no `jobs.<job_id>.if`.
- A falha fechou antes de hidratação ou upload: `current.json` e o snapshot
  completo anterior permaneceram intactos.
- Em `2026-07-26T23:04Z`, `PRIVATE_FEED_FULL_ENABLED=true` e
  `PRIVATE_FEED_PILOT_ENABLED=false` foram transferidos para variables do
  repositório e os dois duplicados foram removidos do Environment. O workflow
  permaneceu ativo.
- O primeiro ciclo nominal posterior à correção, previsto para
  `2026-07-27T00:47Z`, foi criado pelo GitHub às `04:25:46Z` e terminou com
  sucesso às `04:47:32Z`, sem `workflow_dispatch`. Ele hidratou o snapshot
  anterior, publicou o novo conjunto completo, passou pelos canários e não
  excluiu snapshots na retenção.
- Em 2026-07-27, 12 feeds LinkedIn com baseline já degradado foram regenerados
  localmente, validados com 60 itens completos e enviados à `main` nos commits
  `319a88bb` e `32a47138`. Como a hidratação privada substitui a árvore Git
  pelo snapshot R2 antes dos scrapers, a promoção exige uma execução manual
  allowlisted.
- A primeira tentativa controlada, run `30288789576`, concluiu staging,
  hidratação, restauração e geração, mas foi interrompida antes do upload:
  o baseline degradado continha datas sintéticas diferentes das datas reais
  restauradas. `current.json` permaneceu intacto. O perfil manual agora admite
  essa correção somente nos 12 feeds fixos e somente quando o item remoto tem
  simultaneamente autor fallback e conteúdo visível abaixo de 200 caracteres,
  enquanto o candidato recupera autor e conteúdo completo.
- A segunda execução, run `30290619416`, foi autorizada individualmente e
  terminou com sucesso em 2026-07-27 às `18:06:14Z`. Ela transportou e
  restaurou 12 fontes/24 objetos, hidratou o snapshot anterior
  `30280303014-1-7003ea8af1f3`, validou 213 objetos e 107 rotas, ativou
  atomicamente `30290619416-1-1765aebfb4ff`, passou pelos canários e não
  removeu snapshots na retenção.
- A reconciliação via API da Cloudflare encontrou no novo prefixo 214 chaves:
  106 feeds, 106 históricos, um OPML e `manifest.json`. Os hashes dos 12 feeds
  LinkedIn coincidem com os XMLs corrigidos depois da troca esperada do
  `self-link` público pelo canônico privado. O bucket permanece Standard,
  `r2.dev` está desabilitado e não há Custom Domain ligado diretamente ao R2.
- Depois da ativação, os feeds privados testados anonimamente responderam
  `401`, `workers.dev` respondeu `404`, GitHub Pages permaneceu `200` e o apex
  continuou redirecionando `301` para `https://linktr.ee/paulofehlauer`.
  `PRIVATE_FEED_FULL_ENABLED=true` e `PRIVATE_FEED_PILOT_ENABLED=false`
  permanecem no escopo do repositório e ausentes do Environment.
- O enriquecimento dos feeds Folha entrou na `main` em `1b481286`; o workflow
  público gerou os artefatos atualizados em `0c9581eb`. O primeiro run privado
  posterior, `30301308278`, hidratou e gerou normalmente, mas falhou fechado
  na validação antes do upload. O item de Martin Wolf
  `quem-vencera-a-guerra-dos-neomercantilistas.shtml` mudou de
  `Wed, 22 Jul 2026 20:30:00 -0306` para
  `Wed, 22 Jul 2026 23:30:00 +0000`.
- A diferença é uma correção do antigo uso de
  `datetime.replace(tzinfo=pytz.timezone(...))`: `-03:06` era o offset
  histórico LMT, não o fuso de São Paulo em 2026. O validador corretamente
  recusou a mudança; `current.json` e
  `30290619416-1-1765aebfb4ff` permaneceram ativos.
- A exceção de migração exige modo `full`,
  baseline hidratado, disparo manual e correspondência exata de feed, artigo,
  data antiga e data nova. Ela também exige conteúdo completo no candidato,
  falha se a transição não for observada e não pode ser combinada com o reparo
  LinkedIn.
- O reparo entrou na `main` no commit `70c4243c` e foi executado uma única vez,
  com autorização individual, no run manual `30305737638`. Ele hidratou os 213
  objetos de `30290619416-1-1765aebfb4ff`, validou o perfil
  `martin-wolf-pubdate-2026-07-27`, 213 objetos e 107 rotas, ativou
  `30305737638-1-70c4243cc7a9`, passou pelos canários e concluiu retenção sem
  exclusões.
- A API da Cloudflare confirmou 214 chaves no prefixo novo: 106 feeds, 106
  históricos, um OPML e `manifest.json`, todos em Standard. O SHA-256 do
  objeto `martin_wolf_feed.xml` coincide com o XML completo corrigido, com
  autoria `Martin Wolf` e data `Wed, 22 Jul 2026 23:30:00 +0000`.
- Depois da ativação, a rota privada de Martin Wolf respondeu `401` sem
  credenciais e `Cache-Control: no-store`; `workers.dev` permaneceu `404`,
  GitHub Pages `200` e o apex `301` para o Linktree. Os gates continuam
  `PRIVATE_FEED_FULL_ENABLED=true` e
  `PRIVATE_FEED_PILOT_ENABLED=false` apenas no repositório.
- O usuário cadastrou `martin_wolf_feed.xml` no Feedbin com as credenciais
  privadas existentes, confirmou autoria e conteúdo completos e removeu a
  assinatura nativa da Folha. Esse teste fecha o gate autenticado de Martin
  Wolf; restam 18 assinaturas nativas da Folha no lote atual. Juliano Spyer e
  Sérgio Rodrigues continuam adiados.
- As 18 assinaturas restantes do lote Folha foram então cadastradas com as
  URLs privadas, validadas pelo usuário e tiveram as versões nativas removidas.
  O Feedbin agora acompanha os 106 feeds gerados pelo endpoint privado. FT
  Climate Capital, Juliano Spyer e Sérgio Rodrigues permanecem diretamente nos
  provedores; Sérgio ainda era uma assinatura exclusiva do leitor, fora da
  configuração do repositório.
- A investigação local de 2026-07-27 confirmou que o RSS oficial de Juliano
  congelou em 15/12/2025 enquanto a página da coluna tinha publicação em
  27/07/2026. O candidato troca Juliano para `FolhaScraper`, adiciona Sérgio
  com `FolhaRssFullContentScraper` e gera ambos com 10 itens, autor e conteúdo
  integral.
- Depois dessa mudança, a configuração deriva 109 fontes, 108 feeds gerados,
  um RSS nativo, 217 objetos internos e 109 rotas. A transição exigia uma
  publicação manual com o perfil fixo
  `folha-juliano-sergio-2026-07-27`; ciclos normais continuam falhando
  fechados para qualquer objeto configurado ausente.
- O primeiro ciclo agendado normal posterior ao reparo de Martin Wolf terminou
  com sucesso no run `30327075108`, no commit automático `365187247398`,
  descendente de `9a0133e0`. Sem perfil de reparo ou migração, o job hidratou o
  snapshot anterior `30305737638-1-70c4243cc7a9` e concluiu geração,
  validação, ativação, canários e retenção. A reconciliação do R2 confirmou
  `current.json` apontando para `30327075108-1-365187247398` e 214 chaves no
  prefixo: 106 feeds, 106 históricos, OPML e `manifest.json`, todos em
  Standard. Os checks anônimos permaneceram `401`/`no-store` no endpoint
  privado, `404` em `workers.dev`, `200` no Pages e `301` do apex para o
  Linktree. O gate full executou e o run agendado do piloto foi ignorado,
  confirmando operacionalmente full habilitado e piloto desabilitado. O
  download integral do log não estava disponível sem autenticação de
  administrador; a evidência registrada combina os estados seguros das etapas
  do GitHub com a reconciliação do R2.
- A migração fixa de Juliano Spyer e Sérgio Rodrigues foi publicada com
  sucesso no run manual `30357116106`, a partir do commit
  `51f8690fec06ea89868538aaf43e3e8359ad1341`. O perfil semeou somente os
  quatro objetos autorizados e `current.json` ativou
  `30357116106-1-51f8690fec06` às `2026-07-28T12:18:40Z`.
- A reconciliação independente do R2 encontrou 218 chaves Standard no prefixo
  ativo: 108 feeds, 108 históricos, OPML e `manifest.json`, correspondentes a
  217 objetos internos e 109 rotas. Os hashes remotos de Juliano e Sérgio
  coincidem com os XMLs locais; ambos têm dez itens, autoria explícita,
  conteúdo integral e self-link canônico.
- Depois da ativação, as duas rotas privadas responderam `401` e
  `Cache-Control: no-store` sem credenciais; `workers.dev` permaneceu `404`,
  GitHub Pages `200` e o apex `301` para o Linktree. Havia 13 snapshots, todos
  abaixo do teto de retenção de 28. O perfil de migração foi consumido e não
  pode ser reutilizado.
- O usuário cadastrou Juliano Spyer e Sérgio Rodrigues com as credenciais
  privadas existentes, validou ambos no Feedbin e removeu as duas assinaturas
  nativas. O leitor passou a acompanhar os 108 feeds gerados no endpoint
  privado; FT Climate Capital é a única assinatura direta no provedor.
- Tornar somente o repositório privado não protege necessariamente um site do GitHub Pages.
- Colocar um proxy autenticado diante do Pages sem remover a origem pública não resolve a exposição.

### Estratégia recomendada

Usar um endpoint HTTPS protegido por **HTTP Basic Auth**, formato suportado nativamente pelo Feedbin.

Arquitetura de referência:

1. O GitHub Actions executa os scrapers e gera os XMLs a cada seis horas.
2. Os XMLs são enviados para um serviço de publicação privado, como um Cloudflare Worker com armazenamento privado ou assets protegidos.
3. O endpoint exige HTTP Basic Auth antes de entregar qualquer feed.
4. Usuário, senha e credenciais de implantação ficam exclusivamente em secrets; nunca no código, nos XMLs ou nos logs.
5. O Feedbin assina as URLs HTTPS normais e armazena as credenciais solicitadas no cadastro.
6. Depois da validação no Feedbin, o GitHub Pages é desativado e os XMLs deixam de ser publicados no repositório público.

### Topologia decidida

Foi escolhida a alternativa **código público e artefatos privados**: manter o
código no repositório atual, parar de versionar `feeds/` somente no gate de
corte e publicar os XMLs apenas no endpoint autenticado.

### Sequência segura de migração

1. Confirmar provedor e topologia do repositório; o domínio de produção já foi
   definido como `feeds.paulofehlauer.com`.
2. Criar o endpoint autenticado sem desligar ainda a publicação atual.
3. Publicar uma cópia de teste de um único feed.
4. Confirmar que uma requisição sem credenciais recebe `401 Unauthorized` e `WWW-Authenticate: Basic`.
5. Confirmar que uma requisição autenticada recebe `200 OK`, XML válido e `Content-Type: application/rss+xml`.
6. Cadastrar o feed protegido no Feedbin e aguardar pelo menos uma atualização automática bem-sucedida.
7. Migrar as demais assinaturas e validar OPML, URLs internas e GUIDs.
8. Interromper o commit de `feeds/` no repositório público.
9. Desativar o GitHub Pages e verificar que as URLs antigas não entregam mais os XMLs.
10. Validar uma execução agendada completa e documentar recuperação e rotação de credenciais.

### Critérios de aceite

- O Feedbin cadastra e atualiza os feeds protegidos usando HTTP Basic Auth.
- Requisições sem credenciais não recebem XML, trechos ou metadados dos feeds.
- Todos os feeds são servidos por HTTPS com XML e cabeçalhos corretos.
- O agendamento de seis horas continua funcionando sem intervenção manual.
- Nenhum segredo aparece no repositório, nos artefatos públicos ou nos logs do GitHub Actions.
- As URLs públicas antigas deixam de servir os feeds.
- Os XMLs novos não são commitados em uma área pública.
- Existe procedimento documentado para trocar a senha sem perder as assinaturas do Feedbin.

### Gates que permanecem abertos

- **Decidido:** Cloudflare Worker, R2 Standard privado e código público.
- **Decidido:** usar `feeds.paulofehlauer.com`; `workers.dev` ficou restrito ao
  piloto, foi desabilitado depois da validação e `fehla.xyz` permanece como
  domínio legado.
- **Decidido:** OPML privado e índice HTML fora da publicação.
- **Concluído:** bucket R2 Standard privado, Worker em `workers.dev`, secrets do
  Worker, token R2 restrito e ambiente GitHub `private-feed-pilot`.
- **Concluído:** inventário DNS, migração dos nameservers, preservação do
  redirect do domínio principal para o Linktree e Custom Domain
  `feeds.paulofehlauer.com`.
- **Concluído:** snapshot piloto de `drauzio_feed.xml` no domínio definitivo,
  com canários autenticados e anônimos aprovados.
- **Concluído:** assinatura piloto recriada no Feedbin com o novo par; atualização
  automática observada em 2026-07-25 às 15:28:38 BRT, com `If-None-Match`,
  `If-Modified-Since`, resposta `304` e resultado `ok`.
- **Concluído:** novo par promovido aos bindings principais, bindings de
  transição removidos e `workers.dev` desabilitado; a origem temporária passou
  a responder `404`.
- **Concluído em 2026-07-25:** commit `bc9e2a60`, push para `main` e primeira
  execução manual de **Private feed publication**; o snapshot
  `30170506858-1-bc9e2a6055ac` hidratou o piloto, validou 213 objetos e 107
  rotas, ativou o novo ponteiro e passou pelos canários e retenção.
- **Falha fechada em 2026-07-26:** embora
  `PRIVATE_FEED_FULL_ENABLED=true`,
  `PRIVATE_FEED_FULL_CANARY_FEED_FILE=drauzio_feed.xml` e
  `PRIVATE_FEED_PILOT_ENABLED=false` estejam confirmados no Environment, os
  runs agendados `30187551489`, `30195696122`, `30205646460` e `30217759033`
  terminaram como `skipped`, sem steps.
- **Preservado:** a API do R2 confirmou nenhum objeto sob os quatro prefixos de
  run; `current.json` continuou com `Last-Modified`
  `2026-07-25T19:08:56.771Z`, e o snapshot completo ativo conserva 213 objetos
  mais o manifesto.
- **Corrigido em 2026-07-26:** os gates foram transferidos para variables do
  repositório, preservando `PRIVATE_FEED_FULL_ENABLED=true` e
  `PRIVATE_FEED_PILOT_ENABLED=false`; os duplicados do Environment foram
  removidos e as demais variables permaneceram intactas.
- **Concluído em 2026-07-27:** o run agendado `30237068708`, no modo `full`,
  hidratou `30170506858-1-bc9e2a6055ac`, validou 213 objetos e 107 rotas,
  ativou `30237068708-1-57ac4cee27df`, passou pelos canários e executou a
  retenção sem exclusões. A API do R2 confirmou 214 chaves no prefixo do
  snapshot e `current.json` atualizado depois do upload.
- **Concluído em 2026-07-27:** as 86 assinaturas públicas atuais foram
  migradas manualmente em cinco lotes; somadas ao piloto, são 87 assinaturas
  privadas confirmadas como `OK`.
- **Concluído em 2026-07-27:** as 87 assinaturas antigas do GitHub Pages foram
  excluídas do Feedbin, incluindo o órfão legado
  `futuro_marketing_b2b_linkedin_feed.xml`.
- **Concluído em 2026-07-28:** o primeiro ciclo agendado normal posterior ao
  reparo de Martin Wolf terminou com sucesso no run `30327075108` e ativou
  `30327075108-1-365187247398`, sem perfil de reparo ou migração.
- **Concluído em 2026-07-28:** o run manual `30357116106` ativou
  `30357116106-1-51f8690fec06`, com 217 objetos internos e 109 rotas. O perfil
  fixo de Juliano Spyer e Sérgio Rodrigues foi consumido e não deve ser
  selecionado novamente.
- **Concluído em 2026-07-28:** Juliano Spyer e Sérgio Rodrigues foram
  validados no Feedbin e suas assinaturas nativas foram removidas; o leitor
  agora acompanha os 108 feeds gerados pelo endpoint privado.
- **Concluído em 2026-07-28:** a janela de estabilização atravessou dois ciclos
  agendados normais, `30371575582` e `30394804773`, sem perfil de reparo ou
  migração. Eles hidrataram sucessivamente os snapshots anteriores, validaram
  217 objetos e 109 rotas, ativaram
  `30371575582-1-e3ff37944524` e
  `30394804773-1-1204dfd6414d`, passaram pelos canários e aplicaram retenção
  sem exclusões.
- **Observação operacional:** o segundo ciclo preservou os feeds anteriores
  diante de `404` no RSS do Bloomberg Green, `404` na página de Fernando
  Reinach e respostas `429` durante enriquecimentos do LinkedIn. A validação
  integral do snapshot e os canários continuaram aprovados.
- **Concluído em 2026-07-28:** a autorização explícita de corte foi executada
  no commit `ed9924f6`: o workflow público foi removido, `feeds/` e `history/`
  saíram da árvore atual e passaram a ser ignorados, e o GitHub Pages foi
  desativado sem reescrever o histórico.
- **Validado em 2026-07-28:** o run manual pós-corte `30398410821` hidratou os
  217 objetos de `30394804773-1-1204dfd6414d`, validou 217 objetos e 109
  rotas e ativou `30398410821-1-ed9924f6e9ad`. O prefixo contém 218 chaves:
  108 feeds, 108 históricos, OPML e manifesto. Canários e retenção passaram.
- **Reconciliação final:** domínio privado em `401` e `no-store` sem
  credenciais, `workers.dev` em `404`, Pages e arquivo bruto da árvore atual
  em `404`, apex em `301` para o Linktree, `full=true` e `pilot=false`.
- **Próximo gate:** observar os próximos ciclos agendados pós-corte e manter
  rollback, retenção e rotação sob acompanhamento operacional.
- Reescrita de histórico continua fora de escopo.

### Fora de escopo dos próximos gates

- Alterar ou adicionar scrapers, incluindo Correio Braziliense e Estado de Minas.
- Mudar a frequência do pipeline.
- Reescrever histórico Git ou apagar publicações existentes sem uma decisão explícita.

### Dependência para futuras fontes com conteúdo integral

Antes de publicar novos feeds integrais — incluindo os feeds de Sérgio Abranches no Estado de Minas e no Correio Braziliense — reavaliar se esta estratégia de privacidade já deve ser implementada. O Estado de Minas deve continuar sendo considerado a fonte principal; o Correio Braziliense, uma fonte secundária com possível duplicação de artigos.
