# Operação da publicação privada de feeds

**Estado em 2026-08-12:** bucket R2 Standard privado, Worker, DNS, Custom
Domain `feeds.paulofehlauer.com` e ambiente GitHub estão operacionais sem
exposição de secrets. A publicação completa do run `31599855268` está ativa
com 219 objetos internos e 110 rotas privadas. Os perfis manuais de Juliano
Spyer/Sérgio Rodrigues e Duda Herriot foram consumidos e não podem ser
reutilizados. Canários autenticados e anônimos passaram; `workers.dev`
permanece desabilitado e o apex continua redirecionando ao Linktree. O endpoint
privado publica 109 feeds gerados; FT Climate Capital é a única fonte direta no
provedor. O workflow público foi removido, os artefatos saíram da árvore atual
e o GitHub Pages está desativado.

Este runbook complementa a
[especificação](private-feed-publication-cloudflare-spec.md). Ele não autoriza
por si só implantação, compra, troca de nameservers, publicação completa ou
corte do GitHub Pages.

## 1. Gates e autorizações

Foram concluídos com autorização explícita: atualização da assinatura piloto no
Feedbin, rotação do par de credenciais e desativação de `workers.dev`.

A publicação completa foi autorizada e executada manualmente em 2026-07-25. O
workflow entrou na `main` pelo commit `bc9e2a60` e publicou
`30170506858-1-bc9e2a6055ac`. Em 2026-07-26, os runs agendados `30187551489`,
`30195696122`, `30205646460` e `30217759033` foram pulados antes de qualquer
step. Com autorização explícita, os gates foram movidos para o nível do
repositório, mantendo `PRIVATE_FEED_FULL_ENABLED=true` e
`PRIVATE_FEED_PILOT_ENABLED=false`; os duplicados do Environment foram
removidos. A exigência de observar um ciclo completo sem substituí-lo por uma
reexecução manual foi satisfeita pelo run agendado `30237068708` em
2026-07-27.

A migração das demais assinaturas foi autorizada e concluída em 2026-07-27. O
corte público recebeu autorização explícita separada e foi concluído em
2026-07-28, sem reescrita do histórico Git.

O gate de espera foi satisfeito por uma atualização automática do Feedbin. Em
futuras rotações, continuar exigindo essa evidência e não avançar apenas porque
uma requisição manual funcionou. A janela de estabilização posterior à migração
foi satisfeita pelos runs agendados `30371575582` e `30394804773`, ambos sem
perfil de reparo ou migração. O run manual pós-corte `30398410821` comprovou
que o estado é hidratado exclusivamente do snapshot privado.

## 2. Modelo implementado

- O Worker autentica antes de examinar método, caminho ou R2.
- O bucket só é acessado pelo binding privado do Worker e pelo token S3 de
  publicação.
- Cada snapshot contém todos os feeds gerados, históricos e o OPML necessários
  à próxima execução.
- As rotas públicas são separadas dos objetos armazenados. No piloto, apenas
  um feed é roteável.
- `current.json` é o único ponteiro mutável.
- Objetos e manifesto são escritos com `If-None-Match`; o ponteiro é trocado
  com `If-Match` ou `If-None-Match`.
- Uma falha antes da ativação não altera o ponteiro.
- Uma falha de canário depois da ativação restaura o ponteiro anterior.
- Publicação e rollback compartilham o grupo
  `private-feed-r2-publication`, com fila serial.
- Actions externas dos workflows privados são fixadas por SHA completo e
  identificadas pelo release correspondente.
- A retenção mantém 28 snapshots e protege o ativo e o imediatamente anterior.

O snapshot ativo deriva 109 feeds, 109 históricos e um OPML: 219 objetos
internos e 110 rotas. O único `ExistingRssScraper` restante é FT Climate
Capital. XMLs agregados ou órfãos presentes no disco não entram no snapshot.

## 3. Verificação local

Usar sempre o ambiente virtual do repositório:

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

O último comando apenas empacota e valida; não deve ser substituído por um
deploy real antes do gate.

## 4. Recursos a criar depois de autorização

| Recurso | Configuração | Motivo |
|---|---|---|
| R2 | bucket Standard `rss-de-valor-private-feeds` | snapshots privados |
| Worker | `rss-de-valor-private-feeds` | única porta de leitura |
| Token R2 | Object Read & Write, restrito ao bucket | hidratar, publicar e fazer rollback |
| Ambiente GitHub | `private-feed-pilot` | isolar variables e secrets privados; reutilizado pela publicação completa para não duplicar secrets não recuperáveis |

Habilitar R2 pode exigir aceitar termos de cobrança ou cadastrar um meio de
pagamento, mesmo que a escala estimada fique na faixa gratuita. Explicar isso
e obter autorização antes de prosseguir.

No bucket:

- usar armazenamento Standard;
- manter **Public Development URL (`r2.dev`) desabilitada**;
- não conectar Custom Domain ao bucket;
- não criar política anônima;
- confirmar essas três condições novamente depois da criação.

O domínio `workers.dev` do piloto pertence ao Worker, não ao bucket.

## 5. Secrets e variables

Nunca enviar valores pela conversa, colocá-los na linha de comando ou incluí-los
em URLs. Usar prompts interativos, o painel da Cloudflare e GitHub Environment
Secrets.

### Worker secrets

- `BASIC_AUTH_USERNAME`
- `BASIC_AUTH_PASSWORD_CURRENT`
- `BASIC_AUTH_USERNAME_NEXT`, apenas durante rotação completa
- `BASIC_AUTH_PASSWORD_NEXT`, apenas durante rotação

O Wrangler pode recebê-los interativamente, um de cada vez:

```bash
npx wrangler secret put BASIC_AUTH_USERNAME
npx wrangler secret put BASIC_AUTH_PASSWORD_CURRENT
```

Durante uma rotação completa, configurar também
`BASIC_AUTH_USERNAME_NEXT` e `BASIC_AUTH_PASSWORD_NEXT` pelo mesmo mecanismo.

