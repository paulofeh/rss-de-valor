import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import datetime
import pytz
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import escape as html_escape

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

    def get_articles(self, limit=10):
        """Return a list of articles (up to *limit*).

        Default implementation wraps get_latest_article() in a list.
        Subclasses that can fetch multiple articles should override this.
        """
        article = self.get_latest_article()
        return [article] if article else []

    def _extract_article_data(self, soup):
        raise NotImplementedError("This method should be implemented by subclasses")

class ExistingRssScraper(BaseScraper):
    """Scraper for existing RSS feeds (no scraping needed)."""

    @staticmethod
    def _find_elem(parent, *tags):
        """Find the first matching element, avoiding the XML element bool() pitfall."""
        for tag in tags:
            elem = parent.find(tag)
            if elem is not None:
                return elem
        return None

    def _parse_item(self, item):
        """Parse a single RSS/Atom item element into an article dict."""
        # Extract title
        title_elem = self._find_elem(item, 'title', '{http://www.w3.org/2005/Atom}title')
        title = title_elem.text if title_elem is not None and title_elem.text else 'Título não encontrado'

        # Extract link
        link_elem = self._find_elem(item, 'link', '{http://www.w3.org/2005/Atom}link')
        if link_elem is not None:
            link = link_elem.get('href', link_elem.text if link_elem.text else '')
        else:
            link = ''

        # Extract description
        desc_elem = self._find_elem(item,
                    'description',
                    '{http://purl.org/rss/1.0/modules/content/}encoded',
                    '{http://www.w3.org/2005/Atom}summary',
                    '{http://www.w3.org/2005/Atom}content')
        description = desc_elem.text if desc_elem is not None and desc_elem.text else ''

        # Extract author
        author_elem = self._find_elem(item,
                      'author',
                      '{http://purl.org/dc/elements/1.1/}creator',
                      '{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name')
        author = author_elem.text if author_elem is not None and author_elem.text else 'Autor não encontrado'

        # Extract publication date
        pubdate = None
        date_elem = self._find_elem(item,
                    'pubDate',
                    '{http://purl.org/dc/elements/1.1/}date',
                    '{http://www.w3.org/2005/Atom}published',
                    '{http://www.w3.org/2005/Atom}updated')

        if date_elem is not None and date_elem.text:
            try:
                pubdate = parsedate_to_datetime(date_elem.text)
                if pubdate.tzinfo is None:
                    pubdate = pubdate.replace(tzinfo=pytz.UTC)
                else:
                    pubdate = pubdate.astimezone(pytz.UTC)
            except Exception:
                try:
                    pubdate = datetime.datetime.fromisoformat(date_elem.text.replace('Z', '+00:00'))
                    if pubdate.tzinfo is None:
                        pubdate = pubdate.replace(tzinfo=pytz.UTC)
                    else:
                        pubdate = pubdate.astimezone(pytz.UTC)
                except Exception:
                    pass

        if not pubdate:
            pubdate = datetime.datetime.now(pytz.UTC)

        return {
            'title': title,
            'link': link,
            'pubdate': pubdate,
            'author': author,
            'description': description
        }

    def _fetch_items(self):
        """Fetch and return all RSS/Atom item elements."""
        response = requests_retry_session().get(self.url, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        return items

    def get_latest_article(self):
        """Fetch and parse an existing RSS feed to get the latest article."""
        try:
            items = self._fetch_items()
            if not items:
                print(f"Nenhum item encontrado no feed: {self.url}")
                return None
            return self._parse_item(items[0])
        except Exception as e:
            print(f"Erro ao processar feed RSS {self.url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        """Fetch and parse up to *limit* articles from the RSS feed."""
        try:
            items = self._fetch_items()
            if not items:
                print(f"Nenhum item encontrado no feed: {self.url}")
                return []
            return [self._parse_item(item) for item in items[:limit]]
        except Exception as e:
            print(f"Erro ao processar feed RSS {self.url}: {str(e)}")
            return []

class GoogleAlertsScraper(ExistingRssScraper):
    """Scraper for Google Alerts RSS feeds.

    Extends ExistingRssScraper to clean up Google Alerts quirks:
    - Resolves google.com/url redirects to the real article URL
    - Strips HTML tags from titles (Google Alerts bolds the search terms)
    - Fetches full article content via trafilatura
    """

    def _parse_item(self, item):
        article = super()._parse_item(item)

        # Clean HTML from title
        article['title'] = BeautifulSoup(article['title'], 'html.parser').text

        # Resolve google.com/url redirect to real URL
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(article['link'])
        if parsed.netloc.endswith('google.com') and parsed.path == '/url':
            real_url = parse_qs(parsed.query).get('url', [''])[0]
            if real_url:
                article['link'] = real_url

        # Fetch full article content via trafilatura
        content = self._fetch_content(article['link'])
        if content:
            article['description'] = content
        elif article['description']:
            # Fallback: clean the Google Alerts snippet
            article['description'] = BeautifulSoup(article['description'], 'html.parser').text

        return article

    @staticmethod
    def _fetch_content(url):
        """Fetch and extract article content using trafilatura."""
        import trafilatura

        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return trafilatura.extract(downloaded, output_format='html', include_links=True)
        except Exception as e:
            print(f"Erro ao extrair conteúdo de {url}: {str(e)}")
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
    def _parse_feed_item(self, item):
        """Parse a single bastian-feed-item element."""
        title_el = item.select_one('h2.feed-post-link')
        link_el = item.select_one('a')
        date_el = item.select_one('span.feed-post-datetime')
        author_el = item.select_one('span.feed-post-metadata-section')
        desc_el = item.select_one('p.feed-post-body-resumo')

        if not (title_el and link_el):
            return None

        return {
            'title': title_el.text.strip(),
            'link': link_el['href'],
            'pubdate': self._parse_date(date_el.text.strip() if date_el else ''),
            'author': author_el.text.strip() if author_el else 'Autor Desconhecido',
            'description': desc_el.text.strip() if desc_el else '',
        }

    def _extract_article_data(self, soup):
        article = soup.select_one('div.bastian-feed-item')
        if article:
            return self._parse_feed_item(article)
        return None

    def _fetch_article_content(self, url):
        """Fetch full article content from individual article page.

        Returns HTML string with article body paragraphs, or None on failure.
        Filters out inline recommendation blocks (data-block-type="raw").
        """
        try:
            response = requests_retry_session().get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            body = soup.select_one('div.mc-article-body')
            if not body:
                return None
            paragraphs = []
            for div in body.select('div.content-text'):
                if div.get('data-block-type') == 'raw':
                    continue
                p = div.select_one('p.content-text__container')
                if p:
                    paragraphs.append(str(p))
            return '\n'.join(paragraphs) if paragraphs else None
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar conteúdo de {url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
            items = soup.select('div.bastian-feed-item')
            articles = []
            for item in items[:limit]:
                article = self._parse_feed_item(item)
                if article:
                    content = self._fetch_article_content(article['link'])
                    if content:
                        article['description'] = content
                    articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar {self.url}: {str(e)}")
            return []

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


class EstadaoSectionScraper(BaseScraper):
    """Scraper for Estadão section pages (e.g. /sustentabilidade/).

    Uses the Fusion/Arc CMS JSON embedded in the page to find the latest
    article, then fetches the article page to extract full content from
    its own Fusion.globalContent.content_elements.
    """
    BASE_URL = "https://www.estadao.com.br"

    def _build_article(self, article_meta, fetch_content=True):
        """Build an article dict from Fusion cache metadata, optionally fetching full content."""
        canonical = article_meta.get('canonical_url', '')
        article_url = canonical if canonical.startswith('http') else f"{self.BASE_URL}{canonical}"

        content_html = self._fetch_article_content(article_url) if fetch_content else None

        credits = article_meta.get('credits', {})
        authors = [a.get('name', '') for a in credits.get('by', [])]

        return {
            'title': article_meta.get('headlines', {}).get('basic', ''),
            'link': article_url,
            'pubdate': self._parse_date(article_meta.get('first_publish_date', '')),
            'author': ', '.join(authors) if authors else 'Estadão',
            'description': content_html or article_meta.get('subheadlines', {}).get('basic', ''),
        }

    def get_latest_article(self):
        """Fetch the section listing page and return the most recent article with full content."""
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            all_meta = self._find_articles_from_cache(soup)
            if not all_meta:
                return None

            return self._build_article(all_meta[0])
        except Exception as e:
            print(f"Erro ao processar seção {self.url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        """Fetch up to *limit* articles from the section page, with full content."""
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            all_meta = self._find_articles_from_cache(soup)
            return [self._build_article(meta) for meta in all_meta[:limit]]
        except Exception as e:
            print(f"Erro ao processar seção {self.url}: {str(e)}")
            return []

    def _find_articles_from_cache(self, soup):
        """Extract article metadata list from Fusion.contentCache, sorted by date desc."""
        import json as _json

        for script in soup.find_all('script'):
            text = script.string or ''
            if 'Fusion.contentCache' not in text:
                continue

            start = text.index('Fusion.contentCache=') + len('Fusion.contentCache=')
            end = text.index(';Fusion.', start)
            cache = _json.loads(text[start:end])

            story_feed = cache.get('story-feed-query', {})

            # Collect all articles from every query in the cache, deduplicating by _id
            seen_ids = set()
            all_articles = []
            for query_val in story_feed.values():
                data = query_val.get('data', {}) if isinstance(query_val, dict) else {}
                for el in data.get('content_elements', []):
                    aid = el.get('_id')
                    if aid and aid not in seen_ids:
                        seen_ids.add(aid)
                        all_articles.append(el)

            all_articles.sort(
                key=lambda a: a.get('first_publish_date', ''),
                reverse=True,
            )
            return all_articles

        return []

    def _fetch_article_content(self, url):
        """Fetch an article page and build HTML from its Fusion content_elements."""
        import json as _json

        try:
            response = requests_retry_session().get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            for script in soup.find_all('script'):
                text = script.string or ''
                if 'Fusion.globalContent' not in text:
                    continue

                start = text.index('Fusion.globalContent=') + len('Fusion.globalContent=')
                end = text.index(';Fusion.', start)
                data = _json.loads(text[start:end])

                elements = data.get('content_elements', [])
                if not elements:
                    return None

                parts = []
                for el in elements:
                    el_type = el.get('type')
                    if el_type == 'text':
                        parts.append(el.get('content', ''))
                    elif el_type == 'header':
                        level = el.get('level', 2)
                        parts.append(f"<h{level}>{el.get('content', '')}</h{level}>")
                return '\n'.join(parts) if parts else None

        except Exception as e:
            print(f"Erro ao buscar conteúdo de {url}: {str(e)}")
            return None

    def _parse_date(self, date_str):
        """Parse ISO 8601 date string."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class BloombergLineaScraper(BaseScraper):
    """Scraper for Bloomberg Línea Brasil sections via Arc/Fusion API.

    The URL should be in the format:
        https://www.bloomberglinea.com.br/<section-path>/
    e.g. https://www.bloomberglinea.com.br/esg/bloomberg-linea-green/
    """
    BASE_URL = "https://www.bloomberglinea.com.br"
    API_PATH = "/pf/api/v3/content/fetch/story-feed-sections"
    FILTER = (
        "{content_elements{_id,canonical_url,description{basic},"
        "display_date,headlines{basic},last_updated_date,subtype,"
        "taxonomy{primary_section{_id,name,path}},type,"
        "websites{bloomberg-linea-brasil{website_section{_id,name},website_url}}}}"
    )

    def _build_article(self, meta):
        """Build a full article dict from API metadata, fetching content from the article page."""
        canonical = meta.get('canonical_url', '')
        article_url = canonical if canonical.startswith('http') else f"{self.BASE_URL}{canonical}"
        content_html, author = self._fetch_article_content(article_url)

        return {
            'title': meta.get('headlines', {}).get('basic', ''),
            'link': article_url,
            'pubdate': self._parse_date(meta.get('display_date', '')),
            'author': author or 'Bloomberg Línea',
            'description': content_html or meta.get('description', {}).get('basic', ''),
        }

    def get_latest_article(self):
        try:
            elements = self._fetch_listing(1)
            if not elements:
                return None
            return self._build_article(elements[0])
        except Exception as e:
            print(f"Erro ao processar Bloomberg Línea {self.url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        try:
            elements = self._fetch_listing(limit)
            return [self._build_article(meta) for meta in elements]
        except Exception as e:
            print(f"Erro ao processar Bloomberg Línea {self.url}: {str(e)}")
            return []

    def _section_path(self):
        """Derive the Arc section path from the page URL (e.g. '/esg/bloomberg-linea-green')."""
        from urllib.parse import urlparse
        path = urlparse(self.url).path.strip('/')
        return f"/{path}"

    def _fetch_listing(self, size=1):
        """Fetch article metadata from the Arc API."""
        import json as _json
        from urllib.parse import quote

        query = _json.dumps({
            "excludeSections": "/videos",
            "feature": "medium-card-promo-bullet",
            "feedOffset": 0,
            "feedSize": size,
            "includeSections": self._section_path(),
        })

        api_url = (
            f"{self.BASE_URL}{self.API_PATH}"
            f"?query={quote(query)}"
            f"&filter={quote(self.FILTER)}"
            f"&_website=bloomberg-linea-brasil"
        )

        response = requests_retry_session().get(api_url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        })
        response.raise_for_status()
        data = response.json()

        return data.get('content_elements', [])

    def _fetch_article_content(self, url):
        """Fetch an article page and extract full content + author from Fusion.globalContent."""
        import json as _json

        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            for script in soup.find_all('script'):
                text = script.string or ''
                if 'Fusion.globalContent' not in text:
                    continue

                start = text.index('Fusion.globalContent=') + len('Fusion.globalContent=')
                end = text.index(';Fusion.', start)
                data = _json.loads(text[start:end])

                # Extract author
                credits = data.get('credits', {})
                authors = [a.get('name', '') for a in credits.get('by', [])]
                author = ', '.join(a for a in authors if a)

                # Extract content
                elements = data.get('content_elements', [])
                parts = []
                for el in elements:
                    el_type = el.get('type')
                    if el_type == 'text':
                        parts.append(el.get('content', ''))
                    elif el_type == 'header':
                        level = el.get('level', 2)
                        parts.append(f"<h{level}>{el.get('content', '')}</h{level}>")

                content_html = '\n'.join(parts) if parts else None
                return content_html, author

        except Exception as e:
            print(f"Erro ao buscar conteúdo de {url}: {str(e)}")

        return None, None

    def _parse_date(self, date_str):
        """Parse ISO 8601 date string."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class SustainableViewsScraper(BaseScraper):
    """Scraper for Sustainable Views (FT specialist service) category pages.

    The URL should be a category listing, e.g.:
        https://www.sustainableviews.com/category/daily-briefing/

    Listing pages are server-rendered and contain <aside> cards with
    category, date, title, and description.  Author is extracted from
    the article page's dataLayer script.
    """

    def _parse_aside(self, aside):
        """Parse a single <aside> card into an article dict (without author)."""
        texts = list(aside.stripped_strings)
        if len(texts) < 3:
            return None

        article_link = None
        for a in aside.select('a[href]'):
            href = a.get('href', '')
            if (href.startswith('https://www.sustainableviews.com/')
                    and href != 'https://www.sustainableviews.com/'
                    and '/category/' not in href):
                article_link = href
                break

        if not article_link:
            return None

        return {
            'title': texts[2] if len(texts) > 2 else '',
            'link': article_link,
            'pubdate': self._parse_date(texts[1] if len(texts) > 1 else ''),
            'author': 'Sustainable Views',
            'description': texts[3] if len(texts) > 3 else '',
        }

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            asides = soup.select('aside')
            if not asides:
                print(f"Nenhum artigo encontrado em {self.url}")
                return []

            articles = []
            for aside in asides[:limit]:
                article = self._parse_aside(aside)
                if article:
                    # Fetch author only for the first article to avoid too many requests
                    if not articles:
                        author = self._fetch_author(article['link'])
                        if author:
                            article['author'] = author
                    articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar Sustainable Views {self.url}: {str(e)}")
            return []

    def _fetch_author(self, url):
        """Fetch the article page and extract author from the dataLayer script."""
        import json as _json

        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            for script in soup.find_all('script'):
                text = script.string or ''
                if 'Article Entity Loaded' not in text:
                    continue

                start = text.index('data: {') + 6
                brace_count = 0
                for i, c in enumerate(text[start:], start):
                    if c == '{':
                        brace_count += 1
                    elif c == '}':
                        brace_count -= 1
                    if brace_count == 0:
                        data = _json.loads(text[start:i + 1])
                        return data.get('author_name', '')
        except Exception as e:
            print(f"Erro ao buscar autor de {url}: {str(e)}")

        return None

    def _parse_date(self, date_str):
        """Parse English date string like 'March 31, 2026'."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.strptime(date_str.strip(), "%B %d, %Y")
            return dt.replace(tzinfo=pytz.UTC)
        except ValueError:
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class BBCTopicScraper(BaseScraper):
    """Scraper for BBC News topic pages (e.g. /portuguese/topics/<id>).

    The listing page has server-rendered promo cards with title, link and date.
    The article page provides full content (no paywall) and author info.
    """

    def _parse_promo(self, promo):
        """Parse a promo card into a partial article dict (no content/author yet)."""
        h = promo.select_one('h2, h3')
        link = promo.select_one('a[href*="/articles/"]')
        if not (h and link):
            return None

        article_url = link.get('href', '')
        if not article_url.startswith('http'):
            article_url = f"https://www.bbc.com{article_url}"

        time_el = promo.select_one('time')
        date_str = time_el.get('datetime', '') if time_el else ''

        return {
            'title': h.text.strip(),
            'link': article_url,
            'pubdate': self._parse_date(date_str),
            'author': 'BBC News Brasil',
            'description': '',
        }

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            articles = []
            for promo in soup.select('div.promo-text'):
                article = self._parse_promo(promo)
                if not article:
                    continue

                # Fetch full content for each article
                author, content_html = self._fetch_article(article['link'])
                if author:
                    article['author'] = author
                if content_html:
                    article['description'] = content_html

                articles.append(article)
                if len(articles) >= limit:
                    break

            if not articles:
                print(f"Nenhum artigo encontrado em {self.url}")
            return articles
        except Exception as e:
            print(f"Erro ao processar BBC topic {self.url}: {str(e)}")
            return []

    def _fetch_article(self, url):
        """Fetch article page to extract author and full content."""
        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            main = soup.select_one('main')
            if not main:
                return None, None

            # Extract author from byline section
            author = None
            for section in main.select('section'):
                text = section.text.strip()
                if 'Author' in text and len(text) < 300:
                    spans = section.select('span')
                    for i, span in enumerate(spans):
                        if span.string and span.string.strip().startswith('Author'):
                            # The name is in the next sibling span
                            if i + 1 < len(spans) and spans[i + 1].string:
                                author = spans[i + 1].string.strip()
                                break
                    break

            # Extract content paragraphs
            parts = []
            for p in main.select('p'):
                text = p.text.strip()
                if (len(text) > 40
                        and not text.startswith('Crédito')
                        and not text.startswith('Legenda')
                        and 'Getty Images' not in text):
                    parts.append(f'<p>{text}</p>')

            content_html = '\n'.join(parts) if parts else None
            return author, content_html

        except Exception as e:
            print(f"Erro ao buscar artigo BBC {url}: {str(e)}")
            return None, None

    def _parse_date(self, date_str):
        """Parse ISO date string like '2026-03-23'."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class WordPressApiScraper(BaseScraper):
    """Scraper for WordPress sites via the WP REST API (/wp-json/wp/v2/posts).

    The URL should be the site root or a category/tag page, e.g.:
        https://nottus.com.br/noticias/
        https://revistapesquisa.fapesp.br/sustentabilidade/
    When a path segment is present (e.g. /sustentabilidade/), the scraper
    automatically resolves it as a tag or category slug to filter posts.
    """

    def _resolve_filter(self, parsed):
        """Resolve the URL path into a WP API filter (tags=<id>, categories=<id>, or custom taxonomy).

        Tries tags and categories first, then discovers custom taxonomies
        via /wp-json/wp/v2/taxonomies and searches each for a matching slug.
        """
        slug = parsed.path.strip('/').split('/')[-1] if parsed.path.strip('/') else ''
        if not slug or slug in ('noticias', 'blog', 'posts', 'news'):
            return ''

        base = f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2"
        # Try tags first, then categories
        for endpoint in ('tags', 'categories'):
            try:
                r = requests_retry_session().get(
                    f"{base}/{endpoint}?slug={slug}", timeout=15)
                if r.status_code == 200:
                    items = r.json()
                    if items:
                        return f"&{endpoint}={items[0]['id']}"
            except Exception:
                pass

        # Try custom taxonomies
        try:
            r = requests_retry_session().get(f"{base}/taxonomies", timeout=15)
            if r.status_code == 200:
                taxonomies = r.json()
                for tax_key, tax_info in taxonomies.items():
                    if tax_key in ('category', 'post_tag', 'nav_menu'):
                        continue
                    rest_base = tax_info.get('rest_base', tax_key)
                    try:
                        r2 = requests_retry_session().get(
                            f"{base}/{rest_base}?slug={slug}", timeout=15)
                        if r2.status_code == 200:
                            items = r2.json()
                            if items:
                                return f"&{rest_base}={items[0]['id']}"
                    except Exception:
                        pass
        except Exception:
            pass
        return ''

    def _parse_post(self, post):
        """Parse a WP REST API post object into an article dict."""
        title_html = post.get('title', {}).get('rendered', '')
        title = BeautifulSoup(title_html, 'html.parser').text.strip()

        embedded = post.get('_embedded', {})
        authors = embedded.get('author', [])
        author = authors[0].get('name', '') if authors else ''

        return {
            'title': title,
            'link': post.get('link', ''),
            'pubdate': self._parse_date(post.get('date_gmt', '')),
            'author': author or 'Autor não encontrado',
            'description': post.get('content', {}).get('rendered', ''),
        }

    def _fetch_posts(self, limit=1):
        """Fetch posts from the WP REST API."""
        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        filter_param = self._resolve_filter(parsed)
        api_url = f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts?per_page={limit}&_embed{filter_param}"

        response = requests_retry_session().get(api_url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        })
        response.raise_for_status()
        return response.json()

    def get_latest_article(self):
        try:
            posts = self._fetch_posts(1)
            if not posts:
                print(f"Nenhum post encontrado para {self.url}")
                return None
            return self._parse_post(posts[0])
        except Exception as e:
            print(f"Erro ao processar WordPress API {self.url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        try:
            posts = self._fetch_posts(limit)
            return [self._parse_post(post) for post in posts]
        except Exception as e:
            print(f"Erro ao processar WordPress API {self.url}: {str(e)}")
            return []

    def _parse_date(self, date_str):
        """Parse WordPress GMT date (ISO 8601 without timezone)."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str)
            return dt.replace(tzinfo=pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class CNNBrasilBlogScraper(BaseScraper):
    """Scraper for CNN Brasil blogs (custom post type) via their internal resolver API.

    CNN Brasil's blogs are a custom post type not exposed by /wp/v2/posts, and
    the per-blog tag has only a single post. The site exposes a custom endpoint
    /wp-json/content/v1/resolver/<url-encoded URL> that returns the full list of
    posts for any archive page, including blog/columnist pages such as
    https://www.cnnbrasil.com.br/blogs/pedro-cortes/.

    For each post, full body HTML is fetched from /wp-json/content/v1/posts/<slug>.
    """

    def _resolver_url(self):
        from urllib.parse import quote
        return f"https://www.cnnbrasil.com.br/wp-json/content/v1/resolver/{quote(self.url, safe='')}"

    def _post_detail_url(self, slug):
        return f"https://www.cnnbrasil.com.br/wp-json/content/v1/posts/{slug}"

    def _parse_date(self, date_str):
        """CNN publish_date comes as 'YYYY-MM-DD HH:MM:SS' in São Paulo time."""
        tz = pytz.timezone('America/Sao_Paulo')
        if not date_str:
            return datetime.datetime.now(tz)
        try:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return tz.localize(dt)
        except (ValueError, TypeError):
            return datetime.datetime.now(tz)

    def _author_name(self, post):
        author = post.get('author') or {}
        authors = author.get('list') or []
        if authors:
            return authors[0].get('name', '') or 'Autor não encontrado'
        return 'Autor não encontrado'

    def _fetch_full_content(self, slug):
        try:
            r = requests_retry_session().get(self._post_detail_url(slug), timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            r.raise_for_status()
            data = r.json()
            content = data.get('content')
            if isinstance(content, dict):
                # Prefer 'content' (rendered HTML, shortcodes expanded) over
                # 'raw' (which contains unprocessed [read_too] shortcodes).
                html = content.get('content') or content.get('rendered') or content.get('raw') or ''
            elif isinstance(content, str):
                html = content
            else:
                return ''
            return self._clean_content(html)
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar conteúdo do post {slug}: {str(e)}")
            return ''

    def _clean_content(self, html):
        """Strip the 'Leia mais' recommendation aside, which is navigation, not body."""
        if not html or '<aside' not in html:
            return html
        soup = BeautifulSoup(html, 'html.parser')
        for aside in soup.select('aside.read-too'):
            aside.decompose()
        return str(soup)

    def _parse_post(self, post, fetch_body=True):
        slug = post.get('slug', '')
        body = self._fetch_full_content(slug) if fetch_body else ''
        description = body or post.get('excerpt', '') or ''
        return {
            'title': post.get('title', '').strip(),
            'link': post.get('permalink', ''),
            'pubdate': self._parse_date(post.get('publish_date', '')),
            'author': self._author_name(post),
            'description': description,
        }

    def _fetch_posts(self):
        response = requests_retry_session().get(self._resolver_url(), timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        })
        response.raise_for_status()
        data = response.json()
        return data.get('data', {}).get('posts', []) or []

    def get_latest_article(self):
        try:
            posts = self._fetch_posts()
            if not posts:
                print(f"Nenhum post encontrado para {self.url}")
                return None
            return self._parse_post(posts[0])
        except Exception as e:
            print(f"Erro ao processar CNN Brasil blog {self.url}: {str(e)}")
            return None

    def get_articles(self, limit=10):
        try:
            posts = self._fetch_posts()
            return [self._parse_post(p) for p in posts[:limit]]
        except Exception as e:
            print(f"Erro ao processar CNN Brasil blog {self.url}: {str(e)}")
            return []

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_latest_article


class NatureRdfScraper(BaseScraper):
    """Scraper for Nature journals that use RDF/RSS 1.0 feeds.

    Parses the RDF feed for article links, then fetches each article page
    to extract the abstract from #Abs1-content.
    """

    RDF_NS = 'http://purl.org/rss/1.0/'
    DC_NS = 'http://purl.org/dc/elements/1.1/'

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            items = root.findall(f'{{{self.RDF_NS}}}item')
            articles = []
            for item in items[:limit]:
                article = self._parse_rdf_item(item)
                if article:
                    articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar feed Nature {self.url}: {str(e)}")
            return []

    def _parse_rdf_item(self, item):
        title_el = item.find(f'{{{self.RDF_NS}}}title')
        link_el = item.find(f'{{{self.RDF_NS}}}link')
        date_el = item.find(f'{{{self.DC_NS}}}date')
        creator_el = item.find(f'{{{self.DC_NS}}}creator')

        if title_el is None or link_el is None:
            return None

        title = title_el.text or ''
        link = link_el.text or ''
        author = creator_el.text if creator_el is not None else ''
        pubdate = self._parse_date(date_el.text if date_el is not None else '')

        abstract = self._fetch_abstract(link)

        return {
            'title': title,
            'link': link,
            'pubdate': pubdate,
            'author': author,
            'description': abstract or title,
        }

    def _fetch_abstract(self, url):
        """Fetch the article page and extract the abstract."""
        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            abstract = soup.select_one('#Abs1-content')
            if abstract:
                return str(abstract)
            return None
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar abstract de {url}: {str(e)}")
            return None

    def _parse_date(self, date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class DWTopicScraper(BaseScraper):
    """Scraper for DW (Deutsche Welle) topic pages via their GraphQL API.

    Expects a topic/navigation URL like:
      https://www.dw.com/en/climate/s-59752983
    Extracts the section ID from the URL and queries the GraphQL API
    for articles with full text.
    """

    GRAPHQL_URL = 'https://www.dw.com/graphql'

    def _extract_section_id(self):
        """Extract the numeric section ID from a DW URL like /en/climate/s-59752983."""
        import re
        match = re.search(r's-(\d+)', self.url)
        return int(match.group(1)) if match else None

    def get_articles(self, limit=10):
        try:
            section_id = self._extract_section_id()
            if not section_id:
                print(f"Erro: não foi possível extrair section ID de {self.url}")
                return []

            query = '''
            {
              content(id: %d) {
                ... on Navigation {
                  name
                  contentComposition {
                    informationSpaces {
                      compositionComponents {
                        contents {
                          ... on Article {
                            name
                            teaser
                            text
                            canonicalUrl
                            contentDate
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            ''' % section_id

            response = requests_retry_session().post(
                self.GRAPHQL_URL,
                json={'query': query},
                timeout=30,
                headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
            )
            response.raise_for_status()
            data = response.json()

            nav = data.get('data', {}).get('content', {})
            comp = nav.get('contentComposition', {})
            spaces = comp.get('informationSpaces', [])

            articles = []
            for space in spaces:
                for cc in space.get('compositionComponents', []):
                    for content in cc.get('contents', []):
                        if content and content.get('name') and content.get('canonicalUrl'):
                            articles.append({
                                'title': content['name'],
                                'link': content['canonicalUrl'],
                                'pubdate': self._parse_date(content.get('contentDate', '')),
                                'author': 'DW',
                                'description': content.get('text', '') or content.get('teaser', ''),
                            })
                            if len(articles) >= limit:
                                return articles
            return articles
        except Exception as e:
            print(f"Erro ao processar DW {self.url}: {str(e)}")
            return []

    def _parse_date(self, date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class BBCFutureScraper(BaseScraper):
    """Scraper for BBC Future (https://www.bbc.com/future).

    BBC Future has no official RSS feed. The hub page is server-rendered and
    exposes /future/article/YYYYMMDD-slug links. Each article page embeds a
    Next.js __NEXT_DATA__ JSON blob with structured content blocks, which we
    convert to HTML.
    """
    BASE_URL = "https://www.bbc.com"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }
    NEXT_DATA_RE = re.compile(
        r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.+?)</script>',
        re.DOTALL,
    )

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30, headers=self.HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            seen = set()
            article_urls = []
            for a in soup.select('a[href*="/future/article/"]'):
                href = (a.get('href') or '').split('?')[0].rstrip('/')
                if not href:
                    continue
                if not href.startswith('http'):
                    href = f"{self.BASE_URL}{href}"
                if href not in seen:
                    seen.add(href)
                    article_urls.append(href)

            if not article_urls:
                print(f"Nenhum artigo encontrado em {self.url}")
                return []

            articles = []
            for url in article_urls[:limit]:
                article = self._fetch_article(url)
                if article:
                    articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar BBC Future {self.url}: {str(e)}")
            return []

    def _fetch_article(self, url):
        import json as _json

        try:
            r = requests_retry_session().get(url, timeout=30, headers=self.HEADERS)
            r.raise_for_status()

            match = self.NEXT_DATA_RE.search(r.text)
            if not match:
                return None

            data = _json.loads(match.group(1))
            pp = data.get('props', {}).get('pageProps', {})
            md = pp.get('metadata', {})
            page = pp.get('page', {})
            if not isinstance(page, dict) or not page:
                return None

            article_data = next(iter(page.values()))
            contents = article_data.get('contents', []) if isinstance(article_data, dict) else []

            title = self._extract_title(contents) or md.get('seoHeadline') or md.get('promoHeadline') or ''
            author = self._clean_author(md.get('contributor', ''))
            pubdate = self._parse_timestamp(md.get('firstPublished'))
            description = self._render_contents(contents) or md.get('description', '')

            return {
                'title': title,
                'link': url,
                'pubdate': pubdate,
                'author': author or 'BBC Future',
                'description': description,
            }
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar artigo BBC Future {url}: {str(e)}")
            return None

    def _extract_title(self, contents):
        for blk in contents:
            if isinstance(blk, dict) and blk.get('type') == 'headline':
                return self._collect_text(blk).strip()
        return ''

    def _clean_author(self, text):
        if not text:
            return ''
        text = text.strip()
        if text.lower().startswith('by '):
            text = text[3:].strip()
        return text

    def _parse_timestamp(self, ts_ms):
        if not ts_ms:
            return datetime.datetime.now(pytz.UTC)
        try:
            return datetime.datetime.fromtimestamp(int(ts_ms) / 1000, tz=pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _render_contents(self, contents):
        """Render the structured contents list to an HTML string."""
        parts = []
        for blk in contents:
            if not isinstance(blk, dict):
                continue
            t = blk.get('type')
            if t == 'text':
                for para in blk.get('model', {}).get('blocks', []):
                    if isinstance(para, dict) and para.get('type') == 'paragraph':
                        rendered = self._render_paragraph(para)
                        if rendered:
                            parts.append(f'<p>{rendered}</p>')
            elif t == 'subheadline':
                rendered = html_escape(self._collect_text(blk).strip())
                if rendered:
                    parts.append(f'<h2>{rendered}</h2>')
        return '\n'.join(parts)

    def _render_paragraph(self, para):
        """Render a paragraph block to inline HTML, preserving links and emphasis."""
        out = []
        for f in para.get('model', {}).get('blocks', []):
            if not isinstance(f, dict):
                continue
            ft = f.get('type')
            model = f.get('model', {})
            if ft == 'fragment':
                text = html_escape(model.get('text', ''))
                attrs = model.get('attributes', []) or []
                if 'bold' in attrs:
                    text = f'<strong>{text}</strong>'
                if 'italic' in attrs:
                    text = f'<em>{text}</em>'
                out.append(text)
            elif ft == 'urlLink':
                href = html_escape(model.get('locator', ''), quote=True)
                inner = html_escape(self._collect_text(f))
                out.append(f'<a href="{href}">{inner}</a>')
            else:
                out.append(html_escape(self._collect_text(f)))
        return ''.join(out)

    def _collect_text(self, blk):
        """Recursively collect plain text from any nested block."""
        if not isinstance(blk, dict):
            return ''
        model = blk.get('model', {})
        if isinstance(model, dict):
            text = model.get('text')
            if text and not model.get('blocks'):
                return text
            inner = model.get('blocks', []) or []
            return ''.join(self._collect_text(b) for b in inner)
        return ''

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class YouTubeTranscriptScraper(BaseScraper):
    """Scraper for YouTube channels that fetches video transcripts.

    Expects the channel's Atom feed URL as input:
      https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID

    For each video, fetches the auto-generated or manual transcript
    via youtube-transcript-api. Shorts are skipped.
    """

    ATOM_NS = 'http://www.w3.org/2005/Atom'
    YT_NS = 'http://www.youtube.com/xml/schemas/2015'
    MEDIA_NS = 'http://search.yahoo.com/mrss/'

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            entries = root.findall(f'{{{self.ATOM_NS}}}entry')

            articles = []
            for entry in entries:
                if len(articles) >= limit:
                    break
                video_id = entry.find(f'{{{self.YT_NS}}}videoId').text
                if self._is_short(video_id):
                    continue
                article = self._parse_entry(entry, video_id)
                if article:
                    articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar feed YouTube {self.url}: {str(e)}")
            return []

    def _is_short(self, video_id):
        """Check if a video is a YouTube Short."""
        try:
            resp = requests_retry_session().get(
                f'https://www.youtube.com/shorts/{video_id}',
                timeout=15,
                headers={'User-Agent': 'Mozilla/5.0'},
                allow_redirects=False,
            )
            # Shorts return 200; regular videos redirect (303)
            return resp.status_code == 200
        except Exception:
            return False

    def _parse_entry(self, entry, video_id):
        title = entry.find(f'{{{self.ATOM_NS}}}title').text or ''
        published = entry.find(f'{{{self.ATOM_NS}}}published').text or ''
        media_group = entry.find(f'{{{self.MEDIA_NS}}}group')
        description = ''
        if media_group is not None:
            desc_el = media_group.find(f'{{{self.MEDIA_NS}}}description')
            if desc_el is not None and desc_el.text:
                description = desc_el.text

        link = f'https://www.youtube.com/watch?v={video_id}'
        pubdate = self._parse_date(published)

        transcript = self._fetch_transcript(video_id)

        return {
            'title': title,
            'link': link,
            'pubdate': pubdate,
            'author': '',
            'description': transcript or description,
        }

    def _fetch_transcript(self, video_id):
        """Fetch transcript for a video, preferring Portuguese."""
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            ytt = YouTubeTranscriptApi()
            transcript = ytt.fetch(video_id, languages=['pt', 'pt-BR', 'en'])
            text = ' '.join(snippet.text for snippet in transcript)
            return text if text else None
        except Exception as e:
            print(f"   ⚠️  Sem transcrição para {video_id}: {str(e)}")
            return None

    def _parse_date(self, date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


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
        'EstadaoSectionScraper': EstadaoSectionScraper,
        'BloombergLineaScraper': BloombergLineaScraper,
        'SustainableViewsScraper': SustainableViewsScraper,
        'BBCTopicScraper': BBCTopicScraper,
        'WordPressApiScraper': WordPressApiScraper,
        'CNNBrasilBlogScraper': CNNBrasilBlogScraper,
        'GoogleAlertsScraper': GoogleAlertsScraper,
        'NatureRdfScraper': NatureRdfScraper,
        'DWTopicScraper': DWTopicScraper,
        'BBCFutureScraper': BBCFutureScraper,
        'YouTubeTranscriptScraper': YouTubeTranscriptScraper,
    }
    return scrapers.get(scraper_name)