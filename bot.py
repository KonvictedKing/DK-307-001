import os
import json
import time
import urllib.parse
from datetime import datetime
from io import BytesIO

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont
from groq import Groq

PAGE_ID = os.environ.get("FB_PAGE_ID")
IG_USER_ID = os.environ.get("IG_USER_ID")
ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

RSS_FEEDS = [
    # --- Local & National News ---
    {"name": "Prothom Alo", "url": "https://www.prothomalo.com/feed"},
    {"name": "The Daily Star", "url": "https://www.thedailystar.net/frontpage/rss.xml"},
    {"name": "bdnews24.com", "url": "https://bangla.bdnews24.com/rss.xml"},
    {"name": "Banglanews24", "url": "https://www.banglanews24.com/rss/rss.xml"},
    {"name": "Dhaka Tribune", "url": "https://www.dhakatribune.com/feed"},
    {"name": "The Business Standard", "url": "https://www.tbsnews.net/rss.xml"},

    # --- International News ---
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "BBC Bangla", "url": "https://feeds.bbci.co.uk/bengali/rss.xml"},
    {"name": "CNN", "url": "http://rss.cnn.com/rss/edition.rss"},
    {"name": "The New York Times", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "AP News", "url": "https://feedx.net/rss/apnews.xml"},
    {"name": "Reuters", "url": "https://feedx.net/rss/reuters.xml"},

    # --- Sports News ---
    {"name": "ESPN", "url": "https://www.espn.com/espn/rss/news"},
    {"name": "The Athletic", "url": "https://theathletic.com/rss-feed/"},
    {"name": "ESPNcricinfo", "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"},
    {"name": "Cricbuzz", "url": "https://www.cricbuzz.com/api/cricket-news/rss"},
    {"name": "Yahoo! Sports", "url": "https://sports.yahoo.com/rss/"},
    {"name": "Bleacher Report", "url": "https://bleacherreport.com/articles/feed"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040"}
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
        json.dump(urls[-250:], f, indent=2)

def get_valid_chat_models():
    ignored_keywords = ["guard", "whisper", "embed", "tts", "safeguard"]
    valid_models = []
    try:
        models = groq_client.models.list()
        for m in models.data:
            model_id = m.id.lower()
            if not any(k in model_id for k in ignored_keywords):
                valid_models.append(m.id)
    except Exception as e:
        print(f"Model list error: {e}")
    return valid_models

def clean_title_or_translate(title):
    models = get_valid_chat_models()
    prompt = f"Extract a clean, powerful, short news headline (max 12-14 words). Remove any source mentions. If in English, keep it in punchy English or clean Bangla as fits best. Return ONLY the headline text without quotes:\n\n{title}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60
            )
            headline = res.choices[0].message.content.strip().replace('"', '')
            if len(headline) > 5:
                return headline
        except:
            continue
    return title[:90]

def extract_image_url(entry):
    # Check media_content or enclosures
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url')
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        return entry.enclosures[0].get('href')
    # Fallback to Pollinations AI
    safe_prompt = urllib.parse.quote(entry.title[:80])
    return f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=720&nologo=true"