O usuário deve ter no máximo 128 bytes, sem `:` nem caracteres de controle. A
senha deve ter entre 24 e 1.024 bytes; usar preferencialmente pelo menos 32
caracteres aleatórios gerados por um gerenciador de senhas. Worker, publicação
e rollback falham fechados se essa política não for atendida.

### GitHub Environment Secrets

- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `PRIVATE_FEED_USERNAME`
- `PRIVATE_FEED_PASSWORD`

### GitHub variables

No nível do repositório:

- `PRIVATE_FEED_FULL_ENABLED`
- `PRIVATE_FEED_PILOT_ENABLED`

No Environment `private-feed-pilot`:

- `R2_ACCOUNT_ID`
- `R2_BUCKET`
- `PRIVATE_FEED_PILOT_ENDPOINT`
- `PRIVATE_FEED_PILOT_FEED_FILE`
- `PRIVATE_FEED_FULL_CANARY_FEED_FILE`

Os dois gates foram transferidos em `2026-07-26T23:04Z`, pois são usados
diretamente em `jobs.<job_id>.if` e não podem existir somente no Environment:
esse nível só fica disponível depois que o runner inicia o job. Os duplicados
foram removidos para evitar fontes operacionais ambíguas. Secrets e variables
consumidos somente pelos steps continuam no Environment.

`PRIVATE_FEED_PILOT_ENDPOINT` deve ser a origem HTTPS completa
`https://feeds.paulofehlauer.com`, sem credenciais e sem caminho. A origem
`workers.dev` foi usada somente no bootstrap do piloto e não deve ser
reativada. O workflow usa a variável como `FEED_BASE_URL`; em publicação
completa, o mesmo domínio canônico continua obrigatório.

Manter `PRIVATE_FEED_PILOT_ENABLED=false`: mesmo uma execução manual do workflow
de piloto deve falhar fechada quando essa variável estiver desabilitada. Na
operação atual, `PRIVATE_FEED_FULL_ENABLED=true` no nível do repositório mantém
a agenda completa ativa e
`PRIVATE_FEED_FULL_CANARY_FEED_FILE=drauzio_feed.xml` define o canário. Em um
novo bootstrap, o gate completo deve começar em `false` até uma execução manual
bem-sucedida; não aplicar essa instrução retroativamente à produção já
validada. Os dois workflows reutilizam o ambiente `private-feed-pilot`,
evitando copiar ou revelar os secrets existentes.

## 6. Implantação do piloto

Executar somente depois dos gates de recursos e acesso:

1. criar e auditar o bucket;
2. validar novamente os testes e o dry-run;
3. implantar o Worker em `workers.dev`;
4. configurar os dois secrets obrigatórios do Worker;
5. confirmar `401` anônimo antes de existir snapshot;
6. configurar o ambiente `private-feed-pilot` no GitHub;
7. escolher explicitamente um feed gerado da configuração;
8. executar manualmente **Private feed pilot**.

Na primeira execução, marcar `allow_bootstrap_from_local=true`. Isso só autoriza
o bootstrap se `current.json` ainda estiver ausente. Nas execuções seguintes,
usar `false`.

Manter `PRIVATE_FEED_PILOT_ENABLED=false` até a publicação manual e os canários
terem passado. Quando for necessário testar atualização automática, mudar para
`true`; o workflow agendado roda a cada seis horas sem alterar o workflow
público existente.

Resultados esperados:

- anônimo: `401`, desafio Basic e nenhum metadado do feed;
- credencial errada: a mesma resposta `401`;
- credencial atual: `200`, RSS válido e cache privado;
- `HEAD`: mesmos metadados de `GET`, sem corpo;
- `If-None-Match`: `304`, sem corpo;
- caminho não permitido: `404` somente depois da autenticação;
- `/healthz`: `200` com o `run_id` ativo.

Não publicar o OPML no piloto. Não incluir usuário ou senha na URL cadastrada no
Feedbin; o próprio Feedbin deve solicitar as credenciais.

## 7. Publicação e hidratação

Ordem executada pelo workflow:

1. hidratar o snapshot apontado por `current.json`;
2. validar hash e tamanho de todos os objetos antes de substituir arquivos
   locais;
3. executar `main.py`;
4. validar XML, OPML, históricos, GUIDs, self-links, allowlist, conteúdo
   enriquecido e ausência de secrets;
5. montar um diretório imutável em `.private-feed-build/<run_id>`;
6. enviar objetos e manifesto;
7. baixar novamente todos os objetos e confirmar os hashes;
8. reler o ponteiro observado na hidratação;
9. ativar por escrita condicional;
10. executar canários anônimo e autenticado;
11. aplicar retenção.

Ao remover uma fonte, o snapshot ativo ainda pode conter o feed e o histórico
legados. A hidratação aceita esses objetos extras somente como estado anterior,
não os copia e continua recusando qualquer objeto atualmente exigido que esteja
ausente. A montagem do novo snapshot usa a allowlist atual exata.

Se um scraper falhar, o feed hidratado anterior permanece no diretório. A
validação impede que falhas de enriquecimento da Folha ou do LinkedIn reduzam
um item conhecido a um stub. A normalização do `self-link` ocorre depois de
todos os scrapers e independe do sucesso deles; assim, um XML preservado migra
da origem anterior para o endpoint ativo sem perder itens, descrições ou GUIDs.

### Reparo controlado de baseline LinkedIn

Um baseline já degradado não pode ser corrigido pela proteção anti-downgrade:
a hidratação substitui a árvore Git pelo snapshot ativo antes que
`merge_articles_with_existing_feed()` seja executado. Para esse caso, o
workflow completo oferece o input manual `repair_linkedin_baseline`, falso por
padrão e ignorado em execuções agendadas.

O reparo é limitado pelo código aos 12 newsletters identificados em
2026-07-27. Ele transporta exatamente 24 objetos da revisão Git confirmada:
um feed e um histórico por fonte. Antes da hidratação, o utilitário exige cinco
itens por feed, autor conhecido, conteúdo não resumido, URLs LinkedIn válidas,
links únicos, histórico coerente e `self-link` HTTPS sem credenciais. Um
manifesto temporário registra tamanho e SHA-256 de cada objeto.

