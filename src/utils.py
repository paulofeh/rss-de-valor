import os
import json
from feedgenerator import Rss201rev2Feed
from datetime import datetime
import pytz
from xml.etree import ElementTree as ET

# Constante para a URL base do GitHub Pages
GITHUB_PAGES_BASE_URL = "https://paulofeh.github.io/rss-de-valor"

class CustomRssFeed(Rss201rev2Feed):
    def root_attributes(self):
        attrs = super().root_attributes()
        attrs['xmlns:atom'] = 'http://www.w3.org/2005/Atom'
        return attrs

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        handler.addQuickElement('guid', item['link'], attrs={'isPermaLink': 'true'})
        
        if 'pubdate' not in item:
            item['pubdate'] = datetime.now(pytz.utc)

def ensure_directories():
    """Create necessary directories if they don't exist."""
    directories = ['feeds', 'history', 'config']
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def get_feed_path(filename):
    """Get the full path for a feed file."""
    return os.path.join('feeds', filename)

def get_history_path(filename):
    """Get the full path for a history file."""
    return os.path.join('history', filename)

def get_config_path(filename):
    """Get the full path for a config file."""
    return os.path.join('config', filename)

def get_feed_url(filename):
    """Get the full GitHub Pages URL for a feed file."""
    return f"{GITHUB_PAGES_BASE_URL}/feeds/{filename}"

def generate_feed(source_name, url, article):
    """Generate RSS feed for an article."""
    feed_filename = f"{source_name.lower().replace(' ', '_')}_feed.xml"
    feed_url = get_feed_url(feed_filename)

    feed = CustomRssFeed(
        title=f"{source_name}",
        link=url,
        description=f"Últimos artigos de {source_name}",
        language="pt-br",
        feed_url=feed_url,
        feed_guid=url,
        ttl="60"
    )

    feed.add_item(
        title=article['title'],
        link=article['link'],
        description=article['description'],
        author_name=article['author'],
        author_email="",
        pubdate=article['pubdate'],
        unique_id=article['link'],
        updateddate=article['pubdate'],
    )

    return feed

def generate_grouped_feed(group_name, articles):
    """Generate RSS feed for a group of articles from multiple authors.

    Args:
        group_name: Name of the group (e.g., 'estadao', 'oglobo')
        articles: List of dicts with keys: author_name, article (with title, link, etc.)

    Returns:
        CustomRssFeed object
    """
    # Create display name for the group
    group_display_names = {
        'estadao': 'Estadão',
        'oglobo': 'O Globo',
        'valor': 'Valor Econômico',
        'folha': 'Folha de S.Paulo',
        'linkedin': 'LinkedIn Newsletters',
        'poder360': 'Poder360'
    }

    display_name = group_display_names.get(group_name, group_name.title())
    feed_filename = f"{group_name}_feed.xml"
    feed_url = get_feed_url(feed_filename)

    # Use the first article's link as the main link (or a generic URL)
    main_link = articles[0]['article']['link'] if articles else "https://paulofeh.github.io/rss-de-valor"

    feed = CustomRssFeed(
        title=f"{display_name} - Colunistas",
        link=main_link,
        description=f"Últimos artigos de colunistas do {display_name}",
        language="pt-br",
        feed_url=feed_url,
        feed_guid=feed_url,
        ttl="60"
    )

    # Sort articles by date (most recent first)
    # Use current time as default for articles without date
    from datetime import datetime
    default_date = datetime.now(pytz.UTC)

    sorted_articles = sorted(
        articles,
        key=lambda x: x['article']['pubdate'] if x['article']['pubdate'] is not None else default_date,
        reverse=True
    )

    # Add each article to the feed with author name in the title
    for item in sorted_articles:
        author_name = item['author_name']
        article = item['article']

        # Format title as "Author: Article Title"
        title_with_author = f"{author_name}: {article['title']}"

        # Use current time if pubdate is None
        pubdate = article['pubdate'] if article['pubdate'] is not None else default_date

        feed.add_item(
            title=title_with_author,
            link=article['link'],
            description=article['description'],
            author_name=author_name,
            author_email="",
            pubdate=pubdate,
            unique_id=article['link'],
            updateddate=pubdate,
        )

    return feed

def save_feed(feed, filename):
    """Save feed to the feeds directory."""
    full_path = get_feed_path(filename)
    with open(full_path, 'w', encoding='utf-8') as f:
        feed.write(f, 'utf-8')

