import os
import json
import requests
import feedparser
from groq import Groq
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from datetime import datetime

# Environment Variables
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
IG_USER_ID = os.environ.get("IG_USER_ID")
ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)

POSTED_FILE = "posted_urls.json"

FEEDS = {
    "National": [
        "https://www.prothomalo.com/feed",
        "https://bangla.bdnews24.com/?widgetName=rssfeed&widgetId=1151&getXmlFeed=true",
        "https://www.thedailystar.net/bangla/rss.xml"
    ],
    "International": [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml"
    ],
    "Sports": [
        "https://www.skysports.com/rss/12040",
        "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"
    ]
}

def load_posted_urls():
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_posted_url(url):
    posted = load_posted_urls()
    posted.add(url)
    with open(POSTED_FILE, "w") as f:
        json.dump(list(posted), f, indent=2)

def extract_image_url(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get("url")
    if "enclosures" in entry and len(entry.enclosures) > 0:
        return entry.enclosures[0].get("href")
    return None

def is_bengali_text(text):
    return any('\u0980' <= c <= '\u09FF' for c in text)

def generate_text(title, summary):
    if is_bengali_text(title):
        prompt = f"""
নিচের সংবাদের শিরোনাম ও বিবরণ থেকে সোশ্যাল মিডিয়া ফটো কার্ডের উপযোগী একটি আকর্ষণীয় বাংলা হেডলাইন তৈরি করুন (সর্বোচ্চ ৮-১২ শব্দ):
শিরোনাম: {title}
বিবরণ: {summary}

Strictly output JSON:
{{"headline": "..."}}
"""
    else:
        prompt = f"""
Given this news story, generate a concise, punchy English headline (7 to 11 words maximum) suitable for a social news card. If the language is not English, translate it accurately to English.
Title: {title}
Summary: {summary}

Strictly output JSON:
{{"headline": "..."}}
"""
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        data = json.loads(completion.choices[0].message.content)
        return data.get("headline", title)
    except Exception as e:
        print(f"Groq API error: {e}")
        return title

def wrap_text(text, font, max_width, draw):
    lines = []
    words = text.split()
    current_line = []
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) > max_width:
            if len(current_line) == 1:
                lines.append(test_line)
                current_line = []
            else:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_dacca_card(image_url, headline, source_name):
    card_width, card_height = 1080, 1350
    card = Image.new("RGB", (card_width, card_height), "#0B0C0E")
    draw = ImageDraw.Draw(card)

    font_path_en = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_path_bn = "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf"

    font_brand = ImageFont.truetype(font_path_bn if os.path.exists(font_path_bn) else font_path_en, 42)
    font_date = ImageFont.truetype(font_path_en, 24)
    font_headline = ImageFont.truetype(font_path_bn if is_bengali_text(headline) else font_path_en, 48)
    font_source = ImageFont.truetype(font_path_en, 22)

    # Top Brand Bar
    draw.text((60, 60), "DACCAখবর", font=font_brand, fill="#FFFFFF")
    date_str = datetime.utcnow().strftime("%d %b %Y").upper()
    draw.text((card_width - 240, 75), date_str, font=font_date, fill="#888888")

    # Headline Placement
    wrapped_lines = wrap_text(headline, font_headline, card_width - 120, draw)
    y_text = 140
    for line in wrapped_lines[:3]:
        draw.text((60, y_text), line, font=font_headline, fill="#FFFFFF")
        y_text += 65

    # Featured News Image Placement
    img_y = max(y_text + 40, 340)
    img_h = 860
    img_w = 960

    try:
        resp = requests.get(image_url, timeout=10)
        with open("temp_raw.jpg", "wb") as f:
            f.write(resp.content)
        raw_img = Image.open("temp_raw.jpg").convert("RGB")

        orig_w, orig_h = raw_img.size
        target_ratio = img_w / img_h
        orig_ratio = orig_w / orig_h

        if orig_ratio > target_ratio:
            new_w = int(orig_h * target_ratio)
            left = (orig_w - new_w) // 2
            raw_img = raw_img.crop((left, 0, left + new_w, orig_h))
        else:
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            raw_img = raw_img.crop((0, top, orig_w, top + new_h))

        raw_img = raw_img.resize((img_w, img_h), Image.Resampling.LANCZOS)
        card.paste(raw_img, (60, img_y))
    except Exception as e:
        print(f"Failed to fetch/process image: {e}")
        draw.rectangle([(60, img_y), (60 + img_w, img_y + img_h)], fill="#1E2022")

    # Footer Attribution
    draw.text((60, card_height - 65), f"VIA - {source_name}", font=font_source, fill="#AAAAAA")

    output_path = "output_card.jpg"
    card.save(output_path, quality=95)
    return output_path

def create_story_card(card_path):
    story_w, story_h = 1080, 1920
    card = Image.open(card_path).convert("RGB")

    bg = card.resize((story_w, story_h), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=45))

    darkener = Image.new("RGB", (story_w, story_h), "#000000")
    bg = Image.blend(bg, darkener, alpha=0.35)

    # Scale down card to float in story
    scale = 0.82
    cw, ch = int(card.width * scale), int(card.height * scale)
    scaled_card = card.resize((cw, ch), Image.Resampling.LANCZOS)

    mask = Image.new("L", (cw, ch), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (cw, ch)], radius=36, fill=255)

    pos_x = (story_w - cw) // 2
    pos_y = (story_h - ch) // 2 - 50
    bg.paste(scaled_card, (pos_x, pos_y), mask)

    draw = ImageDraw.Draw(bg)
    font_path_en = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_tag = ImageFont.truetype(font_path_en, 32)
    draw.text((pos_x + 10, pos_y + ch + 35), "@dacca.news", font=font_tag, fill="#E0E0E0")

    story_path = "output_story.jpg"
    bg.save(story_path, quality=95)
    return story_path