Depois da hidratação normal e integral do R2, o utilitário relê e verifica esse
manifesto e restaura somente os 24 caminhos explicitamente allowlisted. Só
então `main.py` é executado. O baseline de validação continua sendo o snapshot
remoto anterior, de forma que a publicação ainda precisa provar que não houve
downgrade nos outros objetos. Qualquer divergência antes da ativação encerra o
run sem alterar `current.json`; os canários e o rollback automático
pós-ativação permanecem os mesmos.

O baseline degradado também contém datas sintéticas produzidas pela coleta que
falhou. Quando o mesmo link e GUID reaparecem com a data real, o perfil nomeado
`linkedin-full-content-2026-07-27` pode aceitar a correção. A exceção só vale
para os 12 nomes fixos, em modo `full`, com baseline hidratado, e apenas se o
item anterior tiver simultaneamente autor fallback e menos de 200 caracteres
visíveis, enquanto o candidato tiver autor conhecido e pelo menos 200
caracteres visíveis. Sem o perfil, fora da allowlist ou para um item já
completo, qualquer mudança de data continua fatal.

Na primeira tentativa, run `30288789576`, staging, hidratação, restauração e
geração foram concluídos. A validação recusou as 12 diferenças de data antes
do upload; portanto nenhum objeto foi enviado e `current.json` não foi
alterado.

A nova execução foi autorizada individualmente e concluída no run
`30290619416`, de `2026-07-27T17:44:49Z` a `18:06:14Z`, usando o commit
`1765aebf`. Ela registrou:

- staging e restauração de 12 fontes e 24 objetos com o perfil
  `linkedin-full-content-2026-07-27`;
- hidratação de 213 objetos do snapshot anterior
  `30280303014-1-7003ea8af1f3`;
- geração de 106 fontes e validação de 213 objetos e 107 rotas;
- ativação de `30290619416-1-1765aebfb4ff`;
- canários autenticados e anônimos aprovados;
- retenção concluída sem exclusões.

Na reconciliação, a API da Cloudflare listou 214 chaves no prefixo — os 213
objetos do manifesto mais `manifest.json` — e `current.json` foi atualizado às
`18:00:06Z`, antes da conclusão dos canários. Os hashes dos 12 feeds no R2
coincidiram com os XMLs corrigidos após somente substituir o `self-link` do
Pages pelo canônico privado. O bucket continuou Standard, com `r2.dev`
desabilitado e nenhum Custom Domain próprio.

Os testes anônimos posteriores receberam `401` tanto no canário de Drauzio
quanto em `ia_sem_hype_linkedin_feed.xml`; `workers.dev` retornou `404`, o
Pages permaneceu `200` e o apex preservou o `301` para o Linktree. Os gates
continuaram `PRIVATE_FEED_FULL_ENABLED=true` e
`PRIVATE_FEED_PILOT_ENABLED=false` apenas no escopo do repositório.

O reparo de 2026-07-27 está concluído. Não repetir esse perfil como rotina:
execuções manuais normais devem deixar `repair_linkedin_baseline=false`.

Para executar o reparo:

1. confirmar que os 12 pares corrigidos estão commitados em `main`;
2. abrir **Private feed publication** em GitHub Actions;
3. selecionar **Run workflow**;
4. marcar `confirm_full_publication=true`;
5. marcar `repair_linkedin_baseline=true`;
6. conferir no log os resultados `staged` e `restored`, ambos com 12 fontes e
   24 objetos;
7. conferir que a validação usou o perfil
   `linkedin-full-content-2026-07-27`;
8. aguardar validação, ativação, canários e retenção;
9. reconciliar `current.json`, o novo prefixo e os feeds autenticados;
10. deixar `repair_linkedin_baseline=false` em execuções manuais normais.

Não usar esse input para adicionar fontes, bootstrap, rollback ou reparos
genéricos. Uma mudança na lista exige revisão de código, testes e novo gate.

### Reparo controlado da data de Martin Wolf

O run agendado `30301308278`, no descendente `0c9581eb` da correção Folha,
hidratou e gerou os feeds, mas parou em **Validate and stage the complete
snapshot**. O item
`quem-vencera-a-guerra-dos-neomercantilistas.shtml` existia no baseline como
`Wed, 22 Jul 2026 20:30:00 -0306` e passou a
`Wed, 22 Jul 2026 23:30:00 +0000`.

O `-03:06` não era o fuso de São Paulo em 2026: era o offset histórico LMT
introduzido pelo uso antigo de `replace(tzinfo=pytz.timezone(...))`. O horário
corrigido representa 20h30 em São Paulo como 23h30 UTC. A proteção de data
agiu corretamente e bloqueou o run antes do upload; `current.json` continuou
apontando para `30290619416-1-1765aebfb4ff`.

O workflow oferece `repair_martin_wolf_pubdate`, falso por padrão e ignorado
em execuções agendadas. O perfil
`martin-wolf-pubdate-2026-07-27` aceita somente:

- `martin_wolf_feed.xml`;
- a URL integral exata desse artigo;
- a data antiga e a data nova registradas acima;
- um candidato com autor conhecido e pelo menos 200 caracteres visíveis;
- modo `full` com baseline hidratado.

O run falha se qualquer valor divergir ou se a transição não for encontrada.
Assim, o perfil também falha fechado se for selecionado novamente depois que
o snapshot ativo já contiver a data corrigida. Os reparos de Martin Wolf e
LinkedIn são mutuamente exclusivos.

O reparo foi executado uma única vez, com autorização individual, no run
`30305737638`, baseado no commit `70c4243c`, de `21:10:37Z` a `21:35:19Z`.
Os inputs efetivos foram `confirm_full_publication=true`,
`repair_linkedin_baseline=false` e `repair_martin_wolf_pubdate=true`.

Evidência operacional:

- hidratação de 213 objetos do snapshot anterior
  `30290619416-1-1765aebfb4ff`;
- processamento de 106 fontes, com proteção anterior preservada nas falhas
  transitórias de coleta;
