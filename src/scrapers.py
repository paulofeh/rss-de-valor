import re
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup, Comment
import datetime
import pytz
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import escape as html_escape
from urllib.parse import parse_qs, urljoin, unquote, urlparse

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

class FolhaRssFullContentScraper(ExistingRssScraper):
    """Scraper for Folha RSS feeds that enriches items with full article content."""

    DEFAULT_AUTHORS = {
        'antonioprata': 'Antonio Prata',
        'bernardo-carvalho': 'Bernardo Carvalho',
        'caos-planejado': 'Caos Planejado',
        'celso-rocha-de-barros': 'Celso Rocha de Barros',
        'conrado-hubner-mendes': 'Conrado Hubner Mendes',
        'de-grao-em-grao': 'De Grão em Grão',
        'drauziovarella': 'Dráuzio Varella',
        'ilona-szabo': 'Ilona Szabó',
        'joaopereiracoutinho': 'João Pereira Coutinho',
        'marceloviana': 'Marcelo Viana',
        'marcos-lisboa': 'Marcos Lisboa',
        'marcos-mendes': 'Marcos Mendes',
        'marilizpereirajorge': 'Mariliz Pereira Jorge',
        'maria-herminia-tavares': 'Maria Hermínia Tavares',
        'ronaldolemos': 'Ronaldo Lemos',
        'samuelpessoa': 'Samuel Pessoa',
        'tatibernardi': 'Tati Bernardi',
        'vera-iaconelli': 'Vera Iaconelli',
        'wilson-gomes': 'Wilson Gomes',
        'zecacamargo': 'Zeca Camargo',
    }

    @staticmethod
    def _resolve_folha_redirect(url):
        """Return the article URL hidden behind Folha's RSS redirection URL."""
        if not url:
            return url
        if 'redir.folha.com.br/redir/' in url and '*' in url:
            return unquote(url.split('*', 1)[1])
        return url

    def _parse_item(self, item):
        article = super()._parse_item(item)
        article['link'] = self._resolve_folha_redirect(article['link'])

        if article.get('author') == 'Autor não encontrado':
            for slug, author in self.DEFAULT_AUTHORS.items():
                if slug in self.url:
                    article['author'] = author
                    break

        content = self._fetch_article_content(article['link'])
        if content:
            article['description'] = content
            article['_enrichment_failed'] = False
        else:
            article['_enrichment_failed'] = True

        return article

    @staticmethod
    def _fetch_article_content(url):
        """Fetch and extract full Folha article content using trafilatura."""
        import trafilatura

        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            html = response.content.decode('utf-8', errors='replace')
            content = trafilatura.extract(
                html,
                output_format='html',
                include_links=True,
            )
            if not content:
                return None

            soup = BeautifulSoup(content, 'html.parser')
            body = soup.body
            return body.decode_contents().strip() if body else content
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar conteúdo da Folha em {url}: {str(e)}")
            return None

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

            if link:
                content = self._fetch_content(link)
                if content:
                    description = content

            return {
                'title': title,
                'link': link,
                'pubdate': date,
                'author': author,
                'description': description,
            }
        return None

    @staticmethod
    def _fetch_content(url):
        """Fetch and extract article content using trafilatura.

        Estadão article pages use styled-components with dynamic class names,
        so trafilatura's heuristic extraction is more robust than CSS selectors.
        """
        import trafilatura
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return trafilatura.extract(downloaded, output_format='html', include_links=True)
        except Exception as e:
            print(f"   ⚠️  Erro ao buscar conteúdo de {url}: {str(e)}")
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
    """Scraper for public LinkedIn newsletter pages with full article content."""
    
    def __init__(self, url):
        super().__init__(url)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def get_latest_article(self):
        """Fetch the latest article, preserving the legacy single-item API."""
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=5):
        """Fetch the public newsletter listing and enrich up to five articles.

        LinkedIn's public newsletter page exposes five issue cards. Each linked
        article is server-rendered and includes schema.org metadata plus an
        ``article-content-blocks`` container with the full newsletter body.
        """
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
                return []
                
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
            cards = soup.select('div.share-update-card')[:limit]
            if not cards:
                print(f"Nenhuma edição pública encontrada em {self.url}")
                return []

            articles = []
            for card in cards:
                article = self._extract_card_data(card, session)
                if article:
                    articles.append(article)
            return articles
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar {self.url}: {str(e)}")
            return []
    
    def _extract_article_data(self, soup):
        """Extract the first article from an already parsed newsletter page."""
        card = soup.select_one('div.share-update-card')
        if not card:
            return None
        return self._extract_card_data(card, requests_retry_session())

    def _extract_card_data(self, card, session):
        title_element = card.select_one('h3.share-article__title a')
        if not title_element or not title_element.get('href'):
            return None

        link = urljoin(self.url, title_element['href'])
        fallback_title = title_element.get_text(' ', strip=True)
        subtitle = card.select_one('h4.share-article__subtitle')
        fallback_description = subtitle.get_text(' ', strip=True) if subtitle else ''

        try:
            response = session.get(link, headers=self.headers, timeout=30)
            response.raise_for_status()
            article_soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')
            return self._extract_full_article(
                article_soup,
                response.url,
                fallback_title,
                fallback_description,
            )
        except requests.exceptions.RequestException as e:
            print(f"   ⚠️  Erro ao enriquecer artigo do LinkedIn {link}: {str(e)}")
            return {
                'title': fallback_title,
                'link': link,
                'pubdate': datetime.datetime.now(pytz.UTC),
                'author': 'Autor não encontrado',
                'description': fallback_description,
                '_enrichment_failed': True,
            }

    def _extract_full_article(self, soup, link, fallback_title, fallback_description):
        metadata = self._find_article_metadata(soup)

        title_element = soup.select_one('main article h1')
        title = (
            metadata.get('name')
            or (title_element.get_text(' ', strip=True) if title_element else '')
            or fallback_title
        )

        author_data = metadata.get('author')
        if isinstance(author_data, dict):
            author = author_data.get('name')
        elif isinstance(author_data, list):
            author = next(
                (item.get('name') for item in author_data if isinstance(item, dict) and item.get('name')),
                None,
            )
        else:
            author = None

        if not author:
            author_element = soup.select_one('main article h3.base-main-card__title')
            author = author_element.get_text(' ', strip=True) if author_element else 'Autor não encontrado'

        pubdate = self._parse_iso_date(metadata.get('datePublished'))
        article_content = self._extract_article_content(soup, link)
        description = article_content or fallback_description

        return {
            'title': title.strip(),
            'link': link,
            'pubdate': pubdate,
            'author': author.strip(),
            'description': description,
            '_enrichment_failed': not bool(article_content),
        }

    @classmethod
    def _find_article_metadata(cls, soup):
        """Return the schema.org Article object embedded in LinkedIn's JSON-LD."""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except (TypeError, ValueError):
                continue

            article = cls._find_article_object(data)
            if article:
                return article
        return {}

    @classmethod
    def _find_article_object(cls, data):
        if isinstance(data, dict):
            item_type = data.get('@type')
            if item_type in ('Article', 'NewsArticle'):
                return data
            for value in data.values():
                found = cls._find_article_object(value)
                if found:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = cls._find_article_object(value)
                if found:
                    return found
        return None

    @staticmethod
    def _parse_iso_date(value):
        if value:
            try:
                parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    return pytz.UTC.localize(parsed)
                return parsed.astimezone(pytz.UTC)
            except (TypeError, ValueError):
                pass
        return datetime.datetime.now(pytz.UTC)

    @classmethod
    def _extract_article_content(cls, soup, article_url):
        container = soup.select_one('[data-test-id="article-content-blocks"]')
        if not container:
            return None

        for unwanted in container.select('script, style, button'):
            unwanted.decompose()

        for comment in container.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        for image in container.find_all('img'):
            delayed_url = image.get('data-delayed-url')
            if delayed_url:
                image['src'] = delayed_url
            elif image.get('src'):
                image['src'] = urljoin(article_url, image['src'])

        for anchor in container.find_all('a', href=True):
            anchor['href'] = cls._clean_linkedin_url(anchor['href'], article_url)

        for span in container.find_all('span'):
            if 'font-[700]' in span.get('class', []):
                span.name = 'strong'
                span.attrs = {}
            else:
                span.unwrap()

        for text_node in container.find_all(string=True):
            if text_node.parent and text_node.parent.name in ('pre', 'code'):
                continue
            normalized = re.sub(r'[\s\u00a0]+', ' ', str(text_node))
            if normalized.strip():
                text_node.replace_with(normalized)
            else:
                text_node.extract()

        for tag in container.find_all(True):
            allowed_attributes = {}
            if tag.name == 'a' and tag.get('href'):
                allowed_attributes['href'] = tag['href']
            elif tag.name == 'img' and tag.get('src'):
                allowed_attributes['src'] = tag['src']
                if tag.get('alt'):
                    allowed_attributes['alt'] = re.sub(r'[\s\u00a0]+', ' ', tag['alt']).strip()
            tag.attrs = allowed_attributes

        blocks = []
        for block in container.find_all(recursive=False):
            content = block.decode_contents().strip()
            if content:
                blocks.append(content)
        return ''.join(blocks) or None

    @staticmethod
    def _clean_linkedin_url(href, article_url):
        absolute_url = urljoin(article_url, href)
        parsed = urlparse(absolute_url)
        if parsed.netloc.endswith('linkedin.com') and parsed.path == '/redir/redirect':
            destination = parse_qs(parsed.query).get('url', [None])[0]
            if destination:
                return destination
        return absolute_url


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


