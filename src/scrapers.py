import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import datetime
import pytz
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

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

class ExistingRssScraper(BaseScraper):
    """Scraper for existing RSS feeds (no scraping needed)."""

    def get_latest_article(self):
        """Fetch and parse an existing RSS feed to get the latest article."""
        try:
            # Fetch the RSS feed
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()

            # Parse XML
            root = ET.fromstring(response.content)

            # Find namespace (if any)
            namespace = {}
            if root.tag.startswith('{'):
                # Extract namespace
                ns = root.tag[1:root.tag.index('}')]
                namespace = {'ns': ns}

            # Try to find items/entries (RSS 2.0 uses <item>, Atom uses <entry>)
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

            if not items:
                print(f"Nenhum item encontrado no feed: {self.url}")
                return None

            # Get the first (most recent) item
            item = items[0]

            # Extract title
            title_elem = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
            title = title_elem.text if title_elem is not None and title_elem.text else 'Título não encontrado'

            # Extract link
            link_elem = item.find('link') or item.find('{http://www.w3.org/2005/Atom}link')
            if link_elem is not None:
                # Atom feeds use link as an attribute
                link = link_elem.get('href', link_elem.text if link_elem.text else '')
            else:
                link = ''

            # Extract description
            desc_elem = (item.find('description') or
                        item.find('{http://purl.org/rss/1.0/modules/content/}encoded') or
                        item.find('{http://www.w3.org/2005/Atom}summary') or
                        item.find('{http://www.w3.org/2005/Atom}content'))
            description = desc_elem.text if desc_elem is not None and desc_elem.text else ''

            # Extract author
            author_elem = (item.find('author') or
                          item.find('{http://purl.org/dc/elements/1.1/}creator') or
                          item.find('{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name'))
            author = author_elem.text if author_elem is not None and author_elem.text else 'Autor não encontrado'

            # Extract publication date
            pubdate = None
            date_elem = (item.find('pubDate') or
                        item.find('{http://purl.org/dc/elements/1.1/}date') or
                        item.find('{http://www.w3.org/2005/Atom}published') or
                        item.find('{http://www.w3.org/2005/Atom}updated'))

            if date_elem is not None and date_elem.text:
                try:
                    # Try parsing RFC 822 format (RSS 2.0)
                    pubdate = parsedate_to_datetime(date_elem.text)
                    # Convert to UTC if not already
                    if pubdate.tzinfo is None:
                        pubdate = pubdate.replace(tzinfo=pytz.UTC)
                    else:
                        pubdate = pubdate.astimezone(pytz.UTC)
                except Exception:
                    try:
                        # Try ISO 8601 format (Atom)
                        pubdate = datetime.datetime.fromisoformat(date_elem.text.replace('Z', '+00:00'))
                        if pubdate.tzinfo is None:
                            pubdate = pubdate.replace(tzinfo=pytz.UTC)
                        else:
                            pubdate = pubdate.astimezone(pytz.UTC)
                    except Exception:
                        pass

            # If still no date, use current time
            if not pubdate:
                pubdate = datetime.datetime.now(pytz.UTC)

            return {
                'title': title,
                'link': link,
                'pubdate': pubdate,
                'author': author,
                'description': description
            }

        except Exception as e:
            print(f"Erro ao processar feed RSS {self.url}: {str(e)}")
            return None