- perfil `martin-wolf-pubdate-2026-07-27`, 213 objetos e 107 rotas validados;
- ativação de `30305737638-1-70c4243cc7a9`;
- canários autenticados e anônimos aprovados;
- retenção concluída sem exclusões.

A API do R2 confirmou 214 chaves no prefixo: 106 feeds, 106 históricos, um OPML
e `manifest.json`, todos em Standard. O hash do objeto
`martin_wolf_feed.xml` é idêntico ao XML completo corrigido, com autoria
`Martin Wolf` e `Wed, 22 Jul 2026 23:30:00 +0000`. `current.json` recebeu novo
ETag às `21:29:59.734Z`; `r2.dev` permaneceu desabilitado e não há Custom
Domain ligado diretamente ao bucket.

A rota privada de Martin Wolf respondeu anonimamente `401`, `no-store` e o
desafio Basic esperado. `workers.dev` continuou `404`, GitHub Pages `200` e o
apex `301` para o Linktree. Os gates permaneceram
`PRIVATE_FEED_FULL_ENABLED=true` e `PRIVATE_FEED_PILOT_ENABLED=false` somente
no repositório.

Não selecionar novamente `repair_martin_wolf_pubdate`: o baseline ativo já tem
a data corrigida e o perfil falharia por não observar a transição. Execuções
manuais normais devem manter os dois inputs de reparo como `false`; execuções
agendadas continuam sem perfil.

O usuário cadastrou o feed privado de Martin Wolf no Feedbin, confirmou autoria
e conteúdo completos e removeu a assinatura nativa. O gate autenticado está
concluído. Restam 18 assinaturas nativas da Folha no lote atual; cadastrar cada
URL privada com o mesmo par de credenciais e remover a origem nativa somente
depois da validação individual. Juliano Spyer e Sérgio Rodrigues ficaram
adiados e não pertenciam àquele lote.

As 18 migrações restantes foram concluídas pelo usuário e as versões nativas
correspondentes foram removidas. O estado esperado no Feedbin é agora:

- 106 feeds gerados em `https://feeds.paulofehlauer.com`;
- FT Climate Capital, Juliano Spyer e Sérgio Rodrigues diretamente nos
  provedores;
- nenhuma assinatura nativa remanescente para os 19 feeds Folha migrados.

Essa observação terminou com sucesso em 2026-07-28 no run agendado
`30327075108`, no commit automático `365187247398`, descendente de
`9a0133e0`. Sem perfil de reparo ou migração, o job hidratou
`30305737638-1-70c4243cc7a9` e concluiu geração, validação, ativação, canários
e retenção. A reconciliação do R2 confirmou `current.json` apontando para
`30327075108-1-365187247398` e 214 chaves Standard: 106 feeds, 106
históricos, OPML e `manifest.json`, equivalentes aos 213 objetos internos e
107 rotas.

Os checks anônimos permaneceram `401`/`no-store` no endpoint privado, `404`
em `workers.dev`, `200` no Pages e `301` do apex para o Linktree. O job full
agendado executou e o piloto agendado no mesmo commit foi ignorado,
confirmando operacionalmente full habilitado e piloto desabilitado. Como o
download integral do log exigia autenticação administrativa indisponível, o
registro usa os estados seguros das etapas do GitHub e a reconciliação
independente do R2.

### 7.5 Migração de Juliano Spyer e Sérgio Rodrigues

A investigação de 2026-07-27 confirmou que o RSS de Juliano está congelado em
15/12/2025, embora a página da coluna tenha artigo em 27/07/2026. Sérgio
Rodrigues tem RSS ativo. A produção usa `FolhaScraper` para Juliano e
`FolhaRssFullContentScraper` para Sérgio; os dois artefatos locais têm dez
itens, autoria explícita, conteúdo integral, GUIDs iguais às URLs e self-links
canônicos.

Antes da migração, o snapshot ativo não possuía:

- `feeds/juliano_spyer_feed.xml`;
- `history/juliano_spyer_history.json`;
- `feeds/sergio_rodrigues_feed.xml`;
- `history/sergio_rodrigues_history.json`.

A primeira publicação foi executada manualmente em `Private feed publication`
com:

- `confirm_full_publication=true`;
- `migrate_folha_juliano_sergio=true`;
- `repair_linkedin_baseline=false`;
- `repair_martin_wolf_pubdate=false`.

O perfil interno `folha-juliano-sergio-2026-07-27` validou esses quatro objetos
antes de qualquer substituição local. O seed aceitava self-link canônico ou o
endereço legado exato do Pages, porque o workflow público podia atualizar o
checkout antes da migração; `main.py` normalizou a saída para o domínio privado
e a validação final recusou qualquer origem pública.

O run manual `30357116106`, no commit
`51f8690fec06ea89868538aaf43e3e8359ad1341`, terminou com sucesso em
2026-07-28. `current.json` ativou
`30357116106-1-51f8690fec06` às `12:18:40Z`. A reconciliação do R2 confirmou
218 chaves Standard: 108 feeds, 108 históricos, OPML e `manifest.json`,
equivalentes a 217 objetos internos e 109 rotas.

Os hashes remotos dos XMLs de Juliano e Sérgio coincidiram com os arquivos
locais. Ambos têm dez itens, autor explícito, conteúdo integral e self-link
canônico. Sem credenciais, as duas rotas responderam `401` com
`Cache-Control: no-store`; `workers.dev` permaneceu `404`, GitHub Pages `200`
e o apex `301` para o Linktree. A retenção deixou 13 snapshots, abaixo do teto
de 28.

Não reutilizar o perfil: ele foi consumido e agora falha porque o conjunto
exato de objetos ausentes deixou de existir. Todos os ciclos seguintes devem
usar hidratação normal, sem perfil.

Os dois XMLs autenticados foram cadastrados no Feedbin:

- `https://feeds.paulofehlauer.com/feeds/juliano_spyer_feed.xml`;
- `https://feeds.paulofehlauer.com/feeds/sergio_rodrigues_feed.xml`.

O usuário confirmou título, autor, conteúdo e funcionamento e então removeu as
duas assinaturas nativas. O Feedbin passou a acompanhar os 108 feeds gerados
pelo endpoint privado. FT Climate Capital permanece upstream.

