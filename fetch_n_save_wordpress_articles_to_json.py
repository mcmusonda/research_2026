import requests
import json
import os
import certifi
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Define constant variables
BASE_URL = "https://znbc.co.zm/index.php?rest_route=/wp/v2/posts"

def fetch_all_articles(base_url, per_page=100, max_pages=5):
  all_articles = []

  for page in range(1, max_pages + 1):
    params = {
        'per_page': per_page,
        'page': page
    }

    try:
      response = requests.get(
          base_url,
          params=params,
          verify=False,
          timeout=30
      )
      if response.status_code == 400:
          print(f"No more valid pages. Stopped at page {page}.")
          break
      response.raise_for_status()
      
      posts = response.json()

      if not posts:
          print('No more posts to found.')
          break

      for post in posts:
          article = {
              'id': post['id'],
              'date': post['date'],
              'date_gmt': post['date_gmt'],
              'guid': post['guid']['rendered'],
              'modified': post['modified'],
              'modified_gmt': post['modified_gmt'],
              'slug': post['slug'],
              'status': post['status'],
              'type': post['type'],
              'link': post['link'],
              'title': post['title']['rendered'],
              'content': post['content']['rendered'],
              'excerpt': post['excerpt']['rendered'],
              'author': post['author'],
              'featured_media': post['featured_media'],
              'comment_status': post['comment_status'],
              'ping_status': post['ping_status'],
              'sticky': post['sticky'],
              'template': post['template'],
              'format': post['format'],
              'meta': post['meta'],
              'categories': post['categories'],
              'tags': post['tags'],
              'links': post['_links']
          }
          all_articles.append(article)

    except requests.exceptions.RequestException as e:
      print(f"An error occurred: {e}")
      break

  return all_articles

def save_to_json(data, filename='data/znbc.json'):
    """Append articles to the JSON file"""
    # Check if the file exists
    if os.path.exists(filename):
        # If the file exists, open it and load the existing data
        with open(filename, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                # If the file is empty or malformed, start with an empty list
                existing_data = []
    else:
        # If the file does not exist, start with an empty list
        existing_data = []

    # Append the new data to the existing data
    existing_data.extend(data)

    # Write the updated data back to the file
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=4)

    print(f"Appended {len(data)} articles to {filename}")

# Run the process
articles = fetch_all_articles(BASE_URL, per_page=10, max_pages=1000)
save_to_json(articles)

