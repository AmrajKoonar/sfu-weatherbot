# 🌩️ SFU Weather Bot

A Python Twitter/X bot that watches conditions at **SFU Burnaby campus** and posts
updates **only when something meaningful actually changes**. Built by
**Amraj Koonar** and **Amar Koonar**.

The bot:

- 📝 Scrapes the official **SFU road condition text** from the
  [SFU Road Conditions Page](https://www.sfu.ca/security/sfuroadconditions/).
- 📷 Downloads the **live SFU webcam images**.
- 🔍 Compares each current webcam image against its **own previous image** using a
  cheap computer-vision check (SSIM).
- 🤖 Optionally uses **AI vision judgement** to decide whether a visible change is
  really weather/road related (snow, rain, fog, ice, visibility) and not just
  lighting, cars, or shadows.
- 🐦 Tweets to **Twitter/X** only when conditions meaningfully change.

---

## 🔗 Links

- 📡 **Live Bot**: [@sfulivewebcams on Twitter/X](https://x.com/sfulivewebcams)
- 🌐 **Data Source**: [SFU Security Road Conditions](https://www.sfu.ca/security/sfuroadconditions/)

---

## 🛠️ Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/sfu-weatherbot.git
cd sfu-weatherbot
```

### 2. Create a virtual environment (optional)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env            # Windows: copy .env.example .env
```

```env
TWITTER_API_KEY=your_key_here
TWITTER_API_SECRET=your_secret_here
TWITTER_BEARER_TOKEN=your_bearer_token_here
TWITTER_ACCESS_TOKEN=your_access_token_here
TWITTER_ACCESS_SECRET=your_access_secret_here

WEATHER_API_KEY=optional_weather_api_key_here
VISION_AI_API_KEY=optional_vision_ai_key_here

ENABLE_AI_JUDGEMENT=false
DRY_RUN=true
```

> Note: `keys_test.py` is **no longer used**. All secrets now come from `.env`.

### 5. Run the bot

```bash
python twitter_bot.py
```

---

## 🤖 Optional AI Judgement

AI visual judgement is **off by default** (`ENABLE_AI_JUDGEMENT=false`).

- When **disabled**, the bot relies only on the image comparison score (plus the
  official SFU text). It only tweets on a text change or a clearly large image
  difference.
- When **enabled** (`ENABLE_AI_JUDGEMENT=true`), the bot asks a vision AI to
  confirm whether a flagged image change is weather/road related before tweeting.
  This needs a `VISION_AI_API_KEY`. If the key is missing, the bot prints a
  warning and simply skips the AI step.

---

## 🧠 How Tweet Decisions Work

The bot **tweets** when:

- The official SFU road update **text changes**, **or**
- The webcam images **visibly change** *and*:
  - AI confirms the change is weather/road related (when AI is enabled), or
  - the image difference is clearly large (when AI is disabled).

The bot **skips tweeting** when:

- There is no official text change **and** the webcams look similar, or
- AI decides the visual difference is just lighting, cars, shadows, or normal
  camera variation.

On the **first run** there is no previous image to compare against, so the bot
saves the current images as a baseline and won't post a visual-change tweet
unless the SFU text update changed.

---

## 🧪 Testing Without Posting (DRY_RUN)

Set `DRY_RUN=true` in your `.env` to test safely. In dry-run mode the bot does
**not** post anything to Twitter/X — it just prints what it *would* have tweeted,
downloads the webcam images, and logs its decision.

```bash
# In .env:
DRY_RUN=true
ENABLE_AI_JUDGEMENT=false

python twitter_bot.py
```

Manual test cases:

1. **First run (no previous images):** saves a baseline, skips visual tweet
   unless the text update changed.
2. **Second run, same images:** skips tweeting.
3. **Second run, obviously different image:** detects a possible image change.
4. **AI disabled:** only tweets on a text change or a very large image difference.
5. **AI enabled:** only tweets a visual change if AI confirms it is weather/road
   related.

---

## 🗂️ Project Structure

```
twitter_bot.py     # main loop + tweet decision logic
webscrape.py       # scrape SFU text + download webcam images
image_compare.py   # SSIM comparison of current vs previous images
ai_judge.py        # optional AI vision judgement
data/
  current_images/  # latest downloaded webcams (gitignored)
  previous_images/ # baseline for comparison (gitignored)
  debug/           # scratch space (gitignored)
```

---

## 🧰 Tech Stack

- **Language**: Python
- **Libraries**: BeautifulSoup, Tweepy, Requests, Pillow, OpenCV, scikit-image,
  python-dotenv (and OpenAI when AI judgement is enabled)
- **Output Platform**: Twitter/X

---

## 📄 License

Open-source under the [MIT License](LICENSE), for educational and informational
use only.