### 7.6 Migração de Duda Herriot

Em 2026-08-12, a coluna de Duda Herriot na CNN Brasil foi cadastrada com o
`CNNBrasilBlogScraper`, já usado por Pedro Côrtes. A fonte pertence ao grupo
`outros` e deriva exatamente:

- `feeds/duda_herriot_feed.xml`;
- `history/duda_herriot_history.json`.

O perfil manual `cnn-duda-herriot-2026-08-12` existia apenas para a primeira
publicação, porque o snapshot anterior ainda não continha esse par. Durante a
hidratação, o perfil consultou o resolver da CNN, aceitou somente URLs sob
`/colunas/duda-herriot/`, exige autoria `Duda Herriot`, data com fuso e conteúdo
integral, e gera os dois objetos em memória. O conjunto observado de objetos
ausentes deve coincidir exatamente com esse par.

Para a primeira publicação, usar `Private feed publication` com:

- `confirm_full_publication=true`;
- `migrate_cnn_duda_herriot=true`;
- todos os demais perfis de reparo/migração em `false`.

O run `31599855268`, no commit `104a65b4`, hidratou exatamente os dois objetos
semeados, publicou 219 objetos e 110 rotas e terminou com sucesso. O snapshot
anterior tinha 217 objetos e 109 rotas, confirmando que somente o feed, o
histórico e a rota de Duda foram acrescentados. O perfil foi consumido e não
deve ser reutilizado; os ciclos seguintes devem usar hidratação normal.

### 7.7 Migração preparada para Caetano W. Galindo

Em 2026-08-13, a coluna de Caetano W. Galindo na Folha foi cadastrada com o
`FolhaScraper`. O endereço previsível do RSS oficial respondeu `404`, enquanto
a página da coluna entregou oito artigos recentes com data válida e conteúdo
integral. A fonte pertence ao grupo `folha` e deriva exatamente:

- `feeds/caetano_w_galindo_feed.xml`;
- `history/caetano_w_galindo_history.json`.

O perfil manual `folha-caetano-w-galindo-2026-08-13` existe apenas para a
primeira publicação, porque o snapshot ativo ainda não contém esse par. Durante
a hidratação, o perfil coleta a página da coluna, aceita somente URLs sob
`/colunas/caetano-w-galindo/` terminadas em `.shtml`, exige autoria
`Caetano W. Galindo`, data com fuso e conteúdo integral, e gera os dois objetos
em memória. O conjunto observado de objetos ausentes deve coincidir exatamente
com esse par.

Para a primeira publicação, usar `Private feed publication` com:

- `confirm_full_publication=true`;
- `migrate_folha_caetano_w_galindo=true`;
- todos os demais perfis de reparo/migração em `false`.

Depois do run bem-sucedido e da verificação da rota autenticada, não reutilizar
o perfil. O cadastro da URL privada no Feedbin é um gate manual separado. Até
esses passos ocorrerem, a fonte está preparada no código, mas ainda não integra
o snapshot privado ativo nem o leitor.

## 8. Rollback

O rollback normal troca apenas `current.json`. Antes disso, ele baixa o snapshot
de destino para uma área temporária e valida manifesto, allowlist, modalidade,
todos os hashes, tipos de conteúdo e a semântica de RSS, OPML e históricos.

Pelo GitHub:

1. abrir **Private feed rollback**;
2. informar o `run_id` exato;
3. conferir o resumo da execução;
4. validar o feed no Feedbin.

O workflow **Private feed rollback** exige `--required-mode full`. Isso impede
que um rollback manual depois da ampliação reduza inadvertidamente a superfície
completa — 110 rotas no snapshot atual — para o único feed do piloto. Antes do
primeiro snapshot `full`, uma falha de publicação
preserva o ponteiro piloto; uma falha de canário depois da ativação restaura
esse ponteiro automaticamente.

Se o canário do destino falhar, o script restaura o ponteiro original e testa o
snapshot restaurado. Não apagar o snapshot defeituoso antes de investigar.

## 9. Rotação de credenciais

Para rotacionar somente a senha:

1. gerar no gerenciador uma senha aleatória com ao menos 32 caracteres, fora de
   logs e da conversa;
2. configurar a nova senha como `BASIC_AUTH_PASSWORD_NEXT`, sem configurar
   `BASIC_AUTH_USERNAME_NEXT`;
3. testar senha atual, senha nova e uma senha inválida;
4. atualizar o Feedbin;
5. aguardar ao menos uma atualização automática;
6. promover a nova senha para `BASIC_AUTH_PASSWORD_CURRENT`;
7. atualizar `PRIVATE_FEED_PASSWORD` no GitHub Environment;
8. remover `BASIC_AUTH_PASSWORD_NEXT`;
9. confirmar `401` para a senha antiga.

Para rotacionar usuário e senha sem interromper o par atual:

1. gerar no gerenciador um usuário aleatório sem relação com domínio, nomes ou
   conteúdo e uma senha aleatória com ao menos 32 caracteres;
2. configurar o novo par como `BASIC_AUTH_USERNAME_NEXT` e
   `BASIC_AUTH_PASSWORD_NEXT`;
3. testar o par atual, o par de transição, os dois pares cruzados e um par
   inválido;
4. atualizar `PRIVATE_FEED_USERNAME` e `PRIVATE_FEED_PASSWORD` no GitHub
   Environment;
5. executar os canários no domínio definitivo;
6. atualizar o Feedbin e aguardar ao menos uma atualização automática;
7. promover o par de transição para `BASIC_AUTH_USERNAME` e
   `BASIC_AUTH_PASSWORD_CURRENT`;
8. remover `BASIC_AUTH_USERNAME_NEXT` e `BASIC_AUTH_PASSWORD_NEXT`;
9. confirmar `401` para o par antigo.

Não há documentação oficial do Feedbin garantindo atualização em lote de
credenciais. Planejar essa etapa como potencialmente individual até o piloto
produzir evidência.

