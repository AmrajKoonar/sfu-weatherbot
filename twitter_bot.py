"""
SFU Weather Bot - main entry point.

What it does each cycle (every 30 minutes):
  1. Reads the official SFU road update text + weather sentence.
  2. Downloads the live SFU webcam images.
  3. Compares each webcam against its OWN previous image (cheap SSIM check).
  4. Optionally asks an AI whether a flagged visual change is really weather/road
     related.
  5. Tweets ONLY when something meaningful actually changed.

Run it with DRY_RUN=true (see .env.example) to test safely without posting.
"""

import os
import shutil
import time
from datetime import datetime

import tweepy
from dotenv import load_dotenv

import ai_judge
from image_compare import compare_image_sets
from webscrape import download_images, get_update, get_weather_info

load_dotenv()

# --- Folder layout ---------------------------------------------------------
DATA_DIR = "data"
CURRENT_DIR = os.path.join(DATA_DIR, "current_images")
PREVIOUS_DIR = os.path.join(DATA_DIR, "previous_images")
DEBUG_DIR = os.path.join(DATA_DIR, "debug")

# --- Behaviour settings ----------------------------------------------------
# True  -> never post real tweets, just print what we would have tweeted.
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

# How long to wait between cycles (30 minutes).
SLEEP_SECONDS = 1800

# Max caption length we allow. Twitter/X allows 280; we leave a little buffer.
MAX_CAPTION_LENGTH = 275

# When AI judgement is OFF, only an image difference this large counts as a
# "clear" visual change worth tweeting. Stricter than IMAGE_DIFF_THRESHOLD so we
# don't tweet on borderline differences without AI confirmation.
IMAGE_DIFF_STRICT_THRESHOLD = 0.25


def ensure_folders():
    """Create the data folders so the bot works on a fresh clone."""
    for folder in (CURRENT_DIR, PREVIOUS_DIR, DEBUG_DIR):
        os.makedirs(folder, exist_ok=True)


