import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import datetime
import pytz

def requests_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None,
    timeout=30,  # Aumentado o timeout padrão
):
    """Configure requests session with retry capabilities."""
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

class BaseScraper:
    """Base scraper class with common functionality."""
    def __init__(self, url):
        self.url = url

    def get_latest_article(self):
        """Fetch and extract the latest article data."""
        try:
            # Aumentado o timeout para 30 segundos
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
            return self._extract_article_data(soup)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar {self.url}: {str(e)}")
            return None

    def _extract_article_data(self, soup):
        raise NotImplementedError("This method should be implemented by subclasses")

class ValorOGloboScraper(BaseScraper):
    """Scraper for Valor/O Globo articles."""
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
    """Scraper for Washington Post articles."""
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
            return datetime.datetime.strptime(date_str, "%B %d, %Y").replace(tzinfo=pytz.timezone('US/Eastern'))
        except ValueError:
            print(f"Não foi possível analisar a data: {date_str}")
            return datetime.datetime.now(pytz.timezone('US/Eastern'))

class FolhaScraper(BaseScraper):
    """Scraper for Folha articles."""
    def _extract_article_data(self, soup):
        article = soup.select_one('div.c-headline.c-headline--opinion')
        if article:
            title = article.select_one('h2.c-headline__title').text.strip()
            link = article.select_one('a.c-headline__url')['href']
            date_str = article.select_one('time.c-headline__dateline')['datetime']
            
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
            return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.timezone('America/Sao_Paulo'))
        except ValueError:
            print(f"Formato de data não reconhecido: {date_str}. Usando a data atual.")
            return datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).replace(microsecond=0)

class EstadaoColumnistScraper(BaseScraper):
    """Scraper for Estadão columnist articles."""
    def _extract_article_data(self, soup):
        article = soup.select_one('div.manchete-dia-a-dia-block-container')
        if article:
            title_element = article.select_one('h2.headline')
            title = title_element.text.strip() if title_element else "No title found"
            
            link_element = article.select_one('a')
            link = link_element['href'] if link_element else ""
            
            description_element = article.select_one('p.subheadline')
            description = description_element.text.strip() if description_element else ""
            
            author_element = article.select_one('div.chapeu span')
            author = author_element.text.strip() if author_element else "Autor Desconhecido"
            
            latest_article = soup.select_one('div.noticias-mais-recenter--item')
            if latest_article:
                date_element = latest_article.select_one('span.date')
                date_str = date_element.text.strip() if date_element else ""
                date = self._parse_date(date_str)
            else:
                date = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
            
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
            date_str = date_str.replace('Por', '').strip()
            
            date_parts = date_str.split(',')
            if len(date_parts) == 2:
                date_part = date_parts[0].strip()
                time_part = date_parts[1].strip().replace('h', ':')
                
                datetime_str = f"{date_part} {time_part}"
                return datetime.datetime.strptime(datetime_str, "%d/%m/%Y %H:%M").replace(
                    tzinfo=pytz.timezone('America/Sao_Paulo')
                )
        except ValueError as e:
            print(f"Erro ao analisar a data '{date_str}': {e}")
            
        return datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).replace(microsecond=0)

def get_scraper_class(scraper_name):
    """Get the scraper class by name."""
    scrapers = {
        'ValorOGloboScraper': ValorOGloboScraper,
        'WashingtonPostScraper': WashingtonPostScraper,
        'FolhaScraper': FolhaScraper,
        'EstadaoColumnistScraper': EstadaoColumnistScraper,
    }
    return scrapers.get(scraper_name)