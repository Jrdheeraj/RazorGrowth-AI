import cv2
import numpy as np

# Compare gemini-layer-1..4 with original images in _originals
orig1 = cv2.imread(r"frontend/src/assets/illustrations/_originals/Home-page-image-1.jpeg")
orig2 = cv2.imread(r"frontend/src/assets/illustrations/_originals/Home-page-image-2.jpeg")
orig3 = cv2.imread(r"frontend/src/assets/illustrations/_originals/Home-page-image-3.jpeg")
orig4 = cv2.imread(r"frontend/src/assets/illustrations/_originals/Home-page-image-4.jpeg")

gem1 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-1.jpeg")
gem2 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-2.jpeg")
gem3 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-3.jpeg")
gem4 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-4.jpeg")

print("Orig1 shape:", orig1.shape if orig1 is not None else None)
print("Gem1 shape:", gem1.shape if gem1 is not None else None)

# If orig1 is 1600x900 and gem1 is 2560x1440, resize gem1 to 1600x900 and check diff
if orig1 is not None and gem1 is not None:
    gem1_resized = cv2.resize(gem1, (orig1.shape[1], orig1.shape[0]))
    diff1 = np.mean(np.abs(orig1.astype(float) - gem1_resized.astype(float)))
    print("Diff orig1 vs gem1:", diff1)

if orig2 is not None and gem2 is not None:
    gem2_resized = cv2.resize(gem2, (orig2.shape[1], orig2.shape[0]))
    diff2 = np.mean(np.abs(orig2.astype(float) - gem2_resized.astype(float)))
    print("Diff orig2 vs gem2:", diff2)