def wrap_text(text, font, max_width, draw):
    lines = []
    words = text.split()
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_dacca_card(image_url, headline, source_name):
    # Standard Facebook Card Size (1080 x 1350 vertical/portrait)
    width, height = 1080, 1350
    card = Image.new("RGB", (width, height), color="#000000")
    draw = ImageDraw.Draw(card)

    try:
        font_brand = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_date = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_headline = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
        font_footer = ImageFont.truetype("DejaVuSans.ttf", 26)
    except:
        font_brand = font_date = font_headline = font_footer = ImageFont.load_default()

    # 1. Top Header Bar
    draw.text((50, 45), "DACCAখবর।", fill="#ffffff", font=font_brand)
    today_str = datetime.utcnow().strftime("%d %b %Y").upper()
    date_bbox = draw.textbbox((0, 0), today_str, font=font_date)
    draw.text((width - 50 - (date_bbox[2] - date_bbox[0]), 48), today_str, fill="#d1d5db", font=font_date)

    # 2. Headline
    wrapped_lines = wrap_text(headline, font_headline, width - 100, draw)
    text_y = 130
    for line in wrapped_lines[:4]:
        draw.text((50, text_y), line, fill="#ffffff", font=font_headline)
        text_y += 70

    # 3. Middle News Image
    image_top = max(text_y + 35, 380)
    image_height = 800
    try:
        resp = requests.get(image_url, timeout=15)
        raw_img = Image.open(BytesIO(resp.content)).convert("RGB")
        # Resize preserving aspect ratio and crop to box
        target_ratio = (width - 100) / image_height
        raw_ratio = raw_img.width / raw_img.height
        if raw_ratio > target_ratio:
            new_width = int(raw_img.height * target_ratio)
            left = (raw_img.width - new_width) // 2
            raw_img = raw_img.crop((left, 0, left + new_width, raw_img.height))
        else:
            new_height = int(raw_img.width / target_ratio)
            top = (raw_img.height - new_height) // 2
            raw_img = raw_img.crop((0, top, raw_img.width, top + new_height))
        
        resized = raw_img.resize((width - 100, image_height))
        card.paste(resized, (50, image_top))
    except Exception as e:
        print(f"Failed to load image: {e}")

    # 4. Footer info
    footer_y = image_top + image_height + 25
    draw.text((50, footer_y), f"VIA - {source_name}", fill="#e5e7eb", font=font_footer)
    draw.text((50, footer_y + 35), "✨ AI-generated content", fill="#9ca3af", font=font_footer)

    # 5. DACCA Watermark Logo on bottom right
    if os.path.exists("logo.png"):
        try:
            logo = Image.open("logo.png").convert("RGBA")
            logo.thumbnail((120, 80))
            card.paste(logo, (width - 170, footer_y - 10), logo)
        except:
            pass
    else:
        draw.text((width - 180, footer_y), "[DACCA]", fill="#ffffff", font=font_brand)

    output_path = "final_card.jpg"
    card.save(output_path, "JPEG", quality=95)
    return output_path

def upload_to_tmp(image_path):
    # Free temporary image hosting for Graph API URL delivery
    with open(image_path, "rb") as f:
        res = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}).json()
        raw_url = res["data"]["url"]
        return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

def post_to_facebook(public_url, caption):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    payload = {"url": public_url, "caption": caption, "access_token": ACCESS_TOKEN}
    res = requests.post(url, data=payload)
    return res.json()

def post_to_instagram(public_url, caption):
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {"image_url": public_url, "caption": caption, "access_token": ACCESS_TOKEN}
    res = requests.post(create_url, data=payload).json()
    creation_id = res.get("id")
    if not creation_id:
        return
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN})

def main():
    posted = load_posted_urls()
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                if entry.link not in posted:
                    print(f"Processing: {entry.title}")
                    headline = clean_title_or_translate(entry.title)
                    img_url = extract_image_url(entry)
                    
                    # Create the exact card layout
                    card_path = create_dacca_card(img_url, headline, feed["name"])
                    public_card_url = upload_to_tmp(card_path)

                    post_caption = f"Details in Comment...\n\nSource: {entry.link}"
                    print("Posting banner card to Facebook...")
                    post_to_facebook(public_card_url, post_caption)

                    if IG_USER_ID:
                        print("Posting banner card to Instagram...")
                        post_to_instagram(public_card_url, f"{headline}\n\nVia {feed['name']}")

                    posted.append(entry.link)
                    save_posted_urls(posted)
                    return
        except Exception as err:
            print(f"Skipping {feed['name']}: {err}")
            continue

