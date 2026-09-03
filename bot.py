import os
import re
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

NATIONAL_FEEDS = [
    {"name": "Prothom Alo", "url": "https://www.prothomalo.com/feed"},
    {"name": "The Daily Star", "url": "https://www.thedailystar.net/frontpage/rss.xml"},
    {"name": "bdnews24.com", "url": "https://bangla.bdnews24.com/rss.xml"},
    {"name": "Banglanews24", "url": "https://www.banglanews24.com/rss/rss.xml"},
    {"name": "Dhaka Tribune", "url": "https://www.dhakatribune.com/feed"},
    {"name": "The Business Standard", "url": "https://www.tbsnews.net/rss.xml"}
]

INTERNATIONAL_FEEDS = [
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "BBC Bangla", "url": "https://feeds.bbci.co.uk/bengali/rss.xml"},
    {"name": "CNN", "url": "http://rss.cnn.com/rss/edition.rss"},
    {"name": "The New York Times", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "AP News", "url": "https://feedx.net/rss/apnews.xml"},
    {"name": "Reuters", "url": "https://feedx.net/rss/reuters.xml"}
]

SPORTS_FEEDS = [
    {"name": "ESPN", "url": "https://www.espn.com/espn/rss/news"},
    {"name": "The Athletic", "url": "https://theathletic.com/rss-feed/"},
    {"name": "ESPNcricinfo", "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"},
    {"name": "Cricbuzz", "url": "https://www.cricbuzz.com/api/cricket-news/rss"},
    {"name": "Yahoo! Sports", "url": "https://sports.yahoo.com/rss/"},
    {"name": "Bleacher Report", "url": "https://bleacherreport.com/articles/feed"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040"}
]

groq_client = Groq(api_key=GROQ_API_KEY)

def load_state():
    state = {"posted_urls": [], "indices": {"national": 0, "international": 0, "sports": 0}}
    if os.path.exists("posted_urls.json"):
        try:
            with open("posted_urls.json", "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    state["posted_urls"] = data
                elif isinstance(data, dict):
                    state["posted_urls"] = data.get("posted_urls", [])
                    state["indices"] = data.get("indices", state["indices"])
        except Exception as e:
            print(f"Error loading state: {e}")
    return state

def save_state(state):
    state["posted_urls"] = state["posted_urls"][-350:]
    with open("posted_urls.json", "w") as f:
        json.dump(state, f, indent=2)

def get_valid_chat_models():
    preferred_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
    try:
        live_models = [m.id for m in groq_client.models.list().data]
        valid = [m for m in preferred_models if m in live_models]
        if valid:
            return valid
    except Exception:
        pass
    return ["llama-3.1-8b-instant"]

def is_bengali_script(text):
    return bool(re.search(r"[\u0980-\u09FF]", text))

def clean_ai_output(text):
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*#_`]", "", text)
    text = re.sub(r"^(Headline:|Title:|Output:|Here is.*?:)", "", text, flags=re.IGNORECASE)
    text = text.replace('"', '').replace("'", "").strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return lines[0] if lines else ""

def pre_clean_raw_title(title):
    cleaned = re.sub(r"<[^>]+>", "", title)
    patterns = [r"\[.*?\]", r"\(.*?\)", r"\|.*$", r"-.*$", r"^\s*[:\-\–\—]\s*"]
    for p in patterns:
        cleaned = re.sub(p, "", cleaned)
    return cleaned.strip()

def get_box1_caption_title(raw_title):
    cleaned = pre_clean_raw_title(raw_title)
    if is_bengali_script(cleaned):
        return cleaned
    
    models = get_valid_chat_models()
    prompt = f"Translate the meaning of this news into 1 short Bengali headline. Return ONLY pure Bengali script without quotes:\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional Bengali news translator. Return only Bengali script."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=60,
                temperature=0.2
            )
            out = clean_ai_output(res.choices[0].message.content)
            if is_bengali_script(out):
                return out
        except Exception:
            continue
    return cleaned

def get_box3_card_headline(raw_title):
    cleaned = pre_clean_raw_title(raw_title)
    if is_bengali_script(cleaned):
        return cleaned
    
    models = get_valid_chat_models()
    prompt = f"Rewrite this news title into a sharp, journalistic English headline (7 to 11 words). Return English text ONLY:\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a headline copy editor. Return the final clean headline only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=60,
                temperature=0.2
            )
            out = clean_ai_output(res.choices[0].message.content)
            if len(out.split()) >= 4:
                return out
        except Exception:
            continue
    return cleaned[:85]

