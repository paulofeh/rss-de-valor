import os
import json
from feedgenerator import Rss201rev2Feed
from datetime import datetime
import pytz

class CustomRssFeed(Rss201rev2Feed):
    def root_attributes(self):
        attrs = super().root_attributes()
        attrs['xmlns:atom'] = 'http://www.w3.org/2005/Atom'
        return attrs

    def add_item_elements(self, handler, item):
        super().add_item_elements(handler, item)
        
        # Adiciona o guid (mesmo que o link)
        handler.addQuickElement('guid', item['link'], attrs={'isPermaLink': 'true'})
        
        # Garante que o item tenha uma data de publicação
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

def generate_feed(source_name, url, article):
    """Generate RSS feed for an article."""
    feed = CustomRssFeed(
        title=f"{source_name}",
        link=url,
        description=f"Últimos artigos de {source_name}",
        language="pt-br",
        feed_url=f"https://raw.githubusercontent.com/paulofeh/rss-de-valor/main/feeds/{source_name.lower().replace(' ', '_')}_feed.xml",
        feed_guid=url,
        ttl="60"
    )

    feed.add_item(
        title=article['title'],
        link=article['link'],
        description=article['description'],
        author_name=article['author'],
        author_email="",  # Campo vazio mas presente
        pubdate=article['pubdate'],
        unique_id=article['link'],  # Garante um ID único
        updateddate=article['pubdate'],  # Data de atualização
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