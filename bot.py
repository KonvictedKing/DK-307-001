import os
import re
import json
import time
import urllib.parse
from datetime import datetime
from io import BytesIO

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8"
}

def load_state():
    state = {"posted_urls": [], "indices": {"national": 0, "international": 0, "sports": 0}}
    if os.path.exists("posted_urls.json"):
        try:
            with open("posted_urls.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    state["posted_urls"] = data
                elif isinstance(data, dict):
                    state["posted_urls"] = data.get("posted_urls", [])
                    state["indices"] = data.get("indices", state["indices"])
        except Exception:
            pass
    return state

def save_state(state):
    state["posted_urls"] = state["posted_urls"][-350:]
    with open("posted_urls.json", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

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
    patterns = [r"\[.*?\]", r"\(.*?\)", r"\|.*$"]
    for p in patterns:
        cleaned = re.sub(p, "", cleaned)
    return cleaned.strip()

def get_bengali_headline(raw_title):
    cleaned = pre_clean_raw_title(raw_title)
    if is_bengali_script(cleaned):
        return cleaned
    
    models = get_valid_chat_models()
    prompt = f"Translate the meaning of this news into 1 clear Bengali headline. Return ONLY Bengali script without quotes:\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a professional Bengali journalist. Output only the Bengali headline."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=80,
                temperature=0.2
            )
            out = clean_ai_output(res.choices[0].message.content)
            if is_bengali_script(out):
                return out
        except Exception:
            continue
    return cleaned

def get_english_headline(raw_title):
    cleaned = pre_clean_raw_title(raw_title)
    models = get_valid_chat_models()
    prompt = f"Rewrite or translate this news title into a sharp, complete English headline (8 to 13 words). Never cut it mid-sentence. Return English ONLY:\n{cleaned}"
    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a senior news copy editor. Produce full, grammatically complete English headlines only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=80,
                temperature=0.2
            )
            out = clean_ai_output(res.choices[0].message.content)
            if len(out.split()) >= 4:
                return out
        except Exception:
            continue
    return cleaned