def extract_image_url(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        url = entry.media_content[0].get('url')
        if url and not url.endswith(('.svg', '.gif')):
            return url

    if 'enclosures' in entry and len(entry.enclosures) > 0:
        url = entry.enclosures[0].get('href')
        if url and not url.endswith(('.svg', '.gif')):
            return url

    if 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        url = entry.media_thumbnail[0].get('url')
        if url:
            return url

    html_corpus = (entry.get('summary', '') + ' ' + entry.get('description', ''))
    img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', html_corpus, re.IGNORECASE)
    if img_match:
        return img_match.group(1)

    try:
        page_resp = requests.get(entry.link, timeout=5, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if page_resp.status_code == 200:
            og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']', page_resp.text, re.IGNORECASE)
            if not og_match:
                og_match = re.search(r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']', page_resp.text, re.IGNORECASE)
            if og_match:
                return og_match.group(1)
    except Exception:
        pass

    return None

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

def ensure_font_downloaded():
    font_file = "HindSiliguri-Bold.ttf"
    if not os.path.exists(font_file):
        url = "https://raw.githubusercontent.com/google/fonts/main/ofl/hindsiliguri/HindSiliguri-Bold.ttf"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                with open(font_file, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    return font_file if os.path.exists(font_file) else None

def get_universal_font(size=32):
    local_font = ensure_font_downloaded()
    if local_font:
        try:
            return ImageFont.truetype(local_font, size)
        except:
            pass
    fallbacks = [
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for fb in fallbacks:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except:
                continue
    return ImageFont.load_default()

def get_asset_path(base_name):
    for ext in [".jpg", ".jpeg", ".png"]:
        if os.path.exists(f"{base_name}{ext}"):
            return f"{base_name}{ext}"
    return None

def create_dacca_card(image_url, headline, source_name):
    width, height = 1080, 1350
    card = Image.new("RGB", (width, height), color="#000000")
    draw = ImageDraw.Draw(card)

    font_date = get_universal_font(28)
    font_headline = get_universal_font(52)
    font_footer = get_universal_font(28)

    # 1. Top Left Header Logo
    header_path = get_asset_path("header_logo")
    if header_path:
        try:
            h_logo = Image.open(header_path).convert("RGB")
            aspect = h_logo.width / h_logo.height
            h_logo = h_logo.resize((int(52 * aspect), 52), Image.Resampling.LANCZOS)
            card.paste(h_logo, (50, 42))
        except Exception:
            draw.text((50, 42), "DACCAখবর", fill="#ffffff", font=font_headline)
    else:
        draw.text((50, 42), "DACCAখবর", fill="#ffffff", font=font_headline)

    # 1.1 Top Right Date
    today_str = datetime.utcnow().strftime("%d %b %Y").upper()
    date_bbox = draw.textbbox((0, 0), today_str, font=font_date)
    draw.text((width - 50 - (date_bbox[2] - date_bbox[0]), 52), today_str, fill="#9ca3af", font=font_date)

    # 2. Headline Canvas Text
    wrapped_lines = wrap_text(headline, font_headline, width - 100, draw)
    text_y = 125
    for line in wrapped_lines[:3]:
        draw.text((50, text_y), line, fill="#ffffff", font=font_headline)
        text_y += 74

    # 3. Middle Photo
    image_top = max(text_y + 30, 360)
    image_height = 840
    try:
        resp = requests.get(image_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        raw_img = Image.open(BytesIO(resp.content)).convert("RGB")
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
        
        resized = raw_img.resize((width - 100, image_height), Image.Resampling.LANCZOS)
        card.paste(resized, (50, image_top))
    except Exception as e:
        print(f"Card image render error: {e}")
        draw.rectangle([(50, image_top), (width - 50, image_top + image_height)], fill="#1f2937")

    # 4. Footer Source
    footer_y = image_top + image_height + 40
    draw.text((50, footer_y + 12), f"VIA - {source_name}", fill="#e5e7eb", font=font_footer)

    # 5. Footer Watermark
    logo_path = get_asset_path("logo")
    if logo_path:
        try:
            d_logo = Image.open(logo_path).convert("RGB")
            aspect = d_logo.width / d_logo.height
            d_logo = d_logo.resize((int(82 * aspect), 82), Image.Resampling.LANCZOS)
            card.paste(d_logo, (width - 50 - d_logo.width, footer_y - 12))
        except Exception:
            pass

    output_path = "final_card.jpg"
    card.save(output_path, "JPEG", quality=95)
    return output_path

def create_instagram_story_card(feed_card_path):
    """Pads the 4:5 card into 1080x1920 (9:16) specifically required by Instagram Stories."""
    story_bg = Image.new("RGB", (1080, 1920), color="#000000")
    feed_card = Image.open(feed_card_path).convert("RGB")
    # Paste centered vertically
    y_offset = (1920 - 1350) // 2
    story_bg.paste(feed_card, (0, y_offset))
    story_path = "final_story_card.jpg"
    story_bg.save(story_path, "JPEG", quality=95)
    return story_path

def upload_image_to_web(image_path):
    """Uploads with multiple fallbacks so Meta's crawler never gets blocked."""
    # Attempt 1: Catbox
    try:
        with open(image_path, "rb") as f:
            res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": f}, timeout=15)
            url = res.text.strip()
            if url.startswith("http"):
                return url
    except Exception as e:
        print(f"Catbox failed: {e}")

    # Attempt 2: Litterbox (Temporary 1-hour fast host)
    try:
        with open(image_path, "rb") as f:
            res = requests.post("https://litterbox.catbox.moe/resources/internals/api.php", data={"reqtype": "fileupload", "time": "1h"}, files={"fileToUpload": f}, timeout=15)
            url = res.text.strip()
            if url.startswith("http"):
                return url
    except Exception as e:
        print(f"Litterbox failed: {e}")

    return None

def post_facebook_feed(image_path, caption):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    payload = {
        "caption": caption,
        "published": "true",
        "feed": "true",
        "access_token": ACCESS_TOKEN
    }
    with open(image_path, "rb") as f:
        res = requests.post(url, files={"source": f}, data=payload).json()
        print("Facebook Feed Public Response:", res)
        return res

def post_facebook_story(image_path):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    payload = {"published": "false", "temporary": "true", "access_token": ACCESS_TOKEN}
    with open(image_path, "rb") as f:
        res = requests.post(url, files={"source": f}, data=payload).json()
        photo_id = res.get("id")
        if photo_id:
            story_url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photo_stories"
            story_res = requests.post(story_url, data={"photo_id": photo_id, "access_token": ACCESS_TOKEN}).json()
            print("Facebook Story Response:", story_res)

def wait_for_ig_container(creation_id):
    """Polls Meta until container status is FINISHED."""
    status_url = f"https://graph.facebook.com/v20.0/{creation_id}?fields=status_code&access_token={ACCESS_TOKEN}"
    for _ in range(8):
        time.sleep(5)
        res = requests.get(status_url).json()
        status = res.get("status_code")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            print(f"Instagram container failed status: {res}")
            return False
    return True

def post_instagram_feed(image_url, caption):
    if not IG_USER_ID:
        return None
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN
    }
    res = requests.post(create_url, data=payload).json()
    print("IG Feed Media Container Response:", res)
    creation_id = res.get("id")
    if not creation_id:
        return None

    if wait_for_ig_container(creation_id):
        publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
        pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
        print("Instagram Feed Publish Response:", pub_res)
        return pub_res.get("id")
    return None

def post_instagram_story(story_image_url):
    if not IG_USER_ID:
        return
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": story_image_url,
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN
    }
    res = requests.post(create_url, data=payload).json()
    print("IG Story Media Container Response:", res)
    creation_id = res.get("id")
    if not creation_id:
        return

    if wait_for_ig_container(creation_id):
        publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
        pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
        print("Instagram Story Publish Response:", pub_res)

def publish_article(entry, source_name, img_url):
    print(f"Publishing from {source_name}: {entry.title}")
    
    caption_headline_bn = get_box1_caption_title(entry.title)
    card_headline = get_box3_card_headline(entry.title)
    
    # 1. Create standard 4:5 Feed card
    card_path = create_dacca_card(img_url, card_headline, source_name)
    post_caption = f"{caption_headline_bn}\n\nবিস্তারিত লিংকে:\n{entry.link}"
    
    # 2. Facebook Feed & Story
    print(f"Dispatching {source_name} to Facebook...")
    post_facebook_feed(card_path, post_caption)
    try:
        post_facebook_story(card_path)
    except Exception as err:
        print(f"FB Story bypass: {err}")

    # 3. Instagram Feed & Story
    if IG_USER_ID:
        print("Preparing Instagram delivery...")
        # Upload 4:5 card for Feed
        feed_web_url = upload_image_to_web(card_path)
        
        # Build 9:16 padded card for IG Story & Upload
        story_card_path = create_instagram_story_card(card_path)
        story_web_url = upload_image_to_web(story_card_path)

        if feed_web_url:
            print("Posting to Instagram Feed...")
            try:
                post_instagram_feed(feed_web_url, f"{card_headline}\n\nVia: {source_name}\n\n#news #breakingnews #bangladesh #dacca")
            except Exception as err:
                print(f"IG Feed error: {err}")

        if story_web_url:
            print("Posting to Instagram Story...")
            try:
                post_instagram_story(story_web_url)
            except Exception as err:
                print(f"IG Story error: {err}")

def find_candidate_in_category(category_name, feed_list, state):
    total_feeds = len(feed_list)
    start_idx = state["indices"].get(category_name, 0) % total_feeds
    
    for i in range(total_feeds):
        current_idx = (start_idx + i) % total_feeds
        feed = feed_list[current_idx]
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                clean_title = pre_clean_raw_title(entry.title)
                if len(clean_title.split()) < 3:
                    continue

                if entry.link not in state["posted_urls"]:
                    img_url = extract_image_url(entry)
                    if not img_url:
                        continue

                    state["indices"][category_name] = (current_idx + 1) % total_feeds
                    return entry, feed["name"], img_url
        except Exception as err:
            print(f"Skipping {feed['name']}: {err}")
            continue

    state["indices"][category_name] = (start_idx + 1) % total_feeds
    return None, None, None

def find_any_fresh_article(all_feeds, state):
    for feed in all_feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                clean_title = pre_clean_raw_title(entry.title)
   
