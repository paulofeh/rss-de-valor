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

        # Clean HTML from description too
        if article['description']:
            article['description'] = BeautifulSoup(article['description'], 'html.parser').text

        return article


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
        """Resolve the URL path into a WP API filter (tags=<id> or categories=<id>)."""
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
        'GoogleAlertsScraper': GoogleAlertsScraper,
    }
    return scrapers.get(scraper_name)