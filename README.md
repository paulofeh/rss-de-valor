# 📰 RSS de Colunistas

Agregador automatizado de feeds RSS de colunistas brasileiros e fontes de risco climático, com atualizações a cada 6 horas via GitHub Actions.

[![Update Feeds](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml/badge.svg)](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml)

## 🎯 O que é este projeto?

Este projeto transforma artigos de colunistas brasileiros e fontes sobre risco climático em feeds RSS padronizados, permitindo que você acompanhe seus colunistas e temas favoritos através de qualquer leitor RSS (Feedly, Inoreader, NetNewsWire, etc.).

**✨ Acesse a página de feeds:** [https://paulofeh.github.io/rss-de-valor/feeds/](https://paulofeh.github.io/rss-de-valor/feeds/)

## 📊 Status Atual

- **82 fontes** monitoradas (colunistas, seções, portais e canais do YouTube)
- **22 feeds RSS nativos** (link direto ao feed original)
- **60 feeds gerados** via scraping/APIs
- **Atualização automática** a cada 6 horas
- **100% gratuito** via GitHub Actions

## 🗂️ Fontes Cobertas

| Grupo | Fontes |
|-------|--------|
| **Folha de S.Paulo** | 25 colunistas |
| **Risco Climático** | 20 (BBC, Bloomberg Green, DW, FT, Nature, Google Alerts, YouTube e mais) |
| **Estadão** | 16 colunistas |
| **O Globo** | 10 colunistas |
| **LinkedIn Newsletters** | 5 |
| **Valor Econômico** | 4 colunistas |
| **Outros** | 2 (Paul Graham, Poder360) |

[Ver lista completa na página de feeds →](https://paulofeh.github.io/rss-de-valor/feeds/)

## 🚀 Como Usar

### Opção 1: Importar Todos os Feeds de Uma Vez (Recomendado)

Baixe o arquivo OPML e importe no seu leitor RSS:

📥 **[Baixar feeds.opml](https://paulofeh.github.io/rss-de-valor/feeds/feeds.opml)**

### Opção 2: Assinar Feeds Individualmente

Visite a página de feeds e escolha os que deseja assinar:

🌐 **[https://paulofeh.github.io/rss-de-valor/feeds/](https://paulofeh.github.io/rss-de-valor/feeds/)**

### Opção 3: URLs Diretas

Copie a URL do feed que deseja e adicione manualmente no seu leitor RSS:

```
https://paulofeh.github.io/rss-de-valor/feeds/folha_feed.xml
https://paulofeh.github.io/rss-de-valor/feeds/estadao_feed.xml
https://paulofeh.github.io/rss-de-valor/feeds/oglobo_feed.xml
...
```

## ✨ Funcionalidades

### Feeds com Conteúdo Completo
- Quando possível, o scraper extrai o conteúdo completo dos artigos (Estadão, BBC, Bloomberg Línea, Valor/O Globo, WordPress)
- Transcrições automáticas de vídeos do YouTube via legendas
- Abstracts de periódicos acadêmicos (Nature)
- Feeds gerados com múltiplos artigos por fonte (não apenas o mais recente)

### Feeds RSS Nativos
- Quando a fonte já fornece RSS oficial (22 fontes), o sistema linka diretamente ao feed original
- Sem redundância: o feed original é sempre mais completo e atualizado

### Feeds Individuais Gerados
- Para fontes sem RSS nativo, gera feeds via scraping de HTML ou APIs internas
- Mantém histórico individual para detectar novos artigos

### Página HTML Interativa
- Interface visual moderna
- Organização por veículo
- Links para todos os feeds (originais ou gerados)
- Estatísticas atualizadas
- Design responsivo (mobile-friendly)

## 🛠️ Tecnologias

- **Python 3** - Linguagem principal
- **BeautifulSoup4** - Scraping de HTML
- **feedgenerator** - Geração de feeds RSS
- **trafilatura** - Extração de conteúdo de artigos (Google Alerts)
- **youtube-transcript-api** - Transcrições de vídeos do YouTube
- **WordPress REST API** - Extração de conteúdo de sites WordPress
- **Arc/Fusion CMS** - APIs internas do Estadão e Bloomberg Línea
- **GitHub Actions** - Automação (executa a cada 6 horas)
- **GitHub Pages** - Hospedagem dos feeds

## 📁 Estrutura do Projeto

```
rss-de-valor/
├── config/
│   └── sources_config.json      # Configuração de todos os colunistas
├── feeds/
│   ├── index.html               # Página web dos feeds
│   ├── feeds.opml               # Arquivo OPML para importação
│   ├── *_feed.xml               # Feeds individuais por fonte
│   └── ...                      
├── history/
│   └── *.json                   # Histórico de artigos processados
├── src/
│   ├── scrapers.py              # Classes de scraping
│   └── utils.py                 # Funções auxiliares
├── main.py                      # Script principal
└── .github/workflows/
    └── workflow.yml             # Automação GitHub Actions
```

## 🔧 Como Adicionar Novas Fontes

### 1. Fonte com Feed RSS Existente

Se a fonte já tem um feed RSS oficial, use `ExistingRssScraper`. O sistema não raspará o feed — apenas linka diretamente ao original no HTML e OPML:

```json
{
  "name": "Nome da Fonte",
  "url": "https://site.com/feed.xml",
  "scraper": "ExistingRssScraper",
  "feed_file": "fonte_feed.xml",
  "history_file": "fonte_history.json",
  "group": "nome_veiculo"
}
```

### 2. Site WordPress com REST API

Se o site é WordPress e tem a API habilitada (`/wp-json/wp/v2/posts`), use `WordPressApiScraper`. Suporta filtro automático por tag/categoria a partir da URL:

```json
{
  "name": "Nome da Fonte",
  "url": "https://site.com/categoria/",
  "scraper": "WordPressApiScraper",
  "feed_file": "fonte_feed.xml",
  "history_file": "fonte_history.json",
  "group": "nome_veiculo"
}
```

### 3. Fonte que Precisa de Scraper Customizado

Para sites com estrutura própria, crie uma classe em `src/scrapers.py` herdando `BaseScraper`, implemente `get_articles(limit)` para retornar múltiplos artigos, registre em `get_scraper_class()`, e adicione a entrada no config.

Adicione a entrada em `config/sources_config.json` e faça commit. O GitHub Actions processará automaticamente.

## 🤖 Automação

O sistema é executado automaticamente via GitHub Actions:

- **Frequência:** A cada 6 horas (00:00, 06:00, 12:00, 18:00 UTC)
- **Processo:**
  1. Coleta artigos de cada fonte que precisa de scraping (60 fontes)
  2. Fontes com RSS nativo (22) são ignoradas no scraping — linkam direto ao original
  3. Compara com histórico para detectar novos artigos
  4. Gera feeds individuais com múltiplos artigos
  5. Atualiza OPML e página HTML
  6. Faz commit automático das mudanças
  7. Publica no GitHub Pages

## 📝 Formato dos Feeds

Os feeds gerados contêm múltiplos artigos por fonte (quando suportado pelo scraper), com conteúdo completo quando disponível:

```xml
<item>
  <title>A importância da filosofia na educação</title>
  <link>https://...</link>
  <description>Conteúdo completo do artigo em HTML...</description>
  <author>Leandro Karnal</author>
  <pubDate>Mon, 19 Jan 2026 10:00:00 GMT</pubDate>
</item>
```

## 🔍 Scrapers Disponíveis

| Scraper | Descrição | Uso |
|---------|-----------|-----|
| `ExistingRssScraper` | Link direto a feeds RSS nativos | Folha (22 feeds), FT Climate Capital |
| `FolhaScraper` | Scraping de páginas da Folha | Folha (4 colunistas) |
| `EstadaoColumnistScraper` | Scraping de colunistas do Estadão | Estadão (16 colunistas) |
| `EstadaoSectionScraper` | Seções do Estadão via Fusion/Arc CMS | Estadão Sustentabilidade |
| `ValorOGloboScraper` | Scraping de Valor e O Globo (com conteúdo completo) | Valor, O Globo (17 fontes) |
| `BloombergLineaScraper` | API Arc/Fusion da Bloomberg Línea | Bloomberg Green |
| `BBCTopicScraper` | Páginas de tópico da BBC (conteúdo completo) | BBC Mudanças Climáticas |
| `WordPressApiScraper` | WP REST API com filtro por tag/categoria/taxonomia | CNN Agro, FAPESP, Nottus, O Eco, Yale Climate, Repórter Brasil |
| `GoogleAlertsScraper` | Google Alerts RSS com conteúdo via trafilatura | Risco Climático, Climate Risk |
| `NatureRdfScraper` | Feeds RDF/RSS 1.0 da Nature com abstracts | npj Climate Action, npj Urban Sustainability |
| `DWTopicScraper` | Tópicos da Deutsche Welle via GraphQL (conteúdo completo) | DW Climate |
| `YouTubeTranscriptScraper` | Transcrições de canais do YouTube (filtra Shorts) | Arroz, Feijão & Clima |
| `SustainableViewsScraper` | Categorias do Sustainable Views (FT) | Sustainable Views Risk |
| `LinkedInNewsletterScraper` | Scraping de newsletters do LinkedIn | LinkedIn (5 fontes) |
| `PaulGrahamScraper` | Essays do paulgraham.com (conteúdo completo) | Paul Graham |
| `Poder360Scraper` | Scraping do Poder360 | Poder360 |

## 🤝 Contribuindo

Contribuições são bem-vindas! Para adicionar novos colunistas ou veículos:

1. Fork o repositório
2. Adicione a configuração em `config/sources_config.json`
3. Se necessário, crie um novo scraper em `src/scrapers.py`
4. Teste localmente com `python main.py`
5. Envie um Pull Request

## 📜 Licença

Este projeto é de código aberto e está disponível sob licença MIT.

## 🙏 Agradecimentos

- Aos jornalistas e colunistas que produzem conteúdo de qualidade
- À comunidade Python pelo excelente ecossistema de ferramentas
- Ao GitHub por fornecer Actions e Pages gratuitamente

## 📞 Contato

Encontrou algum problema ou tem sugestões?

- [Abra uma issue](https://github.com/paulofeh/rss-de-valor/issues)
- [Envie um Pull Request](https://github.com/paulofeh/rss-de-valor/pulls)

---

**⭐ Se este projeto foi útil para você, considere dar uma estrela no repositório!**