Exports do Feedbin exigem cuidado adicional: o `subscriptions.xml` usado no
inventário de 2026-07-27 incorporou o par Basic nas URLs. Tratar todo export
como segredo, não exibir seu conteúdo, sanitizar `userinfo` antes de produzir
um inventário e nunca versionar o arquivo bruto. Ao terminar a migração, o
usuário removeu o bruto de Downloads e o moveu para o Lixo. Uma checagem
somente leitura confirmou sua ausência em Downloads, mas o Lixo não pôde ser
inspecionado por restrições do macOS e continua sendo armazenamento
recuperável até o esvaziamento. A cópia sanitizada anteriormente usada no
inventário também não estava mais no caminho registrado em Downloads. O par
atual foi mantido sem rotação por decisão explícita.

### Evidência da rotação real de 2026-07-25

- a assinatura piloto foi recriada manualmente no Feedbin com o novo par;
- depois da promoção, a Cloudflare expôs somente
  `BASIC_AUTH_USERNAME` e `BASIC_AUTH_PASSWORD_CURRENT`;
- às 15:28:38 BRT, já sem bindings `*_NEXT`, o Feedbin fez `GET` em
  `https://feeds.paulofehlauer.com/feeds/drauzio_feed.xml`, enviou
  `If-None-Match` e `If-Modified-Since` e recebeu `304`, com resultado `ok`;
- o par anterior foi retirado sem recuperar ou registrar seu valor;
- depois dessa evidência, `workers.dev` e Preview URLs foram desabilitados.

## 10. Gate de DNS

### Evidência pública preliminar em 2026-07-24

- `paulofehlauer.com` e `www.paulofehlauer.com` responderam `301` para
  `https://linktr.ee/paulofehlauer`;
- o servidor do redirecionamento se identificou como `hcdn`;
- `A`: `2.57.91.91`;
- `AAAA`: `2a02:4780:84::32`;
- `www`: CNAME para `paulofehlauer.com`;
- NS: `ns1.dns-parking.com` e `ns2.dns-parking.com`;
- SOA aponta para `dns.hostinger.com`;
- a consulta pública do apex não retornou `MX`, `TXT`, `CAA` nem `DS`.

Isso é apenas uma observação pública, não um inventário completo. DNS não
permite enumerar com segurança todos os nomes existentes.

### Inventário obrigatório antes de nameservers

1. exportar a zona completa no provedor atual;
2. guardar o arquivo de zona e uma captura legível;
3. registrar nome, tipo, valor, prioridade, TTL e proxy de todos os registros;
4. conferir `A`, `AAAA`, `CNAME`, `MX`, `TXT`, `CAA`, `SRV`, `NS` e wildcards;
5. procurar especialmente SPF, DKIM, DMARC e verificações de terceiros;
6. consultar o `DS` no registrador e planejar DNSSEC;
7. descobrir no painel atual como o redirect do apex e de `www` foi criado;
8. testar também caminhos, query strings, HTTP e HTTPS para reproduzir a mesma
   semântica;
9. importar ou recriar os registros na zona ainda pendente da Cloudflare;
10. comparar a zona linha a linha e validar e-mail com o provedor responsável.

A varredura automática da Cloudflare não é suficiente; a documentação alerta
que ela pode omitir registros.

### Preparação do redirecionamento

Uma Single Redirect Rule exige DNS com proxy ativado. Para uma origem somente
de redirecionamento, a Cloudflare admite os endereços reservados
`192.0.2.0` e `100::`. A regra exata só deve ser escolhida depois de confirmar
se o comportamento atual preserva caminho e query.

Sequência do gate:

1. reproduzir todos os registros e preparar a regra;
2. obter autorização explícita;
3. tratar DNSSEC/DS conforme o TTL aplicável;
4. trocar nameservers;
5. confirmar primeiro apex, `www`, redirect e serviços de e-mail;
6. somente então criar `feeds.paulofehlauer.com`.

Não alterar `fehla.xyz`.

## 11. Domínio definitivo e publicação completa

Depois de a zona estar ativa e o redirect principal validado:

1. adicionar `feeds.paulofehlauer.com` como Custom Domain do Worker;
2. confirmar o DNS e certificado criados pela Cloudflare;
3. testar o Worker ainda com o snapshot piloto;
4. depois de o Custom Domain responder corretamente, mudar a configuração
   aprovada de produção para `workers_dev=false`, reimplantar e confirmar que a
   origem temporária deixou de servir o Worker;
5. preparar um workflow completo separado, com
   `FEED_BASE_URL=https://feeds.paulofehlauer.com`;
6. obter autorização explícita para publicar todas as rotas;
7. executar manualmente **Private feed publication**, confirmando
   `confirm_full_publication=true`;
8. verificar os 213 objetos internos, as 107 rotas, os canários e o novo
   `current.json`;
9. somente depois do sucesso manual, definir
   `PRIVATE_FEED_FULL_ENABLED=true`;
10. observar ao menos um ciclo agendado completo;
11. obter outro gate antes de migrar as assinaturas em lotes.

Os passos 1–10 estão concluídos. O passo 10 falhou fechado nos quatro disparos
de 2026-07-26 por escopo incorreto da variable usada no `jobs.<job_id>.if`, a
causa foi corrigida às `23:04Z` e o run agendado `30237068708` forneceu a
evidência automática em 2026-07-27. O passo 11 também foi autorizado e
concluído no mesmo dia. O workflow de piloto exige
`PRIVATE_FEED_PILOT_ENABLED=true`, que deve permanecer `false`, para não poder
substituir um snapshot completo por um snapshot com apenas uma rota.

### Evidência da primeira publicação completa

- run GitHub `30170506858`, commit `bc9e2a60`, duração 17m58s;
- hidratação validou 213 objetos do piloto
  `30165530357-1-f312addae81a`;
- geração processou 106 fontes: cinco artigos novos, 99 fontes sem mudança e
  duas falhas de origem; os feeds anteriores foram preservados;
- validação montou 213 objetos e 107 rotas;
- snapshot ativo `30170506858-1-bc9e2a6055ac`, com o piloto registrado como
  ponteiro anterior e nenhuma exclusão pela retenção;
