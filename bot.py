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
    state = {
        "posted_urls": [],
        "indices": {"national": 0, "international": 0, "sports": 0}
    }
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
    ignored = ["guard", "whisper", "embed", "tts", "safeguard"]
    try:
        return [m.id for m in groq_client.models.list().data if not any(k in m.id.lower() for k in ignored)]
    except:
        return ["llama-3.1-8b-instant"]

def is_bengali_script(text):
    return bool(re.search(r"[\u0980-\u09FF]", text))

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
    prompt = f"Translate this headline into clear, natural Bengali. Output Bengali text ONLY with no quotes:\n\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.2
            )
            out = res.choices[0].message.content.strip().replace('"', '').replace("'", "")
            if len(out) > 3:
                return out
        except Exception:
            continue
    return cleaned

def get_box3_card_headline(raw_title):
    cleaned = pre_clean_raw_title(raw_title)
    if is_bengali_script(cleaned):
        return cleaned
    
    models = get_valid_chat_models()
    prompt = f"Rewrite this headline into a sharp, journalistic English headline (7 to 11 words). Output English ONLY with no quotes or preamble:\n\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.2
            )
            out = res.choices[0].message.content.strip().replace('"', '').replace("'", "")
            if len(out) > 3:
                return out
        except Exception:
            continue
    return cleaned[:85]

def extract_image_url(entry):
    # Check media:content
    if 'media_content' in entry and len(entry.media_content) > 0:
        url = entry.media_content[0].get('url')
        if url:
            return url

    # Check enclosures
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        url = entry.enclosures[0].get('href')
        if url:
            return url

    # Check media_thumbnail
    if 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        url = entry.media_thumbnail[0].get('url')
        if url:
            return url

    # Safe placeholder image instead of unfiltered AI generation
    return "https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1080&q=80"

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
        except Exception as e:
            print(f"Font download error: {e}")
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

    # 2. Box 3: Headline Canvas Text
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
        print(f"News image process fallback: {e}")
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
        except Exception as e:
            print(f"Footer logo error: {e}")

    output_path = "final_card.jpg"
    card.save(output_path, "JPEG", quality=95)
    return output_path

def upload_to_catbox(image_path):
    try:
        with open(image_path, "rb") as f:
            res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": f}, timeout=20)
            return res.text.strip()
    except Exception as e:
        print(f"Catbox upload failed: {e}")
        return None

def post_facebook_feed(image_path, caption):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        res = requests.post(url, files={"source": f}, data={"caption": caption, "access_token": ACCESS_TOKEN}).json()
        print("Facebook Feed Response:", res)
        return res

def post_facebook_story(image_path):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        payload = {
            "published": "false",
            "temporary": "true",
            "access_token": ACCESS_TOKEN
        }
        res = requests.post(url, files={"source": f}, data=payload).json()
        photo_id = res.get("id")
        if photo_id:
            story_url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photo_stories"
            story_res = requests.post(story_url, data={"photo_id": photo_id, "access_token": ACCESS_TOKEN}).json()
            print("Facebook Story Response:", story_res)

def post_instagram_feed(image_url, caption):
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    res = requests.post(create_url, data={"image_url": image_url, "caption": caption, "access_token": ACCESS_TOKEN}).json()
    creation_id = res.get("id")
    if not creation_id:
        return None
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
    print("Instagram Feed Response:", pub_res)
    return pub_res.get("id")

def post_instagram_story(image_url):
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN
    }
    res = requests.post(create_url, data=payload).json()
    creation_id = res.get("id")
    if not creation_id:
        return
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
    print("Instagram Story Response:", pub_res)

def publish_article(entry, source_name):
    print(f"Publishing from {source_name}: {entry.title}")
    
    # 1. Box 1: Guarantee non-empty Bengali title
    caption_headline_bn = get_box1_caption_title(entry.title)
    if not caption_headline_bn or len(caption_headline_bn.strip()) == 0:
        caption_headline_bn = pre_clean_raw_title(entry.title)

    # 2. Box 3: Headline on the Card
    card_headline = get_box3_card_headline(entry.title)
    if not card_headline or len(card_headline.strip()) == 0:
        card_headline = pre_clean_raw_title(entry.title)
    
    # 3. Download verified image or clean neutral fallback
    img_url = extract_image_url(entry)
    card_path = create_dacca_card(img_url, card_headline, source_name)
    
    # Format Caption: Box 1 + Box 2
    post_caption = f"{caption_headline_bn}\n\nবিস্তারিত লিংকে:\n{entry.link}"
    print(f"Dispatching {source_name} to Facebook Feed...")
    post_facebook_feed(card_path, post_caption)

    try:
        post_facebook_story(card_path)
    except Exception as err:
        print(f"FB Story bypass: {err}")

    if IG_USER_ID:
        catbox_url = upload_to_catbox(card_path)
        if catbox_url and catbox_url.startswith("http"):
            try:
                post_instagram_feed(catbox_url, f"{card_headline}\n\nVia: {source_name}\n\n#news #breakingnews #bangladesh #dacca")
            except Exception as err:
                print(f"IG Feed bypass: {err}")

            try:
                post_instagram_story(catbox_url)
            except Exception as err:
                print(f"IG Story bypass: {err}")

def find_candidate_in_category(category_name, feed_list, state):
    total_feeds = len(feed_list)
    start_idx = state["indices"].get(category_name, 0) % total_feeds
    
    for i in range(total_feeds):
        current_idx = (start_idx + i) % total_feeds
        feed = feed_list[current_idx]
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                if entry.link not in state["posted_urls"]:
                    state["indices"][category_name] = (current_idx + 1) % total_feeds
                    return entry, feed["name"]
        except Exception as err:
            print(f"Skipping {feed['name']}: {err}")
            continue

    state["indices"][category_name] = (start_idx + 1) % total_feeds
    return None, None

def find_any_fresh_article(all_feeds, state):
    for feed in all_feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                if entry.link not in state["posted_urls"]:
                    return entry, feed["name"]
        except Exception:
            continue
    return None, None

def main():
    state = load_state()
    categories = [
        ("national", NATIONAL_FEEDS),
        ("international", INTERNATIONAL_FEEDS),
        ("sports", SPORTS_FEEDS)
    ]
    
    posts_done = 0
    all_feeds = NATIONAL_FEEDS + INTERNATIONAL_FEEDS + SPORTS_FEEDS

    for cat_name, feed_list in categories:
        entry, source_name = find_candidate_in_category(cat_name, feed_list, state)
        
        if not entry:
            print(f"No fresh articles in {cat_name}. Falling back to any available fresh news.")
            entry, source_name = find_any_fresh_article(all_feeds, state)

        if entry:
            publish_article(entry, source_name)
            state["posted_urls"].append(entry.link)
            save_state(state)
            posts_done += 1
            time.sleep(15)

    print(f"Cycle finished. Total published in this run: {posts_done}")

if __name__ == "__main__":
    main()
    
