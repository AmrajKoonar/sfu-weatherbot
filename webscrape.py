"""
Scraping helpers for the SFU Weather Bot.

This module knows how to:
  - read the official SFU Burnaby road conditions text
  - download the live SFU webcam images
  - (optionally) look up the current temperature from WeatherAPI

Everything here is written to "fail soft": if SFU changes their page or a
download fails, we return a safe fallback instead of crashing the whole bot.
"""

import io
import os

import requests
from bs4 import BeautifulSoup
from PIL import Image

# How long (in seconds) to wait on any network request before giving up.
# This stops the bot from hanging forever if SFU or the webcam server is slow.
REQUEST_TIMEOUT = 15

SFU_ROAD_CONDITIONS_URL = "https://www.sfu.ca/security/sfuroadconditions/"

# Camera name -> live image URL.
# The key is also used as the saved file name, so each camera always maps to the
# same file. That lets us compare a camera against its OWN previous image later.
IMAGE_URLS = {
    "img_url_AQ_North": "https://ns-webcams.its.sfu.ca/public/images/aqn-current.jpg",
    "img_url_AQ_SouthWest": "https://ns-webcams.its.sfu.ca/public/images/aqsw-current.jpg",
    "img_url_AQ_SouthEast": "https://ns-webcams.its.sfu.ca/public/images/aqse-current.jpg",
    "img_url_Gaglardi_intersection": "https://ns-webcams.its.sfu.ca/public/images/gaglardi-current.jpg",
    "img_url_Tower_Road_North": "https://ns-webcams.its.sfu.ca/public/images/towern-current.jpg",
    "img_url_Tower_Road_South": "https://ns-webcams.its.sfu.ca/public/images/towers-current.jpg",
    "img_url_University_Drive_North": "https://ns-webcams.its.sfu.ca/public/images/udn-current.jpg",
    "img_url_Blusson_Hall_Roof": "https://ns-webcams.its.sfu.ca/public/images/wmcroof-current.jpg",
}


def get_weather_api_info(city):
    """Return a short temperature string like "4.5°C" using WeatherAPI.

    The API key is read from the WEATHER_API_KEY environment variable.
    Returns a safe fallback string if the key is missing or the call fails.
    """
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        return "Weather information is currently unavailable."

    try:
        url = f"http://api.weatherapi.com/v1/current.json?key={api_key}&q={city}&aqi=no"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        temperature = data["current"]["temp_c"]
        return f"{temperature}°C"
    except Exception as error:
        print(f"WeatherAPI lookup failed: {error}")
        return "Weather information is currently unavailable."


def get_weather_info():
    """Return the "It is currently ..." weather sentence from the SFU page.

    Falls back to a friendly message if the expected text cannot be found or the
    page layout changes.
    """
    try:
        response = requests.get(SFU_ROAD_CONDITIONS_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as error:
        print(f"Could not load SFU page for weather info: {error}")
        return "Weather information is currently unavailable."

    soup = BeautifulSoup(response.text, "html.parser")
    div_contents = soup.find_all("div", class_="text parbase section")

    for div in div_contents:
        p_tag = div.find("p")
        if p_tag:
            text = " ".join(p_tag.get_text().split()).strip()
            if "It is currently" in text:
                return text

    return "Weather information is currently unavailable."


def get_update():
    """Return the latest official SFU road update text (the grey block).

    Returns a safe fallback string if the block is missing or the page changed.
    """
    try:
        response = requests.get(SFU_ROAD_CONDITIONS_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as error:
        print(f"Could not load SFU page for road update: {error}")
        return "No official SFU road update found."

    soup = BeautifulSoup(response.text, "html.parser")
    current = soup.find("div", class_="block grey")
    if current is None:
        return "No official SFU road update found."

    lines = current.text.split("\n")
    update = lines[1].strip() if len(lines) > 1 else None
    return update if update else "No official SFU road update found."


def download_images(target_dir, image_urls=None):
    """Download all webcam images into ``target_dir``.

    Returns a dictionary of {camera_name: saved_file_path} for the images that
    downloaded successfully. Cameras that fail are simply left out, so the caller
    can tell exactly which live images are actually available.
    """
    if image_urls is None:
        image_urls = IMAGE_URLS

    os.makedirs(target_dir, exist_ok=True)
    downloaded = {}

    for filename, url in image_urls.items():
        try:
            response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            # Validate it is a real image before saving (avoids saving error pages).
            img = Image.open(io.BytesIO(response.content)).convert("RGB")

            file_path = os.path.join(target_dir, f"{filename}.jpg")
            img.save(file_path, "JPEG")

            downloaded[filename] = file_path
            print(f"Downloaded: {filename}")
        except Exception as error:
            print(f"Failed to download {filename} from {url}: {error}")

    return downloaded
