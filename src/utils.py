import os
import json
from feedgenerator import Rss201rev2Feed

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
    feed = Rss201rev2Feed(
        title=f"{source_name}",
        link=url,
        description=f"Últimos artigos de {source_name}",
        language="pt-br",
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