- os canários obrigatórios confirmaram `401` anônimo e inválido, `GET 200`,
  `HEAD 200`, `304` condicional, hash, ETag, `Last-Modified`, XML, cache privado
  e `/healthz` no novo run;
- reconciliação da API confirmou no R2 106 feeds, 106 históricos, um OPML e o
  manifesto; `current.json` foi atualizado às `19:08:56.771Z`;
- bucket Standard sem Custom Domain e com `r2.dev` desabilitado; Worker com
  `workers.dev` e Preview URLs desabilitados;
- dois feeds, OPML, `/healthz` e caminho inexistente retornaram o mesmo `401`
  sem credenciais; Pages permaneceu em `200` e o apex em `301` para o Linktree;
- imediatamente depois da execução manual,
  `PRIVATE_FEED_FULL_ENABLED=false` e
  `PRIVATE_FEED_PILOT_ENABLED=false` foram reconfirmados.

### Evidência das tentativas agendadas que falharam fechadas

- `PRIVATE_FEED_FULL_ENABLED=true` desde `2026-07-25T19:19:57Z` e
  `PRIVATE_FEED_PILOT_ENABLED=false`, ambos no Environment
  `private-feed-pilot`;
- runs `30187551489`, `30195696122`, `30205646460` e `30217759033` concluídos
  como `skipped`, sem steps;
- diagnóstico: `jobs.publish-full.if` é processado antes que variables
  exclusivas do Environment fiquem disponíveis; a expressão recebeu string
  vazia e fechou o job;
- nenhum prefixo dos quatro runs existe no R2;
- `current.json` permaneceu com ETag
  `34ed3781f186ae54da0b20896ae77de4`, SHA-256
  `14ab666e93cc2d7830f4efdea8c6283e497c552f4e842e7665ab3ad84dac999c` e
  `Last-Modified` `2026-07-25T19:08:56.771Z`;
- o snapshot completo ativo continuou com 213 objetos mais o manifesto;
- validação anônima posterior: domínio privado `401`, origem `workers.dev`
  `404`, feed no GitHub Pages `200` e apex `301` para
  `https://linktr.ee/paulofehlauer`.

Não houve hidratação, scraper, upload, ativação, canário ou retenção nesses
quatro runs. Às `23:04Z`, `PRIVATE_FEED_FULL_ENABLED=true` e
`PRIVATE_FEED_PILOT_ENABLED=false` foram criados como variables do repositório
e conferidos; somente depois os dois duplicados foram removidos do Environment.
As demais variables permaneceram intactas e o workflow foi confirmado como
`active`. Não foi usado `workflow_dispatch` como substituto da evidência
agendada.

### Evidência do primeiro ciclo agendado bem-sucedido

- run `30237068708`, `event=schedule`, commit
  `57ac4cee27df9992d076e2507a239f612ff7f97f`;
- primeiro horário nominal posterior à correção: `2026-07-27T00:47Z`; criação
  às `04:25:46Z` e conclusão `success` às `04:47:32Z`;
- modo `full`, com hidratação dos 213 objetos do snapshot anterior
  `30170506858-1-bc9e2a6055ac` e nenhum objeto legado ignorado;
- validação de 213 objetos e 107 rotas;
- ativação de `30237068708-1-57ac4cee27df`, com o snapshot anterior registrado
  como `previous_run_id`, canários autenticados e anônimos aprovados e
  retenção executada sem exclusões;
- API do R2: 214 chaves no prefixo novo, incluindo `manifest.json`, todas em
  Standard; `current.json` com ETag `dc5393314b4f77e24b8dff1b1da787d9`,
  SHA-256 `dd76ce846ab39f32d92258cf35d14e6ada16236aab5a6fc604e496e8e35d16ae`
  e `Last-Modified` `2026-07-27T04:43:15.064Z`;
- validação externa: domínio privado `401`, origem `workers.dev` `404`, feed
  no GitHub Pages `200` e apex `301` para
  `https://linktr.ee/paulofehlauer`;
- variables no repositório: `PRIVATE_FEED_FULL_ENABLED=true` e
  `PRIVATE_FEED_PILOT_ENABLED=false`; esses nomes permanecem ausentes do
  Environment `private-feed-pilot`, que conserva canário, endpoint, feed
  piloto, conta R2 e bucket.

### Evidência da migração das assinaturas no Feedbin

- o inventário inicial encontrou 87 URLs públicas antigas: 86 correspondiam à
  configuração atual e uma era o órfão legado
  `futuro_marketing_b2b_linkedin_feed.xml`;
- as 86 assinaturas atuais foram recriadas com URLs privadas em cinco lotes de
  5, 20, 21, 18 e 22 itens, preservando as categorias;
- com a assinatura piloto de Drauzio, o Feedbin passou a ter 87 assinaturas
  privadas, todas confirmadas como `OK` pelo usuário no cadastro inicial;
- somente depois dessa conferência o usuário excluiu as 87 assinaturas antigas
  do GitHub Pages, inclusive o órfão;
- o export bruto que continha credenciais foi movido para o Lixo e não está
  mais em Downloads; nenhum valor foi registrado no Git, nos documentos ou nos
  logs;
- a reconciliação externa continuou retornando `401` anonimamente no domínio
  privado, `404` em `workers.dev`, `200` no GitHub Pages e destino final
  `https://linktr.ee/paulofehlauer` no apex.

Os runs agendados `30371575582` e `30394804773` atravessaram a janela de
estabilização sem perfil de reparo ou migração. O primeiro hidratou
`30357116106-1-51f8690fec06` e ativou
`30371575582-1-e3ff37944524`; o segundo hidratou esse snapshot e ativou
`30394804773-1-1204dfd6414d`. Cada ciclo validou 217 objetos e 109 rotas,
passou pelos canários autenticados e anônimos e aplicou retenção sem exclusões.
A API do R2 confirmou 218 chaves no segundo prefixo: 108 feeds, 108 históricos,
OPML e manifesto.

O segundo ciclo registrou `404` no RSS do Bloomberg Green, `404` na página de
Fernando Reinach e respostas `429` durante enriquecimentos do LinkedIn. A
proteção contra regressão preservou o conteúdo anterior e o snapshot completo
foi validado e publicado. Esses avisos devem continuar sob observação, mas não
deixaram objetos ou rotas ausentes.

