import requests
from bs4 import BeautifulSoup
import datetime
import pytz
from feedgenerator import Rss201rev2Feed
import os
import json

# Configurações dos colunistas
COLUMNISTS = [
    {
        "name": "Guilherme Ravache",
        "url": "https://valor.globo.com/autores/guilherme-ravache/",
        "feed_file": "guilherme_ravache_feed.xml",
        "history_file": "guilherme_ravache_history.json"
    },
    {
        "name": "Maria Cristina Fernandes",
        "url": "https://valor.globo.com/opiniao/maria-cristina-fernandes/",
        "feed_file": "maria_cristina_fernandes_feed.xml",
        "history_file": "maria_cristina_fernandes_history.json"
    },
    # Adicione outros colunistas aqui seguindo o mesmo formato
]

def get_latest_article(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    article = soup.select_one('div.bastian-feed-item')
    if article:
        title = article.select_one('h2.feed-post-link').text.strip()
        link = article.select_one('a')['href']
        date_str = article.select_one('span.feed-post-datetime').text.strip()
        author = article.select_one('span.feed-post-metadata-section').text.strip()
        description_element = article.select_one('p.feed-post-body-resumo')
        description = description_element.text.strip() if description_element else ""
        
        try:
            date = parse_date(date_str)
        except Exception as e:
            print(f"Erro ao analisar a data '{date_str}': {e}")
            date = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        
        return {
            'title': title,
            'link': link,
            'pubdate': date,
            'author': author,
            'description': description,
        }
    return None

def parse_date(date_str):
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

def generate_feed(columnist, article):
    feed = Rss201rev2Feed(
        title=f"{columnist['name']} - Valor Econômico",
        link=columnist['url'],
        description=f"Artigos mais recentes de {columnist['name']} no Valor Econômico",
        language="pt-BR",
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

def main():
    for columnist in COLUMNISTS:
        latest_article = get_latest_article(columnist['url'])
        if latest_article:
            history = load_history(columnist['history_file'])
            
            if latest_article['link'] != history.get('last_article_link'):
                feed = generate_feed(columnist, latest_article)
                save_feed(feed, columnist['feed_file'])
                print(f"Feed RSS para {columnist['name']} gerado com sucesso! Salvo como '{columnist['feed_file']}'")
                
                history['last_article_link'] = latest_article['link']
                save_history(columnist['history_file'], history)
            else:
                print(f"Nenhum novo artigo para {columnist['name']}. Feed não atualizado.")
        else:
            print(f"Não foi possível obter o último artigo para {columnist['name']}.")

if __name__ == "__main__":
    main()