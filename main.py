import time
from src.scrapers import get_scraper_class
from src.utils import (
    ensure_directories,
    load_sources_config,
    load_history,
    save_history,
    generate_feed,
    save_feed
)

def main():
    # Garante que os diretórios necessários existem
    ensure_directories()
    
    # Carrega a configuração dos sources
    sources = load_sources_config()
    
    for source in sources:
        scraper_class = get_scraper_class(source['scraper'])
        if not scraper_class:
            print(f"Scraper não encontrado: {source['scraper']}")
            continue
            
        scraper = scraper_class(source['url'])
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                latest_article = scraper.get_latest_article()
                if latest_article:
                    history = load_history(source['history_file'])
                    
                    if latest_article['link'] != history.get('last_article_link'):
                        feed = generate_feed(source['name'], source['url'], latest_article)
                        save_feed(feed, source['feed_file'])
                        print(f"Feed RSS de {source['name']} gerado com sucesso! Salvo em feeds/{source['feed_file']}")
                        
                        history['last_article_link'] = latest_article['link']
                        save_history(source['history_file'], history)
                    else:
                        print(f"Nenhum artigo novo para {source['name']}. Feed não atualizado.")
                else:
                    print(f"Não foi possível obter o último artigo de {source['name']}.")
                
                break  # Se bem-sucedido, sai do loop
            except Exception as e:
                print(f"Erro ao processar {source['name']}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"Tentando novamente em 5 segundos...")
                    time.sleep(5)
                else:
                    print(f"Falha após {max_retries} tentativas para {source['name']}.")

if __name__ == "__main__":
    main()