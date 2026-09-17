import os
import time
import json
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 1. Structured Output Schema for Gemini
class WellnessPost(BaseModel):
    myth: str = Field(description="A common sexual wellness myth in India. Keep it under 20 words.")
    fact: str = Field(description="The scientific fact debunking the myth. Keep it clinical and under 25 words.")
    caption: str = Field(description="An empathetic, educational Instagram caption with emojis and hashtags.")

# Rotate through these so consecutive posts don't circle the same ground.
TOPIC_CATEGORIES = [
    "menstrual health",
    "fertility and conception",
    "contraception",
    "reproductive anatomy",
    "safe sex and STI prevention",
    "emotional and relationship intimacy",
    "pregnancy and postpartum health",
    "general sexual wellness and hygiene",
]

STATE_PATH = "posted_topics.json"       # lives in the repo, tracks history across runs
GRAPH_API_VERSION = "v19.0"
BRAND_HANDLE = os.getenv("BRAND_HANDLE", "@wellness_guider")


# ---------------------------------------------------------------------------
# GitHub Contents API helpers — used both as image hosting (Instagram needs a
# public https:// URL, it can't accept a file upload) and as tiny persistent
# storage (GitHub Actions runs are stateless, so "what have we already
# posted" has to live somewhere outside the runner).
# ---------------------------------------------------------------------------

def _github_headers():
    return {
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
    }


def github_get_file(path):
    """Returns (content_bytes, sha) or (None, None) if the file doesn't exist yet."""
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_BRANCH", "main")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    response = requests.get(url, headers=_github_headers(), params={"ref": branch})
    if response.status_code == 200:
        data = response.json()
        return base64.b64decode(data["content"]), data["sha"]
    return None, None


def github_put_file(path, content_bytes, message, sha=None):
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_BRANCH", "main")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(url, headers=_github_headers(), json=payload)
    response.raise_for_status()
    return response.json()


def upload_image_to_github(image_path):
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    repo_path = f"posts/{timestamp}.jpg"
    github_put_file(repo_path, image_bytes, f"Add generated post image {timestamp}")
    repo = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_BRANCH", "main")
    # Give GitHub's raw CDN a moment to catch up before Instagram tries to fetch it.
    time.sleep(5)
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{repo_path}"


def load_state():
    content, sha = github_get_file(STATE_PATH)
    if content is None:
        return {"used_myths": [], "category_index": 0}, None
    return json.loads(content), sha


def save_state(state, sha):
    body = json.dumps(state, indent=2).encode("utf-8")
    github_put_file(STATE_PATH, body, "Update posted topics log", sha=sha)


# 2. The Internal Brain (Google Gemini)
def generate_ai_content(api_key, avoid_list, category):
    client = genai.Client(api_key=api_key)
    avoid_text = ""
    if avoid_list:
        avoid_text = " Do not repeat any of these already-covered myths: " + "; ".join(avoid_list) + "."

    prompt = (
        "You are an expert, empathetic sexual wellness educator in India. "
        f"Generate a 'Myth vs. Fact' post focused specifically on the topic of {category}. "
        "The tone must be strictly clinical, educational, and respectful. Avoid explicit language. "
        "Focus on science and breaking taboos." + avoid_text
    )

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=WellnessPost,
            temperature=0.9,
        ),
    )
    return json.loads(response.text)


# 3. Visual Designer (Pillow)
def _wrap_to_width(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_image(myth_text, fact_text):
    W, H = 1080, 1080
    BG = (250, 247, 240)
    HEADER_BG = (124, 152, 133)     # sage green
    MYTH_COLOR = (196, 91, 91)      # muted coral/red
    FACT_COLOR = (74, 124, 98)      # deep sage/teal-green
    TEXT_DARK = (51, 51, 51)

    img = Image.new('RGB', (W, H), color=BG)
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("Roboto-Bold.ttf", 54)
        font_label = ImageFont.truetype("Roboto-Bold.ttf", 38)
        font_body = ImageFont.truetype("Roboto-Regular.ttf", 42)
        font_handle = ImageFont.truetype("Roboto-Regular.ttf", 30)
    except IOError:
        print("Error: Font files missing.")
        return None

    # Header bar
    draw.rectangle([0, 0, W, 150], fill=HEADER_BG)
    title = "MYTH vs FACT"
    tw = draw.textlength(title, font=font_title)
    draw.text(((W - tw) / 2, 45), title, fill=(255, 255, 255), font=font_title)

    def draw_block(y_top, label, label_color, body_text):
        pad_x, pad_y = 26, 12
        lw = draw.textlength(label, font=font_label)
        draw.rounded_rectangle(
            [80, y_top, 80 + lw + pad_x * 2, y_top + 38 + pad_y * 2],
            radius=22, fill=label_color,
        )
        draw.text((80 + pad_x, y_top + pad_y), label, fill=(255, 255, 255), font=font_label)

        y = y_top + 38 + pad_y * 2 + 28
        for line in _wrap_to_width(draw, body_text, font_body, W - 160):
            draw.text((80, y), line, fill=TEXT_DARK, font=font_body)
            y += font_body.size + 14
        return y

    y = draw_block(210, "MYTH", MYTH_COLOR, myth_text)
    draw_block(y + 60, "FACT", FACT_COLOR, fact_text)

    draw.line([80, H - 100, W - 80, H - 100], fill=(220, 216, 205), width=2)
    draw.text((80, H - 75), BRAND_HANDLE, fill=(150, 150, 150), font=font_handle)

    image_path = "daily_post.jpg"
    img.save(image_path, quality=95)
    return image_path


# 4. Publisher (Meta Graph API)
def publish_to_instagram(ig_user_id, access_token, image_url, caption):
    container_url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/media"
    container_payload = {'image_url': image_url, 'caption': caption, 'access_token': access_token}

    creation_id = None
    container_response = {}
    for attempt in range(3):
        container_response = requests.post(container_url, data=container_payload).json()
        creation_id = container_response.get('id')
        if creation_id:
            break
        print(f"Attempt {attempt + 1}: container creation failed, retrying in 5s...", container_response)
        time.sleep(5)

    if not creation_id:
        print("Failed to create container after retries:", container_response)
        return

    publish_url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish"
    publish_payload = {'creation_id': creation_id, 'access_token': access_token}
    publish_response = requests.post(publish_url, data=publish_payload).json()
    print("Published successfully! ID:", publish_response.get('id'))


if __name__ == "__main__":
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    IG_USER_ID = os.getenv("IG_USER_ID")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")

    print("Loading topic history...")
    state, state_sha = load_state()
    category = TOPIC_CATEGORIES[state["category_index"] % len(TOPIC_CATEGORIES)]

    print(f"Brainstorming with Gemini (topic: {category})...")
    content = generate_ai_content(GEMINI_API_KEY, state["used_myths"][-30:], category)

    print("Generating image...")
    img_path = generate_image(content["myth"], content["fact"])

    if img_path:
        print("Uploading image to GitHub...")
        public_url = upload_image_to_github(img_path)

        # Inject the Comment-to-DM Sales Funnel CTA
        caption_with_cta = content["caption"] + "\n\nWant the full guide on unlearning intimacy myths? Comment the word MYTH below and I will DM it to you for free!"

        print("Publishing to Instagram...")
        publish_to_instagram(IG_USER_ID, IG_ACCESS_TOKEN, public_url, caption_with_cta)

        state["used_myths"] = (state["used_myths"] + [content["myth"]])[-30:]
        state["category_index"] = (state["category_index"] + 1) % len(TOPIC_CATEGORIES)
        save_state(state, state_sha)