def build_twitter_clients():
    """Build the tweepy clients from environment variables.

    Returns (client, api). Exits if required credentials are missing (only called
    when we actually intend to post, i.e. not in DRY_RUN).
    """
    api_key = os.getenv("TWITTER_API_KEY")
    api_secret = os.getenv("TWITTER_API_SECRET")
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    missing = [
        name
        for name, value in {
            "TWITTER_API_KEY": api_key,
            "TWITTER_API_SECRET": api_secret,
            "TWITTER_BEARER_TOKEN": bearer_token,
            "TWITTER_ACCESS_TOKEN": access_token,
            "TWITTER_ACCESS_SECRET": access_secret,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing Twitter credentials: "
            + ", ".join(missing)
            + ". Set them in your .env file, or use DRY_RUN=true to test."
        )

    client = tweepy.Client(bearer_token, api_key, api_secret, access_token, access_secret)
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
    api = tweepy.API(auth, wait_on_rate_limit=True)
    return client, api


# --- Caption helpers -------------------------------------------------------

weather_prefixes = {
    "very hot": "🌡️ It's a scorching hot day at SFU — stay hydrated! 🌡️",
    "sunny": "☀️ It's a bright and sunny day at SFU ☀️",
    "heavy snow": "🚨❄️ Extreme weather alert! It's heavy snow at SFU! ❄️🚨",
    "rain": "🌧️ Don't forget your umbrella — it's rainy at SFU 🌧️",
    "snow": "❄️ Winter wonderland alert! It's snowing at SFU ❄️",
    "wind": "💨 Hold on to your hats — it's windy at SFU! 💨",
}


def extract_temperature(weather_info):
    """Return the temperature as a float, or None.

    Handles formats like "27°C", "4.5°C", and "-3°C".
    """
    import re

    match = re.search(r"(-?\d+(?:\.\d+)?)\s*°C", weather_info)
    if match:
        return float(match.group(1))
    return None


def get_weather_prefix(weather_info):
    """Pick a friendly emoji prefix based on the weather sentence."""
    temp = extract_temperature(weather_info)
    if temp is not None and temp > 25:
        return weather_prefixes["very hot"]

    priorities = ["heavy snow", "rain", "snow", "wind", "sunny"]
    weather_lower = weather_info.lower()
    for keyword in priorities:
        if keyword in weather_lower:
            return weather_prefixes[keyword]
    return "☁️ Here's the latest weather update from SFU ☁️"


def truncate_caption(text, max_length=MAX_CAPTION_LENGTH):
    """Trim a caption so it never exceeds the tweet length limit."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


# --- Tweeting --------------------------------------------------------------

def post_tweet_with_multiple_images_thread(client, api, image_paths, first_caption, thread_caption):
    """Post a tweet (or a thread, if more than 4 images) with images attached.

    - Only existing image files are uploaded (never stale/missing files).
    - Respects DRY_RUN: when on, nothing is posted; we just print the plan.
    """
    # Keep only images that actually exist on disk so we never tweet stale paths.
    existing = [p for p in image_paths if p and os.path.exists(p)]

    if DRY_RUN:
        print("[DRY_RUN] Would post tweet:")
        print(f"  caption: {first_caption}")
        print(f"  images ({len(existing)}): {existing}")
        if len(existing) > 4:
            print(f"  thread caption for extra images: {thread_caption}")
        return True

    if not existing:
        # Text-only tweet (used for official text changes with no images).
        client.create_tweet(text=first_caption)
        print("Posted text-only tweet.")
        return True

    try:
        chunks = [existing[i:i + 4] for i in range(0, len(existing), 4)]
        previous_tweet_id = None

        for i, chunk in enumerate(chunks):
            media_ids = [api.media_upload(path).media_id for path in chunk]
            text = first_caption if i == 0 else thread_caption

            if i == 0:
                response = client.create_tweet(text=text, media_ids=media_ids)
            else:
                response = client.create_tweet(
                    text=text, media_ids=media_ids, in_reply_to_tweet_id=previous_tweet_id
                )
            previous_tweet_id = response.data["id"]

        print("Tweet (thread) posted successfully!")
        return True
    except Exception as error:
        print(f"An error occurred while posting: {error}")
        return False


# --- Baseline management ---------------------------------------------------

def update_baseline(previous_images, current_images):
    """Copy successfully downloaded current images into the previous baseline.

    Cameras that failed to download this cycle keep their OLD baseline, so we
    never lose a good reference image because of one bad download.
    """
    new_previous = dict(previous_images)
    for camera, current_path in current_images.items():
        destination = os.path.join(PREVIOUS_DIR, f"{camera}.jpg")
        try:
            shutil.copyfile(current_path, destination)
            new_previous[camera] = destination
        except Exception as error:
            print(f"Could not update baseline for {camera}: {error}")
    return new_previous


# --- Main loop -------------------------------------------------------------

def main():
    ensure_folders()

    ai_enabled = ai_judge.is_ai_enabled()
    client, api = (None, None) if DRY_RUN else build_twitter_clients()

    print("Bot started on branch ai-image-change-detection.")
    print(f"DRY_RUN: {DRY_RUN} | AI judgement enabled: {ai_enabled}")

    # Build the very first baseline before the loop starts.
    previous_update = get_update()
    previous_images = download_images(PREVIOUS_DIR)
    print(f"Baseline update: {previous_update}")
    print(f"Baseline images: {len(previous_images)}")

    while True:
        current_time = datetime.now()
        time_str = current_time.strftime("%I:%M %p").lstrip("0")
        time_line = f"Current time: {time_str}"

        current_update = get_update()
        weather_info = get_weather_info()
        current_images = download_images(CURRENT_DIR)

        text_changed = current_update != previous_update
        image_compare_result = compare_image_sets(previous_images, current_images)

        print(f"Current update: {current_update}")
        print(f"Text changed: {text_changed}")
        print(f"Downloaded {len(current_images)} current images.")
        scores = [f"{r['camera']}={r['difference_score']}" for r in image_compare_result["all_results"]]
        print(f"Image comparison scores: {scores}")
        print(f"Possible visual changes: {len(image_compare_result['changed_cameras'])}")

        # --- Tweet decision logic --------------------------------------------
        tweeted = False

        if text_changed:
            # 1) Official SFU text changed -> always worth tweeting.
            prefix = get_weather_prefix(weather_info)
            caption = truncate_caption(
                f"{prefix}\n\n{weather_info}\nSFU update: {current_update}\n\n{time_line}"
            )
            thread_caption = "Additional live SFU webcam updates: 📸"
            image_paths = list(current_images.values())
            print("Decision: tweeting (official SFU text update changed).")
            tweeted = post_tweet_with_multiple_images_thread(
                client, api, image_paths, caption, thread_caption
            )

        elif image_compare_result["any_possible_change"]:
            # 2) Images look possibly different. Decide based on AI or strict score.
            if ai_enabled:
                print("AI judgement running...")
                judgement = ai_judge.judge_visual_weather_change(
                    image_compare_result["changed_cameras"], weather_info, current_update
                )
                print(
                    f"AI judgement: changed={judgement['changed']}, "
                    f"reason={judgement['reason']}"
                )
                if judgement["changed"]:
                    caption = truncate_caption(
                        f"📷 {judgement['caption']}\n\n{time_line}"
                    )
                    image_paths = [judgement["best_image_path"]]
                    print("Decision: tweeting (AI confirmed a meaningful visual change).")
                    tweeted = post_tweet_with_multiple_images_thread(
                        client, api, image_paths, caption, caption
                    )
                else:
                    print("Decision: skipped tweet (AI said change is not weather/road related).")
            else:
                # AI disabled: only tweet if the difference is clearly large.
                clear_changes = [
                    r for r in image_compare_result["changed_cameras"]
                    if r["difference_score"] >= IMAGE_DIFF_STRICT_THRESHOLD
                ]
                if clear_changes:
                    caption = truncate_caption(
                        "📷 Visible conditions at SFU Burnaby appear to have changed.\n\n"
                        f"{weather_info}\n\n{time_line}"
                    )
                    image_paths = [r["current_path"] for r in clear_changes]
                    print("Decision: tweeting (clear image change, AI disabled).")
                    tweeted = post_tweet_with_multiple_images_thread(
                        client, api, image_paths, caption, caption
                    )
                else:
                    print("Decision: skipped tweet (image change below strict threshold, AI disabled).")
        else:
            print("Decision: skipped tweet (no text change and webcams look similar).")

        if tweeted:
            print("Tweet step finished.")

        # Update the baseline AFTER the decision, so the next cycle compares
        # against the most recent images.
        previous_images = update_baseline(previous_images, current_images)
        previous_update = current_update

        print(f"Twitter Bot Status: ACTIVE | Time: {time_str} | DRY_RUN: {DRY_RUN}")
        print("-" * 60)
        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