class BloombergGreenScraper(ExistingRssScraper):
    """Scraper for Bloomberg Green global articles.

    Uses Bloomberg's public Green RSS feed as the article index, then fetches
    each article page to extract the richer story body embedded in Next.js
    page data.
    """
    FEED_URL = "https://feeds.bloomberg.com/green/news.rss"
    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36'
        ),
    }
    CURL_USER_AGENT = "Mozilla/5.0"
    SKIP_BLOCK_TYPES = {
        'ad',
        'inline-newsletter',
        'inline-recirc',
        'media',
        'tabularData',
    }
    PROMOTIONAL_PATTERNS = (
        re.compile(r'^sign up here for\b', re.I),
        re.compile(r'^subscribe to bloomberg\b', re.I),
        re.compile(r'^explore all bloomberg newsletters\b', re.I),
        re.compile(r'^read more$', re.I),
    )

    def _fetch_items(self):
        """Fetch Bloomberg Green RSS items regardless of the configured page URL."""
        feed_url = self.url if self.url.endswith('.rss') else self.FEED_URL
        response = requests_retry_session().get(feed_url, timeout=30, headers=self.HEADERS)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        return root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            items = self._fetch_items()
            if not items:
                print(f"Nenhum item encontrado no feed Bloomberg Green: {self.FEED_URL}")
                return []

            articles = []
            for item in items[:limit]:
                article = super()._parse_item(item)
                enriched = self._fetch_article_data(article['link'])
                if enriched:
                    article.update({k: v for k, v in enriched.items() if v})
                articles.append(article)
            return articles
        except Exception as e:
            print(f"Erro ao processar Bloomberg Green {self.url}: {str(e)}")
            return []

    def _fetch_article_data(self, url):
        """Fetch an article page and extract metadata plus body from __NEXT_DATA__."""
        import json as _json

        try:
            html = self._fetch_article_html(url)
            soup = BeautifulSoup(html, 'html.parser')
            script = soup.find('script', id='__NEXT_DATA__')
            if not script or not script.string:
                return None

            data = _json.loads(script.string)
            story = (
                data.get('props', {})
                    .get('pageProps', {})
                    .get('story', {})
            )
            if not story:
                return None

            return {
                'title': story.get('headline') or story.get('title'),
                'author': self._extract_authors(story),
                'pubdate': self._parse_story_date(story),
                'description': self._extract_story_html(story),
            }
        except Exception as e:
            print(f"Erro ao buscar conteúdo Bloomberg Green {url}: {str(e)}")
            return None

    def _fetch_article_html(self, url):
        try:
            response = requests_retry_session().get(url, timeout=30, headers=self.HEADERS)
            response.raise_for_status()
            return response.content
        except requests.exceptions.HTTPError as e:
            if e.response is None or e.response.status_code != 403:
                raise

        # Bloomberg article pages currently block Python requests but allow curl.
        return self._fetch_article_html_with_curl(url)

    def _fetch_article_html_with_curl(self, url):
        import subprocess

        return subprocess.check_output([
            'curl',
            '-L',
            '--silent',
            '--show-error',
            '--max-time',
            '30',
            '-A',
            self.CURL_USER_AGENT,
            url,
        ])

    def _extract_story_html(self, story):
        """Render the Bloomberg story body into simple feed-safe HTML."""
        body = story.get('body', {})
        blocks = body.get('content', [])
        html_parts = []

        for block in blocks:
            rendered = self._render_block(block)
            if rendered:
                html_parts.append(rendered)

        return '\n'.join(html_parts)

    def _render_block(self, block):
        block_type = block.get('type')
        if block_type in self.SKIP_BLOCK_TYPES:
            return None

        text_html = self._render_inline(block.get('content', []))
        plain_text = self._plain_text(text_html)
        if not plain_text or self._is_promotional_text(plain_text):
            return None

        if block_type in ('heading', 'header'):
            level = block.get('data', {}).get('level', 2)
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = 2
            level = min(max(level, 2), 4)
            return f"<h{level}>{text_html}</h{level}>"

        if block_type in ('blockquote', 'quote'):
            return f"<blockquote>{text_html}</blockquote>"

        if block_type == 'list':
            items = []
            for child in block.get('content', []):
                item_html = self._render_inline(child.get('content', []))
                item_text = self._plain_text(item_html)
                if item_text and not self._is_promotional_text(item_text):
                    items.append(f"<li>{item_html}</li>")
            return f"<ul>{''.join(items)}</ul>" if items else None

        if block_type in ('paragraph', 'div', 'byTheNumbers'):
            return f"<p>{text_html}</p>"

        return None

    def _render_inline(self, nodes):
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            return ''

        rendered = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = node.get('type')

            if node_type == 'text':
                rendered.append(html_escape(node.get('value', '')))
                continue

            child_html = self._render_inline(node.get('content', []))
            if not child_html:
                continue

            if node_type == 'link':
                href = self._web_href(node)
                if href:
                    rendered.append(f'<a href="{html_escape(href)}">{child_html}</a>')
                else:
                    rendered.append(child_html)
            elif node_type in ('bold', 'strong'):
                rendered.append(f"<strong>{child_html}</strong>")
            elif node_type in ('italic', 'emphasis'):
                rendered.append(f"<em>{child_html}</em>")
            else:
                rendered.append(child_html)

        return ''.join(rendered)

    def _web_href(self, node):
        data = node.get('data', {})
        href = (
            data.get('href')
            or data.get('webUrl')
            or data.get('destination', {}).get('web')
            or data.get('data-web-url')
        )
        return href if href and href.startswith(('http://', 'https://')) else None

    def _plain_text(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        return ' '.join(soup.get_text(' ', strip=True).split())

    def _is_promotional_text(self, text):
        return any(pattern.search(text) for pattern in self.PROMOTIONAL_PATTERNS)

    def _extract_authors(self, story):
        authors = []
        for author in story.get('authors', []):
            if isinstance(author, dict):
                name = author.get('name')
                if name:
                    authors.append(name)
        return ', '.join(authors)

    def _parse_story_date(self, story):
        date_str = (
            story.get('publishedAt')
            or story.get('publishedDate')
            or story.get('published')
            or story.get('updatedAt')
        )
        if not date_str:
            return None
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            return None


class CDPInsightsScraper(BaseScraper):
    """Scraper for CDP Insights.

    CDP does not expose a real RSS feed for /en/insights, but the page ships
    its initial Contentful entries inside Next.js RSC payloads. This parser
    reads those entries directly and renders the embedded rich text.
    """
    BASE_URL = "https://www.cdp.net"
    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36'
        ),
    }

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30, headers=self.HEADERS)
            response.raise_for_status()
            html = response.content.decode('utf-8', errors='replace')
            items = self._extract_initial_insights(html)
            articles = [self._parse_insight(item) for item in items]
            articles.sort(key=lambda article: article['pubdate'], reverse=True)
            return articles[:limit]
        except Exception as e:
            print(f"Erro ao processar CDP Insights {self.url}: {str(e)}")
            return []

    def _extract_initial_insights(self, html):
        import json as _json

        soup = BeautifulSoup(html, 'html.parser')
        payload_parts = []

        for script in soup.find_all('script'):
            text = script.string or script.get_text() or ''
            match = re.search(r'self\.__next_f\.push\(\[1,(".*")\]\)', text, re.S)
            if not match:
                continue
            try:
                payload_parts.append(_json.loads(match.group(1)))
            except Exception:
                continue

        payload = '\n'.join(payload_parts)
        initial_insights = self._extract_json_array_after_key(payload, '"initialInsights":')
        if not initial_insights:
            return []

        entries = _json.loads(initial_insights)
        return [
            item for item in entries
            if isinstance(item, dict)
            and not item.get('fields', {}).get('hideInsight')
        ]

    @staticmethod
    def _extract_json_array_after_key(text, key):
        key_index = text.find(key)
        if key_index == -1:
            return None

        start = text.find('[', key_index + len(key))
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]

        return None

    def _parse_insight(self, item):
        fields = item.get('fields', {})
        slug = fields.get('slug', '')
        link = urljoin(f"{self.BASE_URL}/en/insights/", slug)

        return {
            'title': fields.get('title') or self._title_from_slug(slug),
            'link': link,
            'pubdate': self._parse_date(
                fields.get('date') or item.get('sys', {}).get('updatedAt')
            ),
            'author': 'CDP',
            'description': self._extract_description(fields),
        }

    def _extract_description(self, fields):
        content = self._render_page_layout(fields.get('pageLayout'))
        if content:
            return content

        description = self._render_rich_text(fields.get('description'))
        if description:
            return description

        seo_description = (
            fields.get('seoMetadata', {})
                  .get('fields', {})
                  .get('metaDescription', '')
        )
        return f"<p>{html_escape(seo_description)}</p>" if seo_description else ''

    def _render_page_layout(self, page_layout):
        if not isinstance(page_layout, list):
            return ''

        html_parts = []
        for section in page_layout:
            if not isinstance(section, dict):
                continue

            fields = section.get('fields', {})
            rendered = self._render_rich_text(fields.get('content'))
            if rendered:
                html_parts.append(rendered)

        return '\n'.join(html_parts)

    def _render_rich_text(self, node):
        if isinstance(node, str) or node is None:
            return ''
        if isinstance(node, list):
            return ''.join(self._render_rich_text(child) for child in node)
        if not isinstance(node, dict):
            return ''

        node_type = node.get('nodeType')
        children = ''.join(self._render_rich_text(child) for child in node.get('content', []))

        if node_type == 'document':
            return children
        if node_type == 'text':
            return self._render_text_node(node)
        if node_type == 'paragraph':
            return f"<p>{children}</p>" if self._strip_html_text(children) else ''
        if node_type and node_type.startswith('heading-'):
            level = node_type.rsplit('-', 1)[-1]
            if level not in {'1', '2', '3', '4', '5', '6'}:
                level = '2'
            return f"<h{level}>{children}</h{level}>" if self._strip_html_text(children) else ''
        if node_type == 'unordered-list':
            return f"<ul>{children}</ul>" if children else ''
        if node_type == 'ordered-list':
            return f"<ol>{children}</ol>" if children else ''
        if node_type == 'list-item':
            return f"<li>{children}</li>" if self._strip_html_text(children) else ''
        if node_type == 'blockquote':
            return f"<blockquote>{children}</blockquote>" if children else ''
        if node_type == 'hyperlink':
            uri = node.get('data', {}).get('uri', '')
            return self._wrap_link(uri, children)
        if node_type in {'entry-hyperlink', 'asset-hyperlink'}:
            uri = self._extract_target_uri(node.get('data', {}).get('target'))
            return self._wrap_link(uri, children)
        if node_type == 'embedded-asset-block':
            return self._render_asset(node.get('data', {}).get('target'))

        return children

    @staticmethod
    def _render_text_node(node):
        text = html_escape(node.get('value', '')).replace('\n', '<br/>')
        for mark in node.get('marks', []):
            mark_type = mark.get('type')
            if mark_type == 'bold':
                text = f"<strong>{text}</strong>"
            elif mark_type == 'italic':
                text = f"<em>{text}</em>"
            elif mark_type == 'underline':
                text = f"<u>{text}</u>"
            elif mark_type == 'code':
                text = f"<code>{text}</code>"
        return text

    def _wrap_link(self, uri, children):
        if not uri:
            return children
        return f'<a href="{html_escape(uri)}">{children}</a>'

    def _extract_target_uri(self, target):
        if not isinstance(target, dict):
            return ''

        fields = target.get('fields', {})
        if fields.get('slug'):
            return urljoin(f"{self.BASE_URL}/en/", fields['slug'])

        file_url = fields.get('file', {}).get('url', '')
        if file_url.startswith('//'):
            return f"https:{file_url}"
        return file_url

    def _render_asset(self, asset):
        if not isinstance(asset, dict):
            return ''

        fields = asset.get('fields', {})
        file_info = fields.get('file', {})
        url = file_info.get('url', '')
        if not url:
            return ''
        if url.startswith('//'):
            url = f"https:{url}"

        title = fields.get('title', '')
        description = fields.get('description', '')
        content_type = file_info.get('contentType', '')

        if content_type.startswith('image/'):
            image = f'<img src="{html_escape(url)}" alt="{html_escape(title)}"/>'
            caption = f"<figcaption>{html_escape(description)}</figcaption>" if description else ''
            return f"<figure>{image}{caption}</figure>"

        label = title or file_info.get('fileName') or url
        return f'<p><a href="{html_escape(url)}">{html_escape(label)}</a></p>'

    @staticmethod
    def _strip_html_text(value):
        return BeautifulSoup(value, 'html.parser').get_text(' ', strip=True)

    @staticmethod
    def _title_from_slug(slug):
        return slug.replace('-', ' ').strip().title() if slug else 'CDP Insight'

    @staticmethod
    def _parse_date(date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class ReutersSustainabilityScraper(BaseScraper):
    """Scraper for Reuters Sustainability via Reuters' public sitemap."""
    SITEMAP_URL = "https://www.reuters.com/arc/outboundfeeds/sitemap/?outputType=xml"
    SECTION_PREFIX = "https://www.reuters.com/sustainability/"
    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36'
        ),
    }
    SITEMAP_NAMESPACES = {
        'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
        'news': 'http://www.google.com/schemas/sitemap-news/0.9',
        'image': 'http://www.google.com/schemas/sitemap-image/1.1',
    }

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            articles = []
            seen_links = set()

            for offset in self._sitemap_offsets():
                for article in self._fetch_sitemap_articles(offset):
                    if article['link'] in seen_links:
                        continue
                    seen_links.add(article['link'])
                    articles.append(article)

            articles.sort(key=lambda article: article['pubdate'], reverse=True)
            return articles[:limit]
        except Exception as e:
            print(f"Erro ao processar Reuters Sustainability {self.url}: {str(e)}")
            return []

    def _sitemap_offsets(self):
        # The sitemap is sorted newest-first in 100-item pages. Sustainability
        # is mixed into the global feed, so scan a bounded window to keep
        # scheduled runs light.
        return [None] + list(range(100, 1100, 100))

    def _fetch_sitemap_articles(self, offset):
        url = self.SITEMAP_URL
        if offset:
            url = f"{url}&from={offset}"

        response = requests_retry_session().get(url, timeout=30, headers=self.HEADERS)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        articles = []
        for url_elem in root.findall('sm:url', self.SITEMAP_NAMESPACES):
            loc = self._find_text(url_elem, 'sm:loc')
            if not loc or not loc.startswith(self.SECTION_PREFIX):
                continue

            title = self._find_text(url_elem, 'news:news/news:title') or self._title_from_url(loc)
            pubdate = self._parse_date(
                self._find_text(url_elem, 'news:news/news:publication_date')
                or self._find_text(url_elem, 'sm:lastmod')
            )
            image_url = self._find_text(url_elem, 'image:image/image:loc')
            image_caption = self._find_text(url_elem, 'image:image/image:caption')

            articles.append({
                'title': title,
                'link': loc,
                'pubdate': pubdate,
                'author': 'Reuters',
                'description': self._build_description(image_url, image_caption),
            })

        return articles

    def _find_text(self, element, path):
        found = element.find(path, self.SITEMAP_NAMESPACES)
        return found.text.strip() if found is not None and found.text else ''

    @staticmethod
    def _build_description(image_url, image_caption):
        parts = []
        if image_url:
            parts.append(f'<p><img src="{html_escape(image_url)}"/></p>')
        if image_caption:
            parts.append(f"<p>{html_escape(image_caption)}</p>")
        return '\n'.join(parts)

    @staticmethod
    def _title_from_url(url):
        slug = url.rstrip('/').split('/')[-1]
        slug = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', slug)
        slug = re.sub(r'--[a-z0-9]+$', '', slug)
        title = slug.replace('-', ' ').strip().title()
        for acronym in ('Ai', 'Ceo', 'Cfo', 'Cop', 'Eu', 'Esg', 'Un', 'Us'):
            title = re.sub(rf'\b{acronym}\b', acronym.upper(), title)
        return title or 'Reuters Sustainability'

    @staticmethod
    def _parse_date(date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


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


class FiocruzClimaSaudeScraper(BaseScraper):
    """Scraper for the Observatório Clima e Saúde (Fiocruz) publications listing.

    Page lists publications grouped by year (h3) inside div.view-content. Each item
    is a div.views-row with title/link, theme and publication type. Links typically
    point to PDFs hosted elsewhere; only year-level dates are available.
    """

    BASE_URL = "https://climaesaude.icict.fiocruz.br"

    def get_latest_article(self):
        articles = self.get_articles(limit=1)
        return articles[0] if articles else None

    def get_articles(self, limit=10):
        try:
            response = requests_retry_session().get(self.url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser', from_encoding='utf-8')

            container = soup.select_one('div.view-content')
            if not container:
                print(f"Container .view-content não encontrado em {self.url}")
                return []

            sp_tz = pytz.timezone('America/Sao_Paulo')
            articles = []
            current_year = None
            year_index = 0

            for el in container.children:
                if getattr(el, 'name', None) == 'h3':
                    try:
                        current_year = int(el.get_text(strip=True))
                    except (ValueError, TypeError):
                        current_year = None
                    year_index = 0
                    continue

                if getattr(el, 'name', None) != 'div' or 'views-row' not in (el.get('class') or []):
                    continue
                if current_year is None:
                    continue

                article = self._parse_row(el, current_year, year_index, sp_tz)
                if article:
                    articles.append(article)
                    year_index += 1
                    if len(articles) >= limit:
                        break

            if not articles:
                print(f"Nenhuma publicação encontrada em {self.url}")
            return articles
        except Exception as e:
            print(f"Erro ao processar Fiocruz Clima e Saúde {self.url}: {str(e)}")
            return []

    def _parse_row(self, row, year, year_index, tz):
        link_el = row.select_one('.views-field-title a')
        if not link_el:
            return None

        title = link_el.get_text(strip=True)
        href = link_el.get('href', '').strip()
        if not (title and href):
            return None
        if href.startswith('/'):
            href = f"{self.BASE_URL}{href}"

        tema_el = row.select_one('.views-field-field-tema .field-content')
        tipo_el = row.select_one('.views-field-field-tipo-de-publica-o .field-content')
        tema = tema_el.get_text(strip=True) if tema_el else ''
        tipo = tipo_el.get_text(strip=True) if tipo_el else ''

        meta_parts = []
        if tipo:
            meta_parts.append(f"<strong>Tipo:</strong> {html_escape(tipo)}")
        if tema:
            meta_parts.append(f"<strong>Tema:</strong> {html_escape(tema)}")
        meta_parts.append(f"<strong>Ano:</strong> {year}")
        description = '<p>' + ' &middot; '.join(meta_parts) + '</p>'

        # Year-only date: anchor at Dec 31 of the year and decrement by minute per
        # position within the year, so the page's most-recent-first order is preserved
        # in the RSS feed.
        pubdate = tz.localize(datetime.datetime(year, 12, 31, 23, 59)) - datetime.timedelta(minutes=year_index)

        return {
            'title': title,
            'link': href,
            'pubdate': pubdate,
            'author': 'Observatório Clima e Saúde / Fiocruz',
            'description': description,
        }

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class WorldBankBlogScraper(BaseScraper):
    """Scraper for World Bank blog sections (e.g. /en/opendata, /en/climatechange).

    The listing page renders article cards as div.blog_teaser. Each card has the
    title, a relative link, a <time> element with a "Month DD, YYYY" date, and
    one or more author links pointing to /en/team/.... The article page itself
    has full content extractable via trafilatura.
    """

    BASE_URL = "https://blogs.worldbank.org"

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
            seen_links = set()
            for teaser in soup.select('div.blog_teaser'):
                article = self._parse_teaser(teaser)
                if not article or article['link'] in seen_links:
                    continue
                seen_links.add(article['link'])

                content_html = self._fetch_article_content(article['link'])
                if content_html:
                    article['description'] = content_html

                articles.append(article)
                if len(articles) >= limit:
                    break

            if not articles:
                print(f"Nenhum artigo encontrado em {self.url}")
            return articles
        except Exception as e:
            print(f"Erro ao processar World Bank blog {self.url}: {str(e)}")
            return []

    def _parse_teaser(self, teaser):
        title_link = teaser.select_one('h3.blog_teaser__title a, h3 a')
        if not title_link:
            return None
        title = title_link.get_text(strip=True)
        href = title_link.get('href', '').strip()
        if not (title and href):
            return None
        if href.startswith('/'):
            href = f"{self.BASE_URL}{href}"

        time_el = teaser.select_one('time')
        pubdate = self._parse_date(time_el.get_text(strip=True) if time_el else '')

        author_links = teaser.select('a[href*="/team/"]')
        authors = [a.get_text(strip=True) for a in author_links if a.get_text(strip=True)]
        author = ', '.join(authors) if authors else 'World Bank Blogs'

        return {
            'title': title,
            'link': href,
            'pubdate': pubdate,
            'author': author,
            'description': '',
        }

    def _fetch_article_content(self, url):
        """Fetch article page and extract full body content.

        World Bank blog articles render the authored body inside
        `.tui_container_col_10_offset_1`, with rich-text in `.cmp-text`,
        images in `.cmp-image`, embeds in `.cmp-embed`, and a topics/regions
        list at the bottom. We take the wrapper, strip boilerplate, and
        rewrite relative URLs. Falls back to trafilatura, then og:description.
        """
        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            wrapper = soup.select_one('.tui_container_col_10_offset_1')
            if wrapper:
                # Remove scripts, styles, and the trailing topics/regions list
                for tag in wrapper.find_all(['script', 'style']):
                    tag.decompose()
                for nav in wrapper.select('.listnavigation, .cmp-list'):
                    nav.decompose()
                # Rewrite relative hrefs/src to absolute
                for a in wrapper.find_all('a', href=True):
                    if a['href'].startswith('/'):
                        a['href'] = f"{self.BASE_URL}{a['href']}"
                for img in wrapper.find_all('img', src=True):
                    if img['src'].startswith('/'):
                        img['src'] = f"{self.BASE_URL}{img['src']}"
                content_html = wrapper.decode_contents().strip()
                if content_html:
                    return content_html

            # Fallback: trafilatura heuristic extraction
            import trafilatura
            content = trafilatura.extract(html, output_format='html', include_links=True)
            if content:
                return content

            og = soup.find('meta', property='og:description')
            if og and og.get('content'):
                return f"<p>{html_escape(og['content'].strip())}</p>"
            return None
        except Exception as e:
            print(f"Erro ao buscar artigo World Bank {url}: {str(e)}")
            return None

    def _parse_date(self, date_str):
        """Parse 'May 05, 2026' into a UTC datetime."""
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        try:
            dt = datetime.datetime.strptime(date_str, '%B %d, %Y')
            return pytz.UTC.localize(dt)
        except (ValueError, TypeError):
            return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


class WMONewsScraper(BaseScraper):
    """Scraper for the WMO News Portal."""

    BASE_URL = "https://wmo.int"

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
            seen_links = set()
            for row in soup.select('.view-news .views-row'):
                article = self._parse_news_card(row)
                if not article or article['link'] in seen_links:
                    continue
                seen_links.add(article['link'])

                content_html = self._fetch_article_content(article['link'])
                if content_html:
                    article['description'] = content_html

                articles.append(article)
                if len(articles) >= limit:
                    break

            if not articles:
                print(f"Nenhuma notícia encontrada em {self.url}")
            return articles
        except Exception as e:
            print(f"Erro ao processar WMO News {self.url}: {str(e)}")
            return []

    def _parse_news_card(self, row):
        link_el = row.select_one('a[href]')
        title_el = row.select_one('h2')
        if not link_el or not title_el:
            return None

        title = title_el.get_text(' ', strip=True)
        link = urljoin(self.BASE_URL, link_el.get('href', '').strip())
        if not title or not link:
            return None

        category_el = row.select_one('.uppercase')
        category = category_el.get_text(' ', strip=True) if category_el else ''

        date_el = row.select_one('span.text-sm, span.md\\:text-base')
        date_text = date_el.get_text(' ', strip=True) if date_el else ''
        pubdate = self._parse_date(date_text)

        image_el = row.select_one('img')
        description_parts = []
        if category:
            description_parts.append(f"<p><strong>{html_escape(category)}</strong></p>")
        if image_el and image_el.get('alt'):
            description_parts.append(f"<p>{html_escape(image_el['alt'].strip())}</p>")

        return {
            'title': title,
            'link': link,
            'pubdate': pubdate,
            'author': 'World Meteorological Organization',
            'description': ''.join(description_parts),
        }

    def _fetch_article_content(self, url):
        try:
            response = requests_retry_session().get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            })
            response.raise_for_status()
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            parts = []
            summary = soup.select_one('.field--name-field-summary')
            body = soup.select_one('.field--name-body')
            for section in (summary, body):
                if not section:
                    continue
                self._clean_content(section)
                content = section.decode_contents().strip()
                if content:
                    parts.append(content)

            if parts:
                return ''.join(parts)

            og_description = soup.find('meta', property='og:description')
            if og_description and og_description.get('content'):
                return f"<p>{html_escape(og_description['content'].strip())}</p>"

            import trafilatura
            content = trafilatura.extract(html, output_format='html', include_links=True)
            return content
        except Exception as e:
            print(f"Erro ao buscar notícia WMO {url}: {str(e)}")
            return None

    def _clean_content(self, section):
        for tag in section.find_all(['script', 'style']):
            tag.decompose()
        for a in section.find_all('a', href=True):
            a['href'] = urljoin(self.BASE_URL, a['href'])
        for img in section.find_all('img', src=True):
            img['src'] = urljoin(self.BASE_URL, img['src'])
        for img in section.find_all('img', srcset=True):
            img['srcset'] = self._absolutize_srcset(img['srcset'])

    def _absolutize_srcset(self, srcset):
        entries = []
        for entry in srcset.split(','):
            parts = entry.strip().split()
            if not parts:
                continue
            parts[0] = urljoin(self.BASE_URL, parts[0])
            entries.append(' '.join(parts))
        return ', '.join(entries)

    def _parse_date(self, date_str):
        if not date_str:
            return datetime.datetime.now(pytz.UTC)
        for date_format in ('%d %B %Y', '%d %b %Y'):
            try:
                dt = datetime.datetime.strptime(date_str, date_format)
                return pytz.UTC.localize(dt)
            except (ValueError, TypeError):
                continue
        return datetime.datetime.now(pytz.UTC)

    def _extract_article_data(self, soup):
        pass  # Logic is handled in get_articles


