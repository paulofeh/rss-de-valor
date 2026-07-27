# Backlog

## Publicação privada dos feeds com compatibilidade com o Feedbin

**Status:** publicação privada completa ativa no domínio definitivo; o primeiro
ciclo agendado depois da correção dos gates foi validado, a migração das
assinaturas no Feedbin foi concluída e o corte da publicação pública permanece
sujeito a um gate separado
**Prioridade:** antes de ampliar a publicação de feeds com conteúdo integral
**Registrado em:** 2026-07-20
**Especificação detalhada:** [`docs/private-feed-publication-cloudflare-spec.md`](docs/private-feed-publication-cloudflare-spec.md)
**Especificação revisada em:** 2026-07-27
**Domínio decidido:** `feeds.paulofehlauer.com`; `workers.dev` foi usado apenas no piloto e está desabilitado

### Objetivo

Substituir a publicação pública dos feeds gerados por uma distribuição privada, mantendo URLs HTTPS estáveis e compatibilidade com o Feedbin.

Privatizar a entrega reduz a exposição e reforça o caráter de uso pessoal, mas não elimina automaticamente questões autorais relacionadas à reprodução de conteúdo integral.

### Situação atual

- Os XMLs gerados são commitados em `feeds/` pelo GitHub Actions.
- O repositório é público, portanto os XMLs também ficam acessíveis diretamente pelo GitHub e pelo histórico do repositório.
- Os feeds são publicados sem autenticação pelo GitHub Pages.
- Em paralelo, os 106 feeds gerados e o OPML estão publicados de forma privada
  em `https://feeds.paulofehlauer.com`, com Basic Auth e R2 privado.
- O snapshot completo ativo é `30237068708-1-57ac4cee27df`, com 213 objetos
  internos e 107 rotas privadas.
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
  allowlisted; o reparo está implementado e aguarda sua publicação controlada.
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
- **Próximo gate:** observar a estabilização do conjunto privado e obter
  autorização explícita adicional antes de interromper commits públicos,
  remover artefatos ou desligar o GitHub Pages.
- **Preservado:** GitHub Pages, `feeds/`, `history/` e o workflow público
  continuam ativos como contingência; a limpeza no Feedbin não autorizou o
  corte da origem pública.
- Reescrita de histórico continua fora de escopo.

### Fora de escopo dos próximos gates

- Alterar ou adicionar scrapers, incluindo Correio Braziliense e Estado de Minas.
- Mudar a frequência do pipeline.
- Reescrever histórico Git ou apagar publicações existentes sem uma decisão explícita.

### Dependência para futuras fontes com conteúdo integral

Antes de publicar novos feeds integrais — incluindo os feeds de Sérgio Abranches no Estado de Minas e no Correio Braziliense — reavaliar se esta estratégia de privacidade já deve ser implementada. O Estado de Minas deve continuar sendo considerado a fonte principal; o Correio Braziliense, uma fonte secundária com possível duplicação de artigos.
