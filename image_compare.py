"""
Cheap image comparison for the SFU Weather Bot.

This is the FIRST gate before we ever ask an AI. We compare each camera against
its OWN previous image using SSIM (structural similarity). SSIM is fast and good
at ignoring tiny compression noise while still noticing real scene changes.

difference_score = 1 - SSIM
  - 0.0  means the two images are basically identical
  - higher means more different

If the score is above IMAGE_DIFF_THRESHOLD we mark the camera as
"possibly_changed" so the more expensive AI step can take a closer look.
"""

import cv2
from skimage.metrics import structural_similarity as ssim

# How different two images must be before we consider it a "possible" change.
# Kept low-ish so we don't miss real changes, but not so low that lighting noise
# triggers it. The AI step (or a stricter threshold) is the real decision maker.
IMAGE_DIFF_THRESHOLD = 0.12

# Images are resized to this size before comparison so different sizes still work
# and the comparison stays fast.
COMPARE_SIZE = (256, 256)


def _load_gray(path):
    """Load an image as grayscale and resize it. Returns None if unreadable."""
    image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return cv2.resize(image, COMPARE_SIZE)


def _difference_score(previous_path, current_path):
    """Return a 0..1 difference score, or None if either image can't be read."""
    previous = _load_gray(previous_path)
    current = _load_gray(current_path)
    if previous is None or current is None:
        return None

    similarity = ssim(previous, current)
    # Clamp to [0, 1] just in case of tiny floating point overshoot.
    return max(0.0, min(1.0, 1.0 - similarity))


def compare_image_sets(previous_images, current_images):
    """Compare matching cameras between two image sets.

    Inputs are dicts of {camera_name: image_path}. Only cameras present in BOTH
    sets are compared (we never compare one camera against a different camera).

    Returns:
        {
            "any_possible_change": bool,
            "changed_cameras": [ ...results above threshold... ],
            "all_results": [ ...every compared camera... ],
        }
    """
    all_results = []
    changed_cameras = []

    for camera, current_path in current_images.items():
        previous_path = previous_images.get(camera)
        if previous_path is None:
            # No previous image for this camera yet, nothing to compare against.
            continue

        score = _difference_score(previous_path, current_path)
        if score is None:
            # One of the images was unreadable; skip it rather than guessing.
            continue

        possibly_changed = score > IMAGE_DIFF_THRESHOLD
        result = {
            "camera": camera,
            "previous_path": previous_path,
            "current_path": current_path,
            "difference_score": round(score, 4),
            "possibly_changed": possibly_changed,
        }
        all_results.append(result)
        if possibly_changed:
            changed_cameras.append(result)

    return {
        "any_possible_change": len(changed_cameras) > 0,
        "changed_cameras": changed_cameras,
        "all_results": all_results,
    }
