import time
from collections import defaultdict
from src.scrapers import get_scraper_class
from src.utils import (
    ensure_directories,
    load_sources_config,
    load_history,
    save_history,
    generate_feed,
    generate_grouped_feed,
    save_feed,
    generate_opml,
    save_opml,
    generate_html_index,
    save_html_index
)

def main():
    # Garante que os diretórios necessários existem
    ensure_directories()

    # Carrega a configuração dos sources
    sources = load_sources_config()

    # Dictionary to group ALL articles by group (vehicle)
    grouped_articles = defaultdict(list)

    # Statistics
    new_articles_count = 0
    no_change_count = 0
    error_count = 0
    individual_feeds_generated = 0

    print("=" * 70)
    print("Coletando artigos e gerando feeds individuais...")
    print("=" * 70)

    # Separate sources that need scraping from those with existing RSS
    scrape_sources = [s for s in sources if s['scraper'] != 'ExistingRssScraper']
    rss_sources = [s for s in sources if s['scraper'] == 'ExistingRssScraper']

    if rss_sources:
        print(f"ℹ️  {len(rss_sources)} fontes com RSS nativo (não serão raspadas)")

    for source in scrape_sources:
        scraper_class = get_scraper_class(source['scraper'])
        if not scraper_class:
            print(f"❌ Scraper não encontrado: {source['scraper']}")
            error_count += 1
            continue

        scraper = scraper_class(source['url'])
        group = source.get('group', '')  # Empty string if no group

        max_retries = 3
        for attempt in range(max_retries):
            try:
                articles = scraper.get_articles()
                if articles:
                    latest_article = articles[0]
                    history = load_history(source['history_file'])

                    # Check if this is a new article for logging/statistics
                    is_new_article = latest_article['link'] != history.get('last_article_link')

                    if is_new_article:
                        # Update history
                        history['last_article_link'] = latest_article['link']
                        save_history(source['history_file'], history)
                        print(f"✅ Novo artigo: {source['name']}")
                        new_articles_count += 1
                    else:
                        print(f"ℹ️  Sem novidades: {source['name']}")
                        no_change_count += 1

                    # ALWAYS generate individual feed (whether new or not)
                    try:
                        individual_feed = generate_feed(source['name'], source['url'], articles)
                        save_feed(individual_feed, source['feed_file'])
                        individual_feeds_generated += 1
                    except Exception as e:
                        print(f"   ⚠️  Erro ao gerar feed individual de {source['name']}: {str(e)}")

                    # Add to grouped articles ONLY if group is specified and not empty
                    if group and group.strip():
                        for article in articles:
                            grouped_articles[group].append({
                                'author_name': source['name'],
                                'article': article
                            })
                else:
                    print(f"⚠️  Não foi possível obter artigo: {source['name']}")
                    error_count += 1

                break  # Se bem-sucedido, sai do loop
            except Exception as e:
                print(f"❌ Erro ao processar {source['name']}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"   Tentando novamente em 5 segundos...")
                    time.sleep(5)
                else:
                    print(f"   Falha após {max_retries} tentativas.")
                    error_count += 1

    # Generate grouped feeds
    print("\n" + "=" * 70)
    print("Gerando feeds agrupados por veículo...")
    print("=" * 70)

    grouped_feeds_generated = 0
    if not grouped_articles:
        print("ℹ️  Nenhum grupo configurado ou nenhum artigo coletado para agrupamento.")
    else:
        for group, articles in grouped_articles.items():
            try:
                feed = generate_grouped_feed(group, articles)
                feed_filename = f"{group}_feed.xml"
                save_feed(feed, feed_filename)
                print(f"✅ Feed do {group.title()} gerado com {len(articles)} artigo(s)")
                grouped_feeds_generated += 1
            except Exception as e:
                print(f"❌ Erro ao gerar feed do {group}: {str(e)}")

    # Print summary
    print("\n" + "=" * 70)
    print("RESUMO DA EXECUÇÃO")
    print("=" * 70)
    print(f"✅ Artigos novos: {new_articles_count}")
    print(f"ℹ️  Sem mudanças: {no_change_count}")
    print(f"❌ Erros: {error_count}")
    print(f"📊 Total processado: {new_articles_count + no_change_count + error_count}")
    print(f"\n📄 Feeds individuais gerados: {individual_feeds_generated}")
    print(f"📚 Feeds agrupados gerados: {grouped_feeds_generated}")

    # Gera o arquivo OPML atualizado
    print("\n" + "=" * 70)
    print("Gerando arquivo OPML...")
    print("=" * 70)
    try:
        opml = generate_opml(sources)
        save_opml(opml, 'feeds/feeds.opml')
        print("✅ Arquivo OPML atualizado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao gerar arquivo OPML: {str(e)}")

    # Gera a página HTML index
    print("\n" + "=" * 70)
    print("Gerando página HTML...")
    print("=" * 70)
    try:
        html = generate_html_index(sources)
        save_html_index(html, 'feeds/index.html')
        print("✅ Página HTML gerada com sucesso!")
        print("   Acesse em: https://paulofeh.github.io/rss-de-valor/feeds/")
    except Exception as e:
        print(f"❌ Erro ao gerar página HTML: {str(e)}")


if __name__ == "__main__":
    main()