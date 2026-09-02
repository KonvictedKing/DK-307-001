import os
import json
import time
import urllib.parse
import feedparser
import requests
from groq import Groq

PAGE_ID = os.environ.get("FB_PAGE_ID")
IG_USER_ID = os.environ.get("IG_USER_ID")
ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

RSS_FEEDS = [
    # --- Local & National News ---
    "https://www.prothomalo.com/feed",
    "https://www.thedailystar.net/frontpage/rss.xml",
    "https://bangla.bdnews24.com/rss.xml",
    "https://www.banglanews24.com/rss/rss.xml",
    "https://www.dhakatribune.com/feed",
    "https://www.tbsnews.net/rss.xml",

    # --- International News ---
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/bengali/rss.xml",
    "http://rss.cnn.com/rss/edition.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://www.theguardian.com/world/rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bloomberg.com/politics/news.rss",
    "https://feedx.net/rss/apnews.xml",
    "https://feedx.net/rss/reuters.xml",

    # --- Sports News ---
    "https://www.espn.com/espn/rss/news",
    "https://theathletic.com/rss-feed/",
    "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
    "https://www.cricbuzz.com/api/cricket-news/rss",
    "https://sports.yahoo.com/rss/",
    "https://bleacherreport.com/articles/feed",
    "https://www.skysports.com/rss/12040"
]

groq_client = Groq(api_key=GROQ_API_KEY)

def load_posted_urls():
    if os.path.exists("posted_urls.json"):
        with open("posted_urls.json", "r") as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_posted_urls(urls):
    with open("posted_urls.json", "w") as f:
        json.dump(urls[-200:], f, indent=2)

def get_valid_chat_models():
    ignored_keywords = ["guard", "whisper", "embed", "tts", "safeguard"]
    valid_models = []
    try:
        models = groq_client.models.list()
        for m in models.data:
            model_id = m.id.lower()
            if not any(k in model_id for k in ignored_keywords):
                valid_models.append(m.id)
        print(f"Available chat models: {valid_models}")
    except Exception as e:
        print(f"Error fetching model list: {e}")
    return valid_models

def generate_summary(text):
    candidate_models = get_valid_chat_models()
    prompt = f"Summarize this news into a crisp, engaging 2-3 sentence post. Write in Bangla with appropriate emojis and relevant hashtags:\n\n{text}"
    
    for model_name in candidate_models:
        try:
            print(f"Trying active model: {model_name}...")
            response = groq_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250
            )
            content = response.choices[0].message.content.strip()
            # Guard against unexpected float/score strings
            if len(content) > 15 and not content.replace(".", "").isdigit():
                return content
        except Exception as err:
            print(f"Skipping {model_name}: {err}")
            continue
            
    raise Exception("Could not generate summary with any available Groq model.")

def post_to_facebook(image_url, message):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    payload = {"url": image_url, "caption": message, "access_token": ACCESS_TOKEN}
    res = requests.post(url, data=payload)
    return res.json()

def post_to_instagram(image_url, caption):
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {"image_url": image_url, "caption": caption, "access_token": ACCESS_TOKEN}
    res = requests.post(create_url, data=payload).json()
    
    creation_id = res.get("id")
    if not creation_id:
        print(f"IG container creation failed: {res}")
        return
    
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
    print("Instagram posted:", pub_res)

def main():
    posted = load_posted_urls()
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed)
            for entry in parsed.entries:
                if entry.link not in posted:
                    print(f"Found new article: {entry.title}")
                    news_text = f"{entry.title}\n{entry.get('summary', '')}"
                    summary = generate_summary(news_text)
                    
                    safe_prompt = urllib.parse.quote(entry.title[:80])
                    image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1080&nologo=true"
                    
                    print("Posting to Facebook...")
                    post_to_facebook(image_url, f"{summary}\n\nSource: {entry.link}")
                    
                    if IG_USER_ID:
                        print("Posting to Instagram...")
                        post_to_instagram(image_url, summary)
                    
                    posted.append(entry.link)
                    save_posted_urls(posted)
                    return
        except Exception as e:
            print(f"Error reading feed {feed}: {e}")
            continue

if __name__ == "__main__":
    main()
