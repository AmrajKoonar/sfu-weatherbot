"""
Optional AI visual judgement for the SFU Weather Bot.

This is the SECOND (and optional) gate. It only runs after image_compare.py
already flagged a possible visual change. Here we ask a vision AI to look at the
previous vs current image of the most-changed camera and decide whether the
change is actually weather/road related (snow, rain, fog, ice, visibility...) or
just normal variation (lighting, cars, shadows, compression).

This whole module is optional:
  - If ENABLE_AI_JUDGEMENT is false, the bot never calls this.
  - If it's true but VISION_AI_API_KEY is missing, we warn and skip.

By default this uses the OpenAI vision API (gpt-4o-mini). The import is lazy so
the bot still runs fine when AI is disabled and the package isn't installed.
"""

import base64
import json
import os

# Model used for vision judgement. Small + cheap is fine for this task.
AI_MODEL = "gpt-4o-mini"

# A safe answer to return whenever AI can't / shouldn't make a call.
_NO_CHANGE_FALLBACK = {
    "changed": False,
    "confidence": 0.0,
    "change_type": "none",
    "reason": "AI judgement was not available, so no visual change was confirmed.",
    "caption": "No noticeable visual weather change detected.",
    "best_camera": None,
    "best_image_path": None,
}

_SYSTEM_PROMPT = (
    "You are a careful assistant that compares two webcam images from the SAME "
    "camera (a previous image and a current image) at SFU Burnaby campus. Decide "
    "whether there is a MEANINGFUL weather, visibility, or road condition change. "
    "Only mark changed=true for visible weather/road changes such as snow, rain, "
    "fog, ice, flooding, or clearly reduced visibility. Mark changed=false for "
    "normal daylight changes, camera exposure shifts, parked or moving cars, "
    "pedestrians, shadows, small compression artifacts, or tiny scene "
    "differences. Use cautious wording: prefer 'Visible conditions appear to have "
    "changed' over 'The weather has changed'. "
    "Respond ONLY with a JSON object using these exact keys: changed (bool), "
    "confidence (0..1 number), change_type (string), reason (string), "
    "caption (string)."
)


def is_ai_enabled():
    """True if the user turned AI judgement on via ENABLE_AI_JUDGEMENT."""
    return os.getenv("ENABLE_AI_JUDGEMENT", "false").strip().lower() == "true"


def _encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _pick_best_camera(changed_camera_results):
    """Pick the camera with the largest difference score to send to the AI."""
    return max(changed_camera_results, key=lambda r: r["difference_score"])


def judge_visual_weather_change(changed_camera_results, weather_info, current_update):
    """Ask the AI whether a flagged visual change is weather/road related.

    Args:
        changed_camera_results: list of result dicts from compare_image_sets
            (only the cameras that were flagged as possibly changed).
        weather_info: the current SFU weather sentence (extra context for the AI).
        current_update: the current official SFU road update text (more context).

    Returns a structured dict (see _NO_CHANGE_FALLBACK for the shape).
    """
    if not changed_camera_results:
        return dict(_NO_CHANGE_FALLBACK)

    api_key = os.getenv("VISION_AI_API_KEY")
    if not api_key:
        print("WARNING: ENABLE_AI_JUDGEMENT is on but VISION_AI_API_KEY is missing. Skipping AI judgement.")
        return dict(_NO_CHANGE_FALLBACK)

    best = _pick_best_camera(changed_camera_results)

    try:
        # Lazy import so the bot runs without the openai package when AI is off.
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        previous_b64 = _encode_image(best["previous_path"])
        current_b64 = _encode_image(best["current_path"])

        user_text = (
            f"Camera: {best['camera']}\n"
            f"Image difference score (0=identical): {best['difference_score']}\n"
            f"Current SFU weather text: {weather_info}\n"
            f"Current SFU road update: {current_update}\n"
            "The first image is the PREVIOUS one, the second is the CURRENT one."
        )

        response = client.chat.completions.create(
            model=AI_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{previous_b64}"}},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{current_b64}"}},
                    ],
                },
            ],
        )

        data = json.loads(response.choices[0].message.content)

        # Attach which camera/image the decision was about so the bot can tweet it.
        result = {
            "changed": bool(data.get("changed", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "change_type": data.get("change_type", "none"),
            "reason": data.get("reason", ""),
            "caption": data.get("caption", "Visible conditions at SFU Burnaby appear to have changed."),
            "best_camera": best["camera"] if data.get("changed") else None,
            "best_image_path": best["current_path"] if data.get("changed") else None,
        }
        return result

    except Exception as error:
        print(f"AI judgement failed, treating as no change: {error}")
        return dict(_NO_CHANGE_FALLBACK)