if __name__ == "__main__":
    main()
    words = text.split()
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_dacca_card(image_url, headline, source_name):
    # Standard Facebook Card Size (1080 x 1350 vertical/portrait)
    width, height = 1080, 1350
    card = Image.new("RGB", (width, height), color="#000000")
    draw = ImageDraw.Draw(card)

    try:
        font_brand = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_date = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_headline = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
        font_footer = ImageFont.truetype("DejaVuSans.ttf", 26)
    except:
        font_brand = font_date = font_headline = font_footer = ImageFont.load_default()

    # 1. Top Header Bar
    draw.text((50, 45), "DACCAখবর।", fill="#ffffff", font=font_brand)
    today_str = datetime.utcnow().strftime("%d %b %Y").upper()
    date_bbox = draw.textbbox((0, 0), today_str, font=font_date)
    draw.text((width - 50 - (date_bbox[2] - date_bbox[0]), 48), today_str, fill="#d1d5db", font=font_date)

    # 2. Headline
    wrapped_lines = wrap_text(headline, font_headline, width - 100, draw)
    text_y = 130
    for line in wrapped_lines[:4]:
        draw.text((50, text_y), line, fill="#ffffff", font=font_headline)
        text_y += 70

    # 3. Middle News Image
    image_top = max(text_y + 35, 380)
    image_height = 800
    try:
        resp = requests.get(image_url, timeout=15)
        raw_img = Image.open(BytesIO(resp.content)).convert("RGB")
        # Resize preserving aspect ratio and crop to box
        target_ratio = (width - 100) / image_height
        raw_ratio = raw_img.width / raw_img.height
        if raw_ratio > target_ratio:
            new_width = int(raw_img.height * target_ratio)
            left = (raw_img.width - new_width) // 2
            raw_img = raw_img.crop((left, 0, left + new_width, raw_img.height))
        else:
            new_height = int(raw_img.width / target_ratio)
            top = (raw_img.height - new_height) // 2
            raw_img = raw_img.crop((0, top, raw_img.width, top + new_height))
        
        resized = raw_img.resize((width - 100, image_height))
        card.paste(resized, (50, image_top))
    except Exception as e:
        print(f"Failed to load image: {e}")

    # 4. Footer info
    footer_y = image_top + image_height + 25
    draw.text((50, footer_y), f"VIA - {source_name}", fill="#e5e7eb", font=font_footer)
    draw.text((50, footer_y + 35), "✨ AI-generated content", fill="#9ca3af", font=font_footer)

    # 5. DACCA Watermark Logo on bottom right
    if os.path.exists("logo.png"):
        try:
            logo = Image.open("logo.png").convert("RGBA")
            logo.thumbnail((120, 80))
            card.paste(logo, (width - 170, footer_y - 10), logo)
        except:
            pass
    else:
        draw.text((width - 180, footer_y), "[DACCA]", fill="#ffffff", font=font_brand)

    output_path = "final_card.jpg"
    card.save(output_path, "JPEG", quality=95)
    return output_path

def upload_to_tmp(image_path):
    # Free temporary image hosting for Graph API URL delivery
    with open(image_path, "rb") as f:
        res = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}).json()
        raw_url = res["data"]["url"]
        return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

def post_to_facebook(public_url, caption):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    payload = {"url": public_url, "caption": caption, "access_token": ACCESS_TOKEN}
    res = requests.post(url, data=payload)
    return res.json()

def post_to_instagram(public_url, caption):
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {"image_url": public_url, "caption": caption, "access_token": ACCESS_TOKEN}
    res = requests.post(create_url, data=payload).json()
    creation_id = res.get("id")
    if not creation_id:
        return
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN})

def main():
    posted = load_posted_urls()
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                if entry.link not in posted:
                    print(f"Processing: {entry.title}")
                    headline = clean_title_or_translate(entry.title)
                    img_url = extract_image_url(entry)
                    
                    # Create the exact card layout
                    card_path = create_dacca_card(img_url, headline, feed["name"])
                    public_card_url = upload_to_tmp(card_path)

                    post_caption = f"Details in Comment...\n\nSource: {entry.link}"
                    print("Posting banner card to Facebook...")
                    post_to_facebook(public_card_url, post_caption)

                    if IG_USER_ID:
                        print("Posting banner card to Instagram...")
                        post_to_instagram(public_card_url, f"{headline}\n\nVia {feed['name']}")

                    posted.append(entry.link)
                    save_posted_urls(posted)
                    return
        except Exception as err:
            print(f"Skipping {feed['name']}: {err}")
            continue

if __name__ == "__main__":
    main()