class Poder360Scraper(BaseScraper):
    """Scraper for Poder360 columnist articles."""
    
    def _extract_article_data(self, soup):
        # Find the most recent article in the archive list
        article = soup.select_one('ul.archive-list__list li')
        
        if article:
            # Extract title
            title_element = article.select_one('h2.archive-list__title-2 a')
            title = title_element.text.strip() if title_element else "Título não encontrado"
            
            # Extract link
            link = title_element['href'] if title_element else ""
            
            # Extract date
            date_element = article.select_one('span.archive-list__date')
            date_str = date_element.text.strip() if date_element else ""
            date = self._parse_date(date_str)
            
            # Extract author from the profile or page title
            author_element = soup.select_one('h2.box-profile-author__title')
            author = author_element.text.strip() if author_element else "Autor Desconhecido"
            
            # Extract description/summary
            description_element = article.select_one('div.archive-list__text p')
            description = description_element.text.strip() if description_element else ""
            
            # Extract category/tag
            tag_element = article.select_one('a.archive-list__tag')
            tag = tag_element.text.strip() if tag_element else ""
            
            # Add tag to description if available
            if tag and description:
                description = f"[{tag}] {description}"
            
            return {
                'title': title,
                'link': link,
                'pubdate': date,
                'author': author,
                'description': description,
            }
            
        return None
    
    def _parse_date(self, date_str):
        """Parse date from Poder360 format (e.g., "24.fev.2025")."""
        try:
            # Map Portuguese month abbreviations to numbers
            month_map = {
                'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
                'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
            }
            
            # Split the date string
            parts = date_str.split('.')
            if len(parts) == 3:
                day = int(parts[0])
                month_abbr = parts[1].lower()
                year = int(parts[2])
                
                # Convert month abbreviation to number
                month = month_map.get(month_abbr, 1)  # Default to January if not found
                
                # Create datetime object
                return datetime.datetime(year, month, day, tzinfo=pytz.timezone('America/Sao_Paulo'))
        except (ValueError, IndexError) as e:
            print(f"Erro ao analisar a data '{date_str}': {e}")
        
        # Default to current time if parsing fails
        return datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).replace(microsecond=0)

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
            
            headline_elem = article.select_one('h2.headline')
            link_element = headline_elem.find_parent('a') if headline_elem else None
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

