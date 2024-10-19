import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import datetime
import pytz
from feedgenerator import Rss201rev2Feed
import os
import json
import time

def requests_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Base scraper class
class BaseScraper:
    def __init__(self, url):
        self.url = url

    def get_latest_article(self):
        try:
            response = requests_retry_session().get(self.url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            return self._extract_article_data(soup)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar {self.url}: {e}")
            return None

    def _extract_article_data(self, soup):
        raise NotImplementedError("This method should be implemented by subclasses")

# Valor/O Globo scraper
class ValorOGloboScraper(BaseScraper):
    def _extract_article_data(self, soup):
        article = soup.select_one('div.bastian-feed-item')
        if article:
            title = article.select_one('h2.feed-post-link').text.strip()
            link = article.select_one('a')['href']
            date_str = article.select_one('span.feed-post-datetime').text.strip()
            author = article.select_one('span.feed-post-metadata-section').text.strip()
            description_element = article.select_one('p.feed-post-body-resumo')
            description = description_element.text.strip() if description_element else ""
            
            date = self._parse_date(date_str)
            
            return {
                'title': title,
                'link': link,
                'pubdate': date,
                'author': author,
                'description': description,
            }
        return None

    def _parse_date(self, date_str):
        now = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        
        if 'Há' in date_str:
            if 'minutos' in date_str or 'hora' in date_str:
                return now.replace(microsecond=0)
            elif 'dia' in date_str:
                days = int(date_str.split()[1])
                return (now - datetime.timedelta(days=days)).replace(microsecond=0)
        elif date_str.lower() == 'ontem':
            return (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_str.lower() == 'hoje':
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            try:
                return datetime.datetime.strptime(date_str, "%d/%m/%Y %H:%M").replace(tzinfo=pytz.timezone('America/Sao_Paulo'))
            except ValueError:
                print(f"Formato de data não reconhecido: {date_str}. Usando a data atual.")
                return now.replace(microsecond=0)

class WashingtonPostScraper(BaseScraper):
    def _extract_article_data(self, soup):
        articles = soup.select('div[data-feature-id="homepage/story"]')
        if not articles:
            return None

        latest_article = articles[0]
        
        title_element = latest_article.select_one('h3[data-qa="card-title"]')
        title = title_element.text.strip() if title_element else "No title found"

        link_element = latest_article.select_one('a[data-pb-local-content-field="web_headline"]')
        link = link_element['href'] if link_element else ""

        description_element = latest_article.select_one('p.font-size-blurb')
        description = description_element.text.strip() if description_element else ""

        author_elements = latest_article.select('span.wpds-c-iVfWzS a')
        authors = [author.text.strip() for author in author_elements]
        author = ", ".join(authors) if authors else "Unknown Author"

        date_element = latest_article.select_one('span[data-testid="timestamp"]')
        date_str = date_element.text.strip() if date_element else ""
        date = self._parse_date(date_str)

        return {
            'title': title,
            'link': link,
            'pubdate': date,
            'author': author,
            'description': description,
        }

    def _parse_date(self, date_str):
        try:
            # Assumindo que a data está no formato "Month Day, Year"
            return datetime.datetime.strptime(date_str, "%B %d, %Y").replace(tzinfo=pytz.timezone('US/Eastern'))
        except ValueError:
            print(f"Não foi possível analisar a data: {date_str}")
            return datetime.datetime.now(pytz.timezone('US/Eastern'))
        
class FolhaScraper(BaseScraper):
    def _extract_article_data(self, soup):
        article = soup.select_one('div.c-headline.c-headline--opinion')
        if article:
            title = article.select_one('h2.c-headline__title').text.strip()
            link = article.select_one('a.c-headline__url')['href']
            date_str = article.select_one('time.c-headline__dateline')['datetime']
            
            # Extrair o nome do autor dinamicamente
            author_element = soup.select_one('div[data-qa="kicker"]')
            author = author_element.text.strip() if author_element else "Autor Desconhecido"
            
            description_element = article.select_one('p.c-headline__standfirst')
            description = description_element.text.strip() if description_element else ""
            
            date = self._parse_date(date_str)
            
            return {
                'title': title,
                'link': link,
                'pubdate': date,
                'author': author,
                'description': description,
            }
        return None

    def _parse_date(self, date_str):
        try:
            # A data vem no formato "YYYY-MM-DD HH:MM:SS"
            return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.timezone('America/Sao_Paulo'))
        except ValueError:
            print(f"Formato de data não reconhecido: {date_str}. Usando a data atual.")
            return datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).replace(microsecond=0)

# RSS feed generator
def generate_feed(source_name, url, article):
    feed = Rss201rev2Feed(
        title=f"{source_name}",
        link=url,
        description=f"Latest articles from {source_name}",
        language="en-US",
    )

    feed.add_item(
        title=article['title'],
        link=article['link'],
        pubdate=article['pubdate'],
        description=article['description'],
        author_name=article['author'],
    )

    return feed

def save_feed(feed, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        feed.write(f, 'utf-8')

def load_history(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

def save_history(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f)

def load_sources_config(filename='sources_config.json'):
    with open(filename, 'r') as f:
        config = json.load(f)
    return config['sources']

def get_scraper_class(scraper_name):
    return globals()[scraper_name]

def main():
    sources = load_sources_config()
    
    for source in sources:
        scraper_class = get_scraper_class(source['scraper'])
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
                        print(f"RSS feed for {source['name']} generated successfully! Saved as '{source['feed_file']}'")
                        
                        history['last_article_link'] = latest_article['link']
                        save_history(source['history_file'], history)
                    else:
                        print(f"No new article for {source['name']}. Feed not updated.")
                else:
                    print(f"Couldn't fetch the latest article for {source['name']}.")
                
                break  # Se bem-sucedido, saia do loop
            except Exception as e:
                print(f"Erro ao processar {source['name']}: {e}")
                if attempt < max_retries - 1:
                    print(f"Tentando novamente em 5 segundos...")
                    time.sleep(5)
                else:
                    print(f"Falha após {max_retries} tentativas para {source['name']}.")

if __name__ == "__main__":
    main()