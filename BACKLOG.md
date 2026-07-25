# Backlog

## Publicação privada dos feeds com compatibilidade com o Feedbin

**Status:** piloto de um feed ativo no domínio definitivo; migração controlada no Feedbin, publicação completa e corte público aguardam gates separados
**Prioridade:** antes de ampliar a publicação de feeds com conteúdo integral
**Registrado em:** 2026-07-20
**Especificação detalhada:** [`docs/private-feed-publication-cloudflare-spec.md`](docs/private-feed-publication-cloudflare-spec.md)
**Especificação revisada em:** 2026-07-25
**Domínio decidido:** `feeds.paulofehlauer.com`, com `workers.dev` apenas no piloto

### Objetivo

Substituir a publicação pública dos feeds gerados por uma distribuição privada, mantendo URLs HTTPS estáveis e compatibilidade com o Feedbin.

Privatizar a entrega reduz a exposição e reforça o caráter de uso pessoal, mas não elimina automaticamente questões autorais relacionadas à reprodução de conteúdo integral.

### Situação atual

- Os XMLs gerados são commitados em `feeds/` pelo GitHub Actions.
- O repositório é público, portanto os XMLs também ficam acessíveis diretamente pelo GitHub e pelo histórico do repositório.
- Os feeds são publicados sem autenticação pelo GitHub Pages.
- Em paralelo, `drauzio_feed.xml` está publicado como piloto privado em
  `https://feeds.paulofehlauer.com`, com Basic Auth e R2 privado.
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
- **Decidido:** usar `feeds.paulofehlauer.com`; `workers.dev` fica restrito ao
  piloto e `fehla.xyz` permanece como domínio legado.
- **Decidido:** OPML privado e índice HTML fora da publicação.
- **Concluído:** bucket R2 Standard privado, Worker em `workers.dev`, secrets do
  Worker, token R2 restrito e ambiente GitHub `private-feed-pilot`.
- **Concluído:** inventário DNS, migração dos nameservers, preservação do
  redirect do domínio principal para o Linktree e Custom Domain
  `feeds.paulofehlauer.com`.
- **Concluído:** snapshot piloto de `drauzio_feed.xml` no domínio definitivo,
  com canários autenticados e anônimos aprovados.
- Atualizar de forma controlada a assinatura piloto no Feedbin para o domínio
  definitivo e o novo par de credenciais.
- Confirmar uma atualização automática do piloto no Feedbin antes de avançar.
- Retirar o par de credenciais anterior e desabilitar `workers.dev` somente
  depois da migração controlada.
- Autorizar publicação completa e, depois, o corte do GitHub Pages.
- Reescrita de histórico continua fora de escopo.

### Fora de escopo dos próximos gates

- Alterar ou adicionar scrapers, incluindo Correio Braziliense e Estado de Minas.
- Mudar a frequência do pipeline.
- Reescrever histórico Git ou apagar publicações existentes sem uma decisão explícita.

### Dependência para futuras fontes com conteúdo integral

Antes de publicar novos feeds integrais — incluindo os feeds de Sérgio Abranches no Estado de Minas e no Correio Braziliense — reavaliar se esta estratégia de privacidade já deve ser implementada. O Estado de Minas deve continuar sendo considerado a fonte principal; o Correio Braziliense, uma fonte secundária com possível duplicação de artigos.
