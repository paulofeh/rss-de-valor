import time
from collections import defaultdict
from src.scrapers import get_scraper_class
from src.utils import (
    ensure_directories,
    load_sources_config,
    load_history,
    save_history,
    generate_grouped_feed,
    save_feed,
    generate_opml,
    save_opml
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

    print("=" * 70)
    print("Coletando artigos de todos os colunistas...")
    print("=" * 70)

    for source in sources:
        scraper_class = get_scraper_class(source['scraper'])
        if not scraper_class:
            print(f"❌ Scraper não encontrado: {source['scraper']}")
            error_count += 1
            continue

        scraper = scraper_class(source['url'])
        group = source.get('group', 'outros')

        max_retries = 3
        for attempt in range(max_retries):
            try:
                latest_article = scraper.get_latest_article()
                if latest_article:
                    history = load_history(source['history_file'])

                    # Always add to grouped articles (not just new ones)
                    grouped_articles[group].append({
                        'author_name': source['name'],
                        'article': latest_article
                    })

                    # Check if this is a new article for logging/statistics
                    if latest_article['link'] != history.get('last_article_link'):
                        # Update history
                        history['last_article_link'] = latest_article['link']
                        save_history(source['history_file'], history)

                        print(f"✅ Novo artigo: {source['name']}")
                        new_articles_count += 1
                    else:
                        print(f"ℹ️  Sem novidades: {source['name']}")
                        no_change_count += 1
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

    if not grouped_articles:
        print("⚠️  Nenhum artigo coletado. Feeds não atualizados.")
    else:
        for group, articles in grouped_articles.items():
            try:
                feed = generate_grouped_feed(group, articles)
                feed_filename = f"{group}_feed.xml"
                save_feed(feed, feed_filename)
                print(f"✅ Feed do {group.title()} gerado com {len(articles)} artigo(s)")
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


if __name__ == "__main__":
    main()