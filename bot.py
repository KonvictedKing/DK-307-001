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
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/bengali/rss.xml",
    "https://www.thedailystar.net/frontpage/rss.xml",
    "https://www.dhakatribune.com/feed",
    "https://bangla.bdnews24.com/rss.xml",
    "https://www.prothomalo.com/feed",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "http://rss.cnn.com/rss/edition.rss"
]

groq_client = Groq(api_key=GROQ_API_KEY)

def get_active_groq_model():
    preferred_models = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "llama3-70b-8192"
    ]
    try:
        available = [m.id for m in groq_client.models.list().data if "guard" not in m.id.lower()]
        for pref in preferred_models:
            if pref in available:
                print(f"Using preferred active model: {pref}")
                return pref
        return available[0]
    except Exception as e:
        print(f"Error listing models: {e}")
        return "llama3-8b-8192"

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
        json.dump(urls[-100:], f, indent=2)

def generate_summary(text):
    active_model = get_active_groq_model()
    prompt = f"Summarize this news into a crisp, engaging 2-3 sentence Facebook post. Write in Bangla with relevant emojis and hashtags:\n\n{text}"
    response = groq_client.chat.completions.create(
        model=active_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    return response.choices[0].message.content.strip()

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
        parsed = feedparser.parse(feed)
        for entry in parsed.entries:
            if entry.link not in posted:
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

if __name__ == "__main__":
    main()
