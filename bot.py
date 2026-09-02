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
    ignored = ["guard", "whisper", "embed", "tts", "safeguard"]
    try:
        return [m.id for m in groq_client.models.list().data if not any(k in m.id.lower() for k in ignored)]
    except:
        return ["llama-3.1-8b-instant"]

def pre_clean_raw_title(title):
    patterns = [r"\[.*?\]", r"\(.*?\)", r"\|.*$", r"-.*$", r"^\s*[:\-\–\—]\s*"]
    cleaned = title
    for p in patterns:
        cleaned = re.sub(p, "", cleaned)
    return cleaned.strip()

def clean_title_or_translate(title):
    cleaned_input = pre_clean_raw_title(title)
    models = get_valid_chat_models()
    
    prompt = f"""You are a professional headline editor for a top digital news outlet.
Transform this news title into a sharp, active headline strictly between 7 to 11 words.

Rules:
1. Retain the exact language of the original title (if Bengali, write punchy Bengali; if English, write punchy English).
2. Never include quotes, asterisks, brackets, or source attribution.
3. Keep it factually accurate and impactful.
4. Output the headline text ONLY with no preamble.

Original Title:
{cleaned_input}"""

    for model in models:
        try:
            res = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.3
            )
            headline = res.choices[0].message.content.strip().replace('"', '').replace("'", "")
            if 15 <= len(headline) <= 120 and not headline.replace(".", "").isdigit():
                return headline
        except Exception:
            continue
            
    return cleaned_input[:85]

def extract_image_url(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        url = entry.media_content[0].get('url')
        if url:
            return url
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        url = entry.enclosures[0].get('href')
        if url:
            return url
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

def get_system_font(font_type="bold", size=32):
    font_paths = {
        "bengali_bold": [
            "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
            "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ],
        "bengali_regular": [
            "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
            "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]
    }
    target_key = "bengali_bold" if font_type == "bold" else "bengali_regular"
    for path in font_paths[target_key]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
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

    font_date = get_system_font("bold", 28)
    font_headline = get_system_font("bold", 54)
    font_footer = get_system_font("bold", 28)

    # 1. Top Left: Header Banner Graphic
    header_path = get_asset_path("header_logo")
    if header_path:
        try:
            h_logo = Image.open(header_path).convert("RGB")
            aspect = h_logo.width / h_logo.height
            h_logo = h_logo.resize((int(52 * aspect), 52), Image.Resampling.LANCZOS)
            card.paste(h_logo, (50, 42))
        except Exception as e:
            print(f"Header logo paste failed: {e}")
            draw.text((50, 42), "DACCAখবর", fill="#ffffff", font=font_headline)
    else:
        draw.text((50, 42), "DACCAখবর", fill="#ffffff", font=font_headline)

    # 1.1 Top Right: Date
    today_str = datetime.utcnow().strftime("%d %b %Y").upper()
    date_bbox = draw.textbbox((0, 0), today_str, font=font_date)
    draw.text((width - 50 - (date_bbox[2] - date_bbox[0]), 52), today_str, fill="#9ca3af", font=font_date)

    # 2. Headline
    wrapped_lines = wrap_text(headline, font_headline, width - 100, draw)
    text_y = 125
    for line in wrapped_lines[:3]:
        draw.text((50, text_y), line, fill="#ffffff", font=font_headline)
        text_y += 74

    # 3. Middle News Image
    image_top = max(text_y + 30, 360)
    image_height = 840
    try:
        resp = requests.get(image_url, timeout=15)
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

    # 4. Footer: Left Side VIA Source
    footer_y = image_top + image_height + 40
    draw.text((50, footer_y + 12), f"VIA - {source_name}", fill="#e5e7eb", font=font_footer)

    # 5. Footer: Right Side Corner Logo
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
    with open(image_path, "rb") as f:
        res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": f})
        return res.text.strip()

def post_facebook_feed(image_path, caption):
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        res = requests.post(url, files={"source": f}, data={"caption": caption, "access_token": ACCESS_TOKEN}).json()
        print("Facebook Feed Response:", res)
        return res

def post_facebook_comment(post_id, link):
    if not post_id:
        return
    comment_url = f"https://graph.facebook.com/v20.0/{post_id}/comments"
    payload = {
        "message": f"বিস্তারিত পড়তে ভিজিট করুন:\n{link}",
        "access_token": ACCESS_TOKEN
    }
    res = requests.post(comment_url, data=payload).json()
    print("Facebook Comment Response:", res)

def post_facebook_story(image_path):
    # FB Page Photo Story via Graph API
    url = f"https://graph.facebook.com/v20.0/{PAGE_ID}/photos"
    with open(image_path, "rb") as f:
        payload = {
            "published": "true",
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
        print(f"IG Feed Media creation failed: {res}")
        return None
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
    print("Instagram Feed Response:", pub_res)
    return pub_res.get("id")

def post_instagram_story(image_url):
    # IG Stories Container API
    create_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN
    }
    res = requests.post(create_url, data=payload).json()
    creation_id = res.get("id")
    if not creation_id:
        print(f"IG Story Media creation failed: {res}")
        return
    time.sleep(10)
    publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
    pub_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}).json()
    print("Instagram Story Response:", pub_res)

def main():
    posted = load_posted_urls()
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                if entry.link not in posted:
                    print(f"Processing candidate: {entry.title}")
                    headline = clean_title_or_translate(entry.title)
                    img_url = extract_image_url(entry)
                    
                    card_path = create_dacca_card(img_url, headline, feed["name"])
                    
                    # 1. Post Feed to Facebook & Auto-comment source link
                    post_caption = "Details in Comment..."
                    print("Dispatching to Facebook Feed...")
                    fb_res = post_facebook_feed(card_path, post_caption)
                    fb_post_id = fb_res.get("post_id") or fb_res.get("id")
                    post_facebook_comment(fb_post_id, entry.link)

                    # 2. Post Story to Facebook
                    print("Dispatching to Facebook Story...")
                    try:
                        post_facebook_story(card_path)
                    except Exception as err:
                        print(f"FB Story bypass: {err}")

                    # 3. Post Feed & Story to Instagram
                    if IG_USER_ID:
                        print("Hosting card asset for Instagram...")
                        catbox_url = upload_to_catbox(card_path)
                        
                        print("Dispatching to Instagram Feed...")
                        post_instagram_feed(cpatbox_url, f"{headline}\n\nVia: {feed['name']}\n\n#news #breakingnews #bangladesh #dacca")

                        print("Dispatching to Instagram Story...")
                        try:
                            post_instagram_story(catbox_url)
                        except Exception as err:
                            print(f"IG Story bypass: {err}")

                    posted.append(entry.link)
                    save_posted_urls(posted)
                    return
        except Exception as err:
            print(f"Skipping {feed['name']}: {err}")
            continue

if __name__ == "__main__":
    main()
            