class LinkedInNewsletterScraper(BaseScraper):
    """Scraper for LinkedIn Newsletter articles."""
    
    def __init__(self, url):
        super().__init__(url)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def get_latest_article(self):
        """Fetch and extract the latest article data."""
        try:
            session = requests_retry_session()
            response = session.get(
                self.url,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            if 'login' in response.url.lower() or 'authenticate' in response.url.lower():
                print(f"LinkedIn está solicitando autenticação para {self.url}")
                return None
                
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
            return self._extract_article_data(soup)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar {self.url}: {str(e)}")
            return None
    
    def _extract_article_data(self, soup):
        """Extract data from LinkedIn newsletter page."""
        # Find all article updates in the newsletter
        articles = soup.select('div.share-update-card')
        if not articles:
            return None
            
        # Get the most recent article (first one)
        latest_article = articles[0]
        
        # Extract article title
        title_element = latest_article.select_one('h3.share-article__title a')
        title = title_element.text.strip() if title_element else "No title found"
        
        # Extract article link
        link = title_element['href'] if title_element else ""
        
        # Extract author information from the profile card
        author_element = soup.select_one('h3.profile-card__header-name')
        author = author_element.text.strip() if author_element else "Unknown Author"
        
        # Extract article description/subtitle
        description_element = latest_article.select_one('h4.share-article__subtitle')
        description = description_element.text.strip() if description_element else ""
        
        # For LinkedIn newsletters, we'll use the current time as publication date
        pubdate = datetime.datetime.now(pytz.UTC)
        
        return {
            'title': title,
            'link': link,
            'pubdate': pubdate,
            'author': author,
            'description': description
        }
        
    def _parse_date(self, date_str):
        """
        LinkedIn shows relative dates (e.g., "3mo", "1w") which are difficult to parse precisely.
        For now, we'll return current time as this would need more complex logic to handle all cases.
        """
        return datetime.datetime.now(pytz.UTC)


class PaulGrahamScraper(BaseScraper):
    """Scraper for Paul Graham essays from paulgraham.com/articles.html."""
    BASE_URL = "https://paulgraham.com"

    MONTHS = {
        'January': 1, 'February': 2, 'March': 3, 'April': 4,
        'May': 5, 'June': 6, 'July': 7, 'August': 8,
        'September': 9, 'October': 10, 'November': 11, 'December': 12
    }

    def get_latest_article(self):
        """Fetch the articles listing and return the most recent essay with full content."""
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Page structure: table[0]=nav, table[1]=recommended intro,
            # table[2]=full article listing (newest first), table[3]=footer.
            # We want the first article link from table[2].
            tables = soup.find_all('table')
            if len(tables) < 3:
                print(f"Estrutura inesperada da página {self.url}")
                return None

            article_listing_table = tables[2]
            article_links = [
                a for a in article_listing_table.find_all('a', href=True)
                if a['href'].endswith('.html')
                and not a['href'].startswith('http')
                and a.text.strip()
            ]

            if not article_links:
                print(f"Nenhum artigo encontrado em {self.url}")
                return None

            # First link is the most recent essay
            first_link = article_links[0]
            title = first_link.text.strip()
            article_url = f"{self.BASE_URL}/{first_link['href']}"

            return self._fetch_article(title, article_url)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar {self.url}: {str(e)}")
            return None

    def _fetch_article(self, title, url):
        """Fetch a Paul Graham essay page and extract its full content."""
        try:
            response = requests_retry_session().get(url, timeout=30)
            response.raise_for_status()
            # Pages are ISO-8859-1 encoded
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='ISO-8859-1')

            # Content is inside <font face="verdana"> in the second table
            tables = soup.find_all('table')
            font = tables[1].find('font', {'face': 'verdana'}) if len(tables) >= 2 else None
            if not font:
                print(f"Conteúdo não encontrado em {url}")
                return None

            date = self._extract_date(font)
            content_html = self._extract_content(font)

            return {
                'title': title,
                'link': url,
                'pubdate': date,
                'author': 'Paul Graham',
                'description': content_html,
            }
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar artigo {url}: {str(e)}")
            return None

    def _extract_date(self, font_tag):
        """Extract publication date from the font tag's opening text (e.g. 'June 2025')."""
        pattern = re.compile(
            r'^(' + '|'.join(self.MONTHS.keys()) + r')\s+(\d{4})$'
        )
        for text in font_tag.stripped_strings:
            match = pattern.match(text.strip())
            if match:
                month = self.MONTHS[match.group(1)]
                year = int(match.group(2))
                return datetime.datetime(year, month, 1, tzinfo=pytz.UTC)
            break  # Date is always the first text node; stop after first check
        return datetime.datetime.now(pytz.UTC)

    def _extract_content(self, font_tag):
        """Convert <br/><br/>-separated content to HTML paragraphs, skipping the date."""
        html = font_tag.decode_contents()

        # Remove leading date text (before the first <br/>)
        html = re.sub(r'^[^<]*', '', html).lstrip()

        # Normalise <br> variants
        html = re.sub(r'<br\s*/?>', '<br/>', html, flags=re.IGNORECASE)

        # Split on double line breaks (paragraph separators)
        paragraphs = re.split(r'<br/>\s*<br/>', html)

        return '\n'.join(
            f'<p>{para.strip()}</p>'
            for para in paragraphs
            if para.strip()
        )

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


def get_scraper_class(scraper_name):
    """Get the scraper class by name."""
    scrapers = {
        'ExistingRssScraper': ExistingRssScraper,
        'LinkedInNewsletterScraper': LinkedInNewsletterScraper,
        'ValorOGloboScraper': ValorOGloboScraper,
        'WashingtonPostScraper': WashingtonPostScraper,
        'FolhaScraper': FolhaScraper,
        'EstadaoColumnistScraper': EstadaoColumnistScraper,
        'Poder360Scraper': Poder360Scraper,
        'PaulGrahamScraper': PaulGrahamScraper,
    }
    return scrapers.get(scraper_name)