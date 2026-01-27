# 📰 RSS de Colunistas

Agregador automatizado de feeds RSS de colunistas brasileiros, com atualizações a cada 6 horas via GitHub Actions.

[![Update Feeds](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml/badge.svg)](https://github.com/paulofeh/rss-de-valor/actions/workflows/workflow.yml)

## 🎯 O que é este projeto?

Este projeto transforma artigos de colunistas brasileiros em feeds RSS padronizados, permitindo que você acompanhe seus colunistas favoritos através de qualquer leitor RSS (Feedly, Inoreader, NetNewsWire, etc.).

**✨ Acesse a página de feeds:** [https://paulofeh.github.io/rss-de-valor/feeds/](https://paulofeh.github.io/rss-de-valor/feeds/)

## 📊 Status Atual

- **63 colunistas** monitorados
- **6 feeds agrupados** por veículo
- **21 feeds RSS oficiais** (mais confiáveis)
- **Atualização automática** a cada 6 horas
- **100% gratuito** via GitHub Actions

## 🗂️ Veículos Cobertos

### Feeds Agrupados Disponíveis

| Veículo | Colunistas | Feed Agrupado |
|---------|------------|---------------|
| **Estadão** | 16 | [estadao_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/estadao_feed.xml) |
| **Folha de S.Paulo** | 25 | [folha_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/folha_feed.xml) |
| **O Globo** | 9 | [oglobo_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/oglobo_feed.xml) |
| **Valor Econômico** | 5 | [valor_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/valor_feed.xml) |
| **LinkedIn Newsletters** | 7 | [linkedin_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/linkedin_feed.xml) |
| **Poder360** | 1 | [poder360_feed.xml](https://paulofeh.github.io/rss-de-valor/feeds/poder360_feed.xml) |

### Alguns Colunistas Incluídos

**Folha:** Antonio Prata, Dráuzio Varella, Tati Bernardi, Celso Rocha de Barros, Conrado Hubner Mendes, Marcos Mendes, Ronaldo Lemos...

**Estadão:** Leandro Karnal, Fernando Reinach, Eugenio Bucci, Felipe Salto, Oliver Stuenkel...

**O Globo:** Martha Batalha, Bernardo Mello Franco, Dorrit Harazim, Pedro Doria...

**Valor:** Guilherme Ravache, Bruno Carazza, Maria Cristina Fernandes...

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

### Feeds Agrupados
- Um feed por veículo contendo todos os colunistas
- Títulos no formato: **"Nome do Autor: Título do Artigo"**
- Ordenados por data de publicação
- Atualizados automaticamente

### Feeds Individuais
- Um feed exclusivo para cada colunista
- Permite acompanhamento personalizado
- Mantém histórico individual

### Página HTML Interativa
- Interface visual moderna
- Organização por veículo
- Links para todos os feeds
- Estatísticas atualizadas
- Design responsivo (mobile-friendly)

### Suporte a Feeds RSS Existentes
- Quando o veículo já fornece RSS oficial, usamos esse feed
- Mais confiável e rápido
- 21 feeds da Folha utilizam RSS oficial

## 🛠️ Tecnologias

- **Python 3.11** - Linguagem principal
- **BeautifulSoup4** - Scraping de HTML
- **feedgenerator** - Geração de feeds RSS
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
│   ├── estadao_feed.xml         # Feed agrupado do Estadão
│   ├── folha_feed.xml           # Feed agrupado da Folha
│   └── ...                      # Outros feeds
├── history/
│   └── *.json                   # Histórico de artigos processados
├── src/
│   ├── scrapers.py              # Classes de scraping
│   └── utils.py                 # Funções auxiliares
├── main.py                      # Script principal
└── .github/workflows/
    └── workflow.yml             # Automação GitHub Actions
```

## 🔧 Como Adicionar Novos Colunistas

### 1. Colunista com Feed RSS Existente

Se o colunista já tem um feed RSS oficial:

```json
{
  "name": "Nome do Colunista",
  "url": "https://site.com/feed.xml",
  "scraper": "ExistingRssScraper",
  "feed_file": "colunista_feed.xml",
  "history_file": "colunista_history.json",
  "group": "nome_veiculo"
}
```

### 2. Colunista que Precisa de Scraping

Para sites sem feed RSS:

```json
{
  "name": "Nome do Colunista",
  "url": "https://site.com/coluna/",
  "scraper": "NomeDoScraper",
  "feed_file": "colunista_feed.xml",
  "history_file": "colunista_history.json",
  "group": "nome_veiculo"
}
```

Adicione a entrada em `config/sources_config.json` e faça commit. O GitHub Actions processará automaticamente.

## 🤖 Automação

O sistema é executado automaticamente via GitHub Actions:

- **Frequência:** A cada 6 horas (00:00, 06:00, 12:00, 18:00 UTC)
- **Processo:**
  1. Coleta artigos mais recentes de cada colunista
  2. Compara com histórico para detectar novos artigos
  3. Gera feeds individuais e agrupados
  4. Atualiza OPML e página HTML
  5. Faz commit automático das mudanças
  6. Publica no GitHub Pages

## 📝 Formato dos Feeds

### Feed Agrupado
```xml
<item>
  <title>Leandro Karnal: A importância da filosofia na educação</title>
  <link>https://...</link>
  <description>Texto do artigo...</description>
  <author>Leandro Karnal</author>
  <pubDate>Mon, 19 Jan 2026 10:00:00 GMT</pubDate>
</item>
```

### Feed Individual
```xml
<item>
  <title>A importância da filosofia na educação</title>
  <link>https://...</link>
  <description>Texto do artigo...</description>
  <author>Leandro Karnal</author>
  <pubDate>Mon, 19 Jan 2026 10:00:00 GMT</pubDate>
</item>
```

## 🔍 Scrapers Disponíveis

| Scraper | Descrição | Uso |
|---------|-----------|-----|
| `ExistingRssScraper` | Processa feeds RSS existentes | Folha (21 feeds) |
| `FolhaScraper` | Scraping de páginas da Folha | Folha (alguns) |
| `EstadaoColumnistScraper` | Scraping do Estadão | Estadão |
| `ValorOGloboScraper` | Scraping de Valor e O Globo | Valor, O Globo |
| `LinkedInNewsletterScraper` | Scraping de newsletters do LinkedIn | LinkedIn |
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