def get_scraper_class(scraper_name):
    """Get the scraper class by name."""
    scrapers = {
        'ExistingRssScraper': ExistingRssScraper,
        'FolhaRssFullContentScraper': FolhaRssFullContentScraper,
        'LinkedInNewsletterScraper': LinkedInNewsletterScraper,
        'ValorOGloboScraper': ValorOGloboScraper,
        'WashingtonPostScraper': WashingtonPostScraper,
        'FolhaScraper': FolhaScraper,
        'EstadaoColumnistScraper': EstadaoColumnistScraper,
        'Poder360Scraper': Poder360Scraper,
        'PaulGrahamScraper': PaulGrahamScraper,
        'EstadaoSectionScraper': EstadaoSectionScraper,
        'BloombergLineaScraper': BloombergLineaScraper,
        'BloombergGreenScraper': BloombergGreenScraper,
        'CDPInsightsScraper': CDPInsightsScraper,
        'ReutersSustainabilityScraper': ReutersSustainabilityScraper,
        'SustainableViewsScraper': SustainableViewsScraper,
        'BBCTopicScraper': BBCTopicScraper,
        'WordPressApiScraper': WordPressApiScraper,
        'CNNBrasilBlogScraper': CNNBrasilBlogScraper,
        'GoogleAlertsScraper': GoogleAlertsScraper,
        'NatureRdfScraper': NatureRdfScraper,
        'DWTopicScraper': DWTopicScraper,
        'BBCFutureScraper': BBCFutureScraper,
        'YouTubeTranscriptScraper': YouTubeTranscriptScraper,
        'FiocruzClimaSaudeScraper': FiocruzClimaSaudeScraper,
        'WorldBankBlogScraper': WorldBankBlogScraper,
        'WMONewsScraper': WMONewsScraper,
    }
    return scrapers.get(scraper_name)