Com a estabilização concluída, o corte autorizado foi aplicado no commit
`ed9924f6`. O run pós-corte `30398410821` hidratou 217 objetos de
`30394804773-1-1204dfd6414d`, sem perfil de reparo ou migração, validou 217
objetos e 109 rotas e ativou `30398410821-1-ed9924f6e9ad`. Canários e retenção
passaram. A API do R2 confirmou 218 chaves: 108 feeds, 108 históricos, OPML e
manifesto.

O `wrangler.jsonc` local não declara rotas porque o Custom Domain é gerenciado
no painel da Cloudflare. Ele fixa `workers_dev=false`, evitando que um deploy
futuro reative a origem temporária. Preview URLs também permanecem desabilitadas
na configuração remota.

## 12. Corte da publicação pública

O corte foi executado em 2026-07-28 depois da autorização explícita:

1. `.github/workflows/workflow.yml` foi removido;
2. `feeds/` e `history/` saíram da árvore atual e passaram a ser ignorados;
3. o workflow privado permaneceu com `contents: read`;
4. o commit `ed9924f6` foi enviado para `main`;
5. o run `30398410821` publicou e ativou o snapshot privado pós-corte;
6. somente depois dos canários, o GitHub Pages foi desativado pela API;
7. a configuração Pages, a URL pública legada e o arquivo bruto em `main`
   retornaram `404`;
8. o endpoint privado permaneceu `401` e `no-store` sem credenciais,
   `workers.dev` permaneceu `404` e o apex preservou o `301` para o Linktree.

O histórico Git não foi reescrito. Para reversão, restaurar os arquivos pelo
revert de `ed9924f6` e só então recriar o Pages apontando para `main` e `/`;
isso exige nova autorização explícita.

## 13. Diagnóstico e recuperação

| Sintoma | Ação |
|---|---|
| hidratação sem `current.json` | parar; bootstrap exige autorização explícita |
| hash remoto divergente | não rodar scraper; preservar estado local e investigar R2 |
| scraper falhou | confirmar que o feed anterior permaneceu; não forçar arquivo vazio |
| upload falhou | confirmar que `current.json` não mudou; repetir com novo `run_id` |
| ponteiro mudou durante a execução | tratar como concorrência; não ativar |
| canário novo falhou | confirmar restauração automática do ponteiro anterior |
| canário restaurado falhou | incidente de entrega; não publicar nem aplicar retenção |
| Worker retorna `503` | validar ponteiro, manifesto, metadata SHA e objeto canário |
| Feedbin não atualizou | manter piloto; conferir `401/200/304`, User-Agent e logs sem conteúdo |
| uso acima da faixa prevista | desabilitar agenda do piloto e revisar antes de contratar plano |

Não imprimir `Authorization`, bodies de artigos ou valores de secrets durante o
diagnóstico.

## 14. Escala e custo

Na configuração atual, uma publicação grava aproximadamente:

- 217 objetos internos;
- um manifesto;
- um ponteiro.

Com quatro execuções diárias, são cerca de 26 mil `PutObject` mensais. A
validação conservadora de retenção acrescenta listagens e aproximadamente
800 mil leituras mensais. Vinte e oito snapshots ocupam ordem de 150 MB, antes
de variações de conteúdo.

Esses valores ficam abaixo das faixas gratuitas publicadas para R2 Standard
(10 GB-mês, 1 milhão de operações Class A e 10 milhões Class B) e Workers Free
(100 mil requisições diárias). Eles não são garantia contratual. Revisar preços,
uso real e CPU do Worker antes de restabelecer o ciclo agendado.

## 15. Evidência externa validada

- O Feedbin documenta suporte a HTTP Basic Auth e solicita usuário e senha
  depois do cadastro da URL.
- O Feedbin documenta importação OPML, mas não promete reutilizar uma única
  credencial para todos os itens nem documenta o comportamento de `304`.
- R2 é fortemente consistente para operações diretas por S3 e Worker binding.
- Buckets R2 são privados por padrão; `r2.dev` e Custom Domains são exposições
  separadas e explícitas.
- R2 oferece operações condicionais necessárias ao ponteiro.
- Workers oferece `crypto.subtle.timingSafeEqual`.
- GitHub Actions oferece `queue: max`; publicação e rollback podem formar uma
  fila serial comum.
- A orientação de segurança do GitHub recomenda SHA completo como a única
  referência imutável para uma Action.

Referências oficiais:

- [Feedbin: Password Protected Feeds](https://feedbin.com/help/password-protected-feeds/)
- [Feedbin: Verifying Feed Requests](https://feedbin.com/help/verifying-feed-requests/)
- [Feedbin: OPML Import](https://feedbin.com/help/how-to-subscribe/)
- [Cloudflare R2: Public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [Cloudflare R2: Consistency](https://developers.cloudflare.com/r2/reference/consistency/)
- [Cloudflare R2: S3 API](https://developers.cloudflare.com/r2/api/s3/api/)
- [Cloudflare R2: Tokens](https://developers.cloudflare.com/r2/api/tokens/)
- [Cloudflare R2: Pricing](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare Workers: Limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Cloudflare Workers: Web Crypto](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/)
- [Cloudflare Workers: Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Cloudflare Workers: Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
- [Cloudflare Workers: `workers.dev`](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
- [Cloudflare Workers: Real-time logs](https://developers.cloudflare.com/workers/observability/logs/real-time-logs/)
- [Cloudflare DNS: Full setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Cloudflare DNS: Import and export](https://developers.cloudflare.com/dns/manage-dns-records/how-to/import-and-export/)
- [Cloudflare DNS: DNSSEC](https://developers.cloudflare.com/dns/dnssec/)
- [Cloudflare Rules: Redirects](https://developers.cloudflare.com/rules/url-forwarding/)
- [GitHub Actions: Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [GitHub Actions: Variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)
- [GitHub Actions: Secure use](https://docs.github.com/en/actions/reference/security/secure-use)