def extract_high_res_image(entry):
    try:
        resp = requests.get(entry.link, timeout=8, headers=BROWSER_HEADERS)
        if resp.status_code == 200:
            html = resp.text
            patterns = [
                r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\'](https?://[^"\']+)["\']',
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
                r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\'](https?://[^"\']+)["\']'
            ]
            for pat in patterns:
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    candidate = m.group(1)
                    if not candidate.endswith(('.svg', '.gif', '.ico')):
                        return candidate
    except Exception:
        pass

    if 'media_content' in entry and len(entry.media_content) > 0:
        url = entry.media_content[0].get('url')
        if url and not url.endswith(('.svg', '.gif')):
            return url

    if 'enclosures' in entry and len(entry.enclosures) > 0:
        url = entry.enclosures[0].get('href')
        if url and not url.endswith(('.svg', '.gif')):
            return url

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
        except Exception:
            pass
    fallbacks = [
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for fb in fallbacks:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                continue
    return ImageFont.load_default()

def get_asset_path(base_name):
    for ext in [".png", ".jpg", ".jpeg"]:
        if os.path.exists(f"{base_name}{ext}"):
            return f"{base_name}{ext}"
    return None

def create_dacca_card(image_url, headline, source_name):
    width, height = 1080, 1080
    card = Image.new("RGB", (width, height), color="#000000")
    draw = ImageDraw.Draw(card)

    font_date = get_universal_font(24)
    font_headline = get_universal_font(42)
    font_footer = get_universal_font(24)
    font_brand_text = get_universal_font(38)

    # 1. Header Logo & Date
    header_path = get_asset_path("header_logo")
    if header_path:
        try:
            h_logo = Image.open(header_path).convert("RGBA")
            aspect = h_logo.width / h_logo.height
            h_logo = h_logo.resize((int(48 * aspect), 48), Image.Resampling.LANCZOS)
            card.paste(h_logo, (45, 35), mask=h_logo.split()[3])
        except Exception:
            draw.text((45, 35), "DACCAখবর", fill="#ffffff", font=font_brand_text)
    else:
        draw.text((45, 35), "DACCAখবর", fill="#ffffff", font=font_brand_text)

    today_str = datetime.utcnow().strftime("%d %b %Y").upper()
    date_bbox = draw.textbbox((0, 0), today_str, font=font_date)
    draw.text((width - 45 - (date_bbox[2] - date_bbox[0]), 45), today_str, fill="#9ca3af", font=font_date)

    # 2. Headline
    wrapped_lines = wrap_text(headline, font_headline, width - 90, draw)
    text_y = 105
    for line in wrapped_lines[:3]:
        draw.text((45, text_y), line, fill="#ffffff", font=font_headline)
        text_y += 58

    # 3. Download & Place Image (1:1 Fit)
    image_top = max(text_y + 25, 290)
    image_box_size = width - 90
    image_height = height - image_top - 110

    try:
        resp = requests.get(image_url, timeout=12, headers=BROWSER_HEADERS)
        if resp.status_code != 200:
            print(f"Image HTTP error: {resp.status_code}")
            return None
        
        raw_img = Image.open(BytesIO(resp.content)).convert("RGB")
        if raw_img.width < 300 or raw_img.height < 200:
            print("Image resolution too low. Skipping.")
            return None

        target_ratio = image_box_size / image_height
        raw_ratio = raw_img.width / raw_img.height

        if raw_ratio > target_ratio:
            new_width = int(raw_img.height * target_ratio)
            left = (raw_img.width - new_width) // 2
            raw_img = raw_img.crop((left, 0, left + new_width, raw_img.height))
        else:
            new_height = int(raw_img.width / target_ratio)
            top = (raw_img.height - new_height) // 2
            raw_img = raw_img.crop((0, top, raw_img.width, top + new_height))

        resized = raw_img.resize((image_box_size, image_height), Image.Resampling.LANCZOS)
        card.paste(resized, (45, image_top))
    except Exception as e:
        print(f"Image load failure: {e}")
        return None

    # 4. Footer & Enlarged Corner Logo (88px)
    footer_y = image_top + image_height + 25
    draw.text((45, footer_y + 16), f"VIA - {source_name.upper()}", fill="#e5e7eb", font=font_footer)

    logo_path = get_asset_path("logo")
    if logo_path:
        try:
            d_logo = Image.open(logo_path).convert("RGBA")
            aspect = d_logo.width / d_logo.height
            logo_height = 88
            d_logo = d_logo.resize((int(logo_height * aspect), logo_height), Image.Resampling.LANCZOS)
            card.paste(d_logo, (width - 45 - d_logo.width, footer_y - 12), mask=d_logo.split()[3])
        except Exception:
            pass

    output_path = "final_card.jpg"
    card.save(output_path, "JPEG", quality=95)
    return output_path

def create_instagram_story_card(feed_card_path):
    story_w, story_h = 1080, 1920
    feed_card = Image.open(feed_card_path).convert("RGB")

    bg = feed_card.resize((story_w, story_h), Image.Resampling.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=45))
    dark_overlay = Image.new("RGB", (story_w, story_h), color="#000000")
    bg = Image.blend(bg, dark_overlay, alpha=0.35)

    target_card_w = int(story_w * 0.88)
    scaled_card = feed_card.resize((target_card_w, target_card_w), Image.Resampling.LANCZOS)

    radius = 32
    mask = Image.new("L", (target_card_w, target_card_w), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([(0, 0), (target_card_w, target_card_w)], radius=radius, fill=255)

    card_x = (story_w - target_card_w) // 2
    card_y = (story_h - target_card_w) // 2 - 50
    bg.paste(scaled_card, (card_x, card_y), mask)

    draw = ImageDraw.Draw(bg)
    handle_font = get_universal_font(34)
    draw.text((card_x + 10, card_y + target_card_w + 30), "@dacca.news", fill="#ffffff", font=handle_font)

    story_path = "final_story_card.jpg"
    bg.save(story_path, "JPEG", quality=95)
    return story_path

def get_fb_image_url(photo_id):
    try:
        url = f"https://graph.facebook.com/v20.0/{photo_id}?fields=images&access_token={ACCESS_TOKEN}"
        res = requests.get(url, timeout=10).json()
        if "images" in res and len(res["images"]) > 0:
            return res["images"][0]["source"]
    except Exception as e:
        print(f"Meta CDN Fetch Error: {e}")
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

def post_facebook_comment(target_id, message):
    url = f"https://graph.facebook.com/v20.0/{target_id}/comments"
    payload = {
        "message": message,
        "access_token": ACCESS_TOKEN
    }
    try:
        res = requests.post(url, data=payload, timeout=15).json()
        print("Facebook Comment Response:", res)
        return res
    except Exception as e:
        print(f"Failed to post FB comment: {e}")
        return None

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
    status_url = f"https://graph.facebook.com/v20.0/{creation_id}?fields=status_code&access_token={ACCESS_TOKEN}"
    for _ in range(8):
        time.sleep(5)
        res = requests.get(status_url).json()
        status = res.get("status_code")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            print(f"IG container error: {res}")
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
    
    clean_raw = pre_clean_raw_title(entry.title)
    is_bn = is_bengali_script(clean_raw)
    
    if is_bn:
        caption_title = get_bengali_headline(clean_raw)
        card_headline = caption_title
        notice_text = "(বিস্তারিত প্রথম কমেন্টে)"
        comment_text = f"সম্পূর্ণ প্রতিবেদনটি পড়তে ভিজিট করুন:\n{entry.link}"
    else:
        caption_title = get_english_headline(clean_raw)
        card_headline = caption_title
        notice_text = "(Details in the first comment)"
        comment_text = f"To read the full report, visit:\n{entry.link}"
    
    card_path = create_dacca_card(img_url, card_headline, source_name)
    if not card_path:
        print(f"Skipping article because image could not be rendered: {entry.title}")
        return False
    
    post_caption = f"{caption_title}\n\n{notice_text}"
    
    print(f"Dispatching {source_name} to Facebook...")
    fb_res = post_facebook_feed(card_path, post_caption)
    fb_photo_id = fb_res.get("id") if isinstance(fb_res, dict) else None

    if fb_photo_id:
        post_facebook_comment(fb_photo_id, comment_text)

    try:
        post_facebook_story(card_path)
    except Exception as err:
        print(f"FB Story bypass: {err}")

    if IG_USER_ID and fb_photo_id:
        print("Fetching Meta CDN URL for Instagram...")
        cdn_url = get_fb_image_url(fb_photo_id)

        if cdn_url:
            print("Posting to Instagram Feed...")
            try:
                post_instagram_feed(cdn_url, f"{card_headline}\n\nVia: {source_name}\n\n#news #breakingnews #bangladesh #dacca")
            except Exception as err:
                print(f"IG Feed error: {err}")

        try:
            print("Generating styled Instagram Story card...")
            styled_story_path = create_instagram_story_card(card_path)
            
            with open(styled_story_path, "rb") as f:
                temp_res = requests.post(
                    f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos",
                    files={"source": f},
                    data={"published": "false", "temporary": "true", "access_token": ACCESS_TOKEN}
                ).json()
            
            story_cdn = get_fb_image_url(temp_res.get("id"))
            if story_cdn:
                print("Posting styled card to Instagram Story...")
                post_instagram_story(story_cdn)
        except Exception as err:
            print(f"IG Story styling error: {err}")
            
    return True

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
                    img_url = extract_high_res_image(entry)
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
                if len(clean_title.split()) < 3:
                    continue

                if entry.link not in state["posted_urls"]:
                    img_url = extract_high_res_image(entry)
                    if img_url:
                        return entry, feed["name"], img_url
        except Exception:
            continue
    return None, None, None

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
        entry, source_name, img_url = find_candidate_in_category(cat_name, feed_list, state)
        
        if not entry:
            print(f"No fresh articles in {cat_name}. Falling back to any available fresh news with photos.")
            entry, source_name, img_url = find_any_fresh_article(all_feeds, state)

        if entry and img_url:
            success = publish_article(entry, source_name, img_url)
            if success:
                state["posted_urls"].append(entry.link)
                save_state(state)
                posts_done += 1
                time.sleep(20)

    print(f"Cycle finished. Total published in this run: {posts_done}")

if __name__ == "__main__":
    main()