def load_history(filename):
    """Load history from the history directory."""
    full_path = get_history_path(filename)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_history(filename, data):
    """Save history to the history directory."""
    full_path = get_history_path(filename)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def load_sources_config(filename='sources_config.json'):
    """Load sources configuration from the config directory."""
    full_path = get_config_path(filename)
    with open(full_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config['sources']

def generate_opml(sources):
    """Generate OPML file from sources configuration with both grouped and individual feeds."""
    # Create root OPML element
    opml = ET.Element('opml', version="2.0")

    # Create head section
    head = ET.SubElement(opml, 'head')
    title = ET.SubElement(head, 'title')
    title.text = 'RSS de Colunistas'
    date_created = ET.SubElement(head, 'dateCreated')
    date_created.text = datetime.now(pytz.UTC).strftime('%a, %d %b %Y %H:%M:%S GMT')
    owner_name = ET.SubElement(head, 'ownerName')
    owner_name.text = 'RSS Scraper'

    # Create body section
    body = ET.SubElement(opml, 'body')

    # Display names for groups
    group_display_names = {
        'estadao': 'Estadão',
        'oglobo': 'O Globo',
        'valor': 'Valor Econômico',
        'folha': 'Folha de S.Paulo',
        'linkedin': 'LinkedIn Newsletters',
        'poder360': 'Poder360'
    }

    # ============================================
    # SECTION 1: Grouped Feeds
    # ============================================
    grouped_outline = ET.SubElement(body, 'outline', text="📚 Feeds Agrupados por Veículo", title="📚 Feeds Agrupados por Veículo")

    # Get unique groups from sources
    groups_info = {}
    for source in sources:
        group = source.get('group', '').strip()
        if group:
            if group not in groups_info:
                groups_info[group] = []
            groups_info[group].append(source['name'])

    # Create feed entries for each group
    for group in sorted(groups_info.keys()):
        display_name = group_display_names.get(group, group.title())
        feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{group}_feed.xml"

        # Count of columnists in this group
        count = len(groups_info[group])
        description = f"{display_name} - {count} colunistas"

        ET.SubElement(grouped_outline, 'outline',
                     type="rss",
                     text=description,
                     title=description,
                     xmlUrl=feed_url)

    # ============================================
    # SECTION 2: Individual Feeds
    # ============================================
    individual_outline = ET.SubElement(body, 'outline', text="📄 Feeds Individuais", title="📄 Feeds Individuais")

    # Group sources by publisher for better organization
    sources_by_group = {}
    ungrouped_sources = []

    for source in sources:
        group = source.get('group', '').strip()
        if group:
            if group not in sources_by_group:
                sources_by_group[group] = []
            sources_by_group[group].append(source)
        else:
            ungrouped_sources.append(source)

    # Add grouped sources
    for group in sorted(sources_by_group.keys()):
        display_name = group_display_names.get(group, group.title())
        group_outline = ET.SubElement(individual_outline, 'outline',
                                      text=display_name,
                                      title=display_name)

        for source in sorted(sources_by_group[group], key=lambda x: x['name']):
            feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{source['feed_file']}"
            ET.SubElement(group_outline, 'outline',
                        type="rss",
                        text=source['name'],
                        title=source['name'],
                        xmlUrl=feed_url)

    # Add ungrouped sources (if any)
    if ungrouped_sources:
        other_outline = ET.SubElement(individual_outline, 'outline',
                                      text="Outros",
                                      title="Outros")

        for source in sorted(ungrouped_sources, key=lambda x: x['name']):
            feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{source['feed_file']}"
            ET.SubElement(other_outline, 'outline',
                        type="rss",
                        text=source['name'],
                        title=source['name'],
                        xmlUrl=feed_url)

    return opml

def save_opml(opml_element, filename='feeds.opml'):
    """Save OPML file with proper formatting."""
    # Create a new ElementTree
    tree = ET.ElementTree(opml_element)
    
    # Add XML declaration
    tree.write(filename, encoding='utf-8', xml_declaration=True)
    
    # Read the file content
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Add proper indentation
    content = format_opml(content)
    
    # Write back the formatted content
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

def format_opml(content):
    """Format OPML content with proper indentation."""
    # Parse the content
    root = ET.XML(content)
    
    # Function to recursively indent elements
    def indent(elem, level=0):
        i = "\n" + level*"    "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "    "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for subelem in elem:
                indent(subelem, level+1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i
    
    # Apply indentation
    indent(root)

    # Convert back to string
    return ET.tostring(root, encoding='unicode', method='xml')

def generate_html_index(sources):
    """Generate an HTML index page showing all feeds organized by group."""
    from datetime import datetime

    # Group sources by vehicle
    group_display_names = {
        'estadao': 'Estadão',
        'oglobo': 'O Globo',
        'valor': 'Valor Econômico',
        'folha': 'Folha de S.Paulo',
        'linkedin': 'LinkedIn Newsletters',
        'poder360': 'Poder360'
    }

    sources_by_group = {}
    ungrouped_sources = []

    for source in sources:
        group = source.get('group', '').strip()
        if group:
            if group not in sources_by_group:
                sources_by_group[group] = []
            sources_by_group[group].append(source)
        else:
            ungrouped_sources.append(source)

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSS de Colunistas - Feeds Disponíveis</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}

        h1 {{
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 2.5em;
        }}

        .subtitle {{
            color: #7f8c8d;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}

        .stats {{
            background: #ecf0f1;
            padding: 20px;
            border-radius: 6px;
            margin-bottom: 40px;
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
        }}

        .stat-item {{
            flex: 1;
            min-width: 150px;
        }}

        .stat-number {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}

        .stat-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}

        h2 {{
            color: #34495e;
            margin-top: 40px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #3498db;
            font-size: 1.8em;
        }}

        .section-intro {{
            color: #7f8c8d;
            margin-bottom: 25px;
            font-style: italic;
        }}

        .group-card {{
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 25px;
            margin-bottom: 25px;
            transition: box-shadow 0.3s ease;
        }}

        .group-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}

        .group-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #ecf0f1;
        }}

        .group-title {{
            font-size: 1.5em;
            color: #2c3e50;
            font-weight: 600;
        }}

        .group-count {{
            background: #3498db;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: 500;
        }}

        .feed-link {{
            display: inline-block;
            background: #27ae60;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            margin-bottom: 15px;
            transition: background 0.3s ease;
            font-weight: 500;
        }}

        .feed-link:hover {{
            background: #229954;
        }}

        .columnists-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }}

        .columnist-item {{
            background: #f8f9fa;
            padding: 12px 15px;
            border-radius: 5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s ease;
        }}

        .columnist-item:hover {{
            background: #e9ecef;
        }}

        .columnist-name {{
            color: #2c3e50;
            font-weight: 500;
        }}

        .individual-link {{
            color: #3498db;
            text-decoration: none;
            font-size: 0.9em;
            padding: 4px 8px;
            border-radius: 3px;
            transition: background 0.2s ease;
        }}

        .individual-link:hover {{
            background: #ebf5fb;
        }}

        .footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }}

        .opml-section {{
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }}

        .opml-section h3 {{
            color: #856404;
            margin-bottom: 10px;
        }}

        .opml-link {{
            display: inline-block;
            background: #ffc107;
            color: #856404;
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 600;
            margin-top: 10px;
            transition: background 0.3s ease;
        }}

        .opml-link:hover {{
            background: #ffca2c;
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 20px;
            }}

            h1 {{
                font-size: 2em;
            }}

            .stats {{
                flex-direction: column;
            }}

            .columnists-list {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📰 RSS de Colunistas</h1>
        <p class="subtitle">Feeds RSS de colunistas brasileiros, atualizados automaticamente a cada 6 horas</p>

        <div class="stats">
            <div class="stat-item">
                <div class="stat-number">{len(sources)}</div>
                <div class="stat-label">Colunistas monitorados</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">{len(sources_by_group)}</div>
                <div class="stat-label">Feeds agrupados</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">{sum(1 for s in sources if s.get('scraper') == 'ExistingRssScraper')}</div>
                <div class="stat-label">Feeds RSS oficiais</div>
            </div>
        </div>

        <div class="opml-section">
            <h3>💡 Assinar todos os feeds de uma vez</h3>
            <p>Use o arquivo OPML para importar todos os feeds no seu leitor RSS favorito (Feedly, Inoreader, NetNewsWire, etc.)</p>
            <a href="{GITHUB_PAGES_BASE_URL}/feeds/feeds.opml" class="opml-link">📥 Baixar OPML</a>
        </div>

        <h2>📚 Feeds Agrupados por Veículo</h2>
        <p class="section-intro">Receba artigos de todos os colunistas de um veículo em um único feed</p>
"""

    # Add grouped feeds
    for group in sorted(sources_by_group.keys()):
        display_name = group_display_names.get(group, group.title())
        columnists = sorted(sources_by_group[group], key=lambda x: x['name'])
        feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{group}_feed.xml"

        html += f"""
        <div class="group-card">
            <div class="group-header">
                <div class="group-title">{display_name}</div>
                <div class="group-count">{len(columnists)} colunistas</div>
            </div>
            <a href="{feed_url}" class="feed-link">🔗 Assinar Feed Agrupado</a>
            <div class="columnists-list">
"""

        for source in columnists:
            individual_feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{source['feed_file']}"
            html += f"""
                <div class="columnist-item">
                    <span class="columnist-name">{source['name']}</span>
                    <a href="{individual_feed_url}" class="individual-link">Feed →</a>
                </div>
"""

        html += """
            </div>
        </div>
"""

    # Add ungrouped sources if any
    if ungrouped_sources:
        html += """
        <h2>📄 Feeds Individuais Sem Grupo</h2>
        <p class="section-intro">Colunistas com feeds individuais que não estão em grupos</p>
        <div class="group-card">
            <div class="columnists-list">
"""
        for source in sorted(ungrouped_sources, key=lambda x: x['name']):
            individual_feed_url = f"{GITHUB_PAGES_BASE_URL}/feeds/{source['feed_file']}"
            html += f"""
                <div class="columnist-item">
                    <span class="columnist-name">{source['name']}</span>
                    <a href="{individual_feed_url}" class="individual-link">Feed →</a>
                </div>
"""
        html += """
            </div>
        </div>
"""

    # Footer
    html += f"""
        <div class="footer">
            <p>Última atualização: {datetime.now(pytz.UTC).strftime('%d/%m/%Y %H:%M')} UTC</p>
            <p>Gerado automaticamente via <a href="https://github.com/paulofeh/rss-de-valor" style="color: #3498db;">GitHub Actions</a></p>
        </div>
    </div>
</body>
</html>
"""

    return html

def save_html_index(html, filename='feeds/index.html'):
    """Save HTML index to file."""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)