def post_facebook_feed(image_path, caption):
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos"
    with open(image_path, "rb") as img:
        payload = {
            "caption": caption,
            "access_token": ACCESS_TOKEN,
            "published": "true"
        }
        files = {"source": img}
        res = requests.post(url, data=payload, files=files, timeout=30).json()
        print("Facebook Feed Response:", res)
        return res

def post_facebook_comment(object_id, message):
    url = f"https://graph.facebook.com/v20.0/{object_id}/comments"
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
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photo_stories"
    with open(image_path, "rb") as img:
        payload = {"access_token": ACCESS_TOKEN}
        files = {"photo": img}
        res = requests.post(url, data=payload, files=files, timeout=30).json()
        print("Facebook Story Response:", res)
        return res

def get_meta_cdn_url(fb_photo_id):
    url = f"https://graph.facebook.com/v20.0/{fb_photo_id}?fields=images&access_token={ACCESS_TOKEN}"
    res = requests.get(url, timeout=15).json()
    if "images" in res and len(res["images"]) > 0:
        return res["images"][0]["source"]
    return None

def post_instagram_feed(cdn_url, caption):
    container_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": cdn_url,
        "caption": caption,
        "access_token": ACCESS_TOKEN
    }
    c_res = requests.post(container_url, data=payload, timeout=20).json()
    print("IG Feed Container Response:", c_res)
    creation_id = c_res.get("id")

    if creation_id:
        publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
        p_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}, timeout=20).json()
        print("Instagram Feed Publish Response:", p_res)
        return p_res
    return None

def post_instagram_story(story_cdn_url):
    container_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media"
    payload = {
        "image_url": story_cdn_url,
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN
    }
    c_res = requests.post(container_url, data=payload, timeout=20).json()
    print("IG Story Container Response:", c_res)
    creation_id = c_res.get("id")

    if creation_id:
        publish_url = f"https://graph.facebook.com/v20.0/{IG_USER_ID}/media_publish"
        p_res = requests.post(publish_url, data={"creation_id": creation_id, "access_token": ACCESS_TOKEN}, timeout=20).json()
        print("Instagram Story Publish Response:", p_res)
        return p_res
    return None

def publish_article(entry, source_name):
    img_url = extract_image_url(entry)
    if not img_url:
        return False

    summary = entry.get("summary", entry.title)
    headline = generate_text(entry.title, summary)

    card_path = create_dacca_card(img_url, headline, source_name)
    story_path = create_story_card(card_path)

    # Instagram caption remains strictly clean (headline only)
    ig_caption = headline

    # Facebook caption gets the comment CTA, and comment gets the link
    if is_bengali_text(headline):
        fb_caption = f"{headline}\n\n(বিস্তারিত প্রথম কমেন্টে)"
        comment_text = f"সম্পূর্ণ প্রতিবেদনটি পড়তে ভিজিট করুন:\n{entry.link}"
    else:
        fb_caption = f"{headline}\n\n(Details in the first comment)"
        comment_text = f"Read the full story here:\n{entry.link}"

    print(f"Dispatching {source_name} to Facebook Feed...")
    fb_res = post_facebook_feed(card_path, fb_caption)
    fb_photo_id = fb_res.get("id") if isinstance(fb_res, dict) else None
    fb_post_id = fb_res.get("post_id") or fb_photo_id

    # Post link in first comment only on Facebook
    if fb_post_id:
        post_facebook_comment(fb_post_id, comment_text)

    # Post Facebook Story
    print(f"Dispatching {source_name} to Facebook Story...")
    post_facebook_story(card_path)

    # Post Instagram Feed & Story via Meta CDN
    if fb_photo_id:
        print("Fetching Meta CDN URL for Instagram...")
        cdn_url = get_meta_cdn_url(fb_photo_id)
        if cdn_url:
            print("Posting to Instagram Feed...")
            post_instagram_feed(cdn_url, ig_caption)

        story_fb_upload = requests.post(
            f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos",
            data={"published": "false", "access_token": ACCESS_TOKEN},
            files={"source": open(story_path, "rb")},
            timeout=20
        ).json()
        story_photo_id = story_fb_upload.get("id")
        if story_photo_id:
            story_cdn_url = get_meta_cdn_url(story_photo_id)
            if story_cdn_url:
                print("Posting styled card to Instagram Story...")
                post_instagram_story(story_cdn_url)

    save_posted_url(entry.link)
    return True

def main():
    posted_urls = load_posted_urls()

    for category, feeds in FEEDS.items():
        article_posted = False
        for feed_url in feeds:
            feed = feedparser.parse(feed_url)
            source_name = feed.feed.get("title", category)

            for entry in feed.entries:
                if entry.link not in posted_urls:
                    if publish_article(entry, source_name):
                        article_posted = True
                        break
            if article_posted:
                break

if __name__ == "__main__":
    main()
