import cv2
import numpy as np

img1 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-1.jpeg")
img2 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-2.jpeg")
img3 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-3.jpeg")
img4 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-4.jpeg")

# Convert to grayscale
gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
gray3 = cv2.cvtColor(img3, cv2.COLOR_BGR2GRAY)
gray4 = cv2.cvtColor(img4, cv2.COLOR_BGR2GRAY)

# Storefront region in 2560x1440: y: 500..1150, x: 500..2100
warp_mode = cv2.MOTION_TRANSLATION
criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-6)

for name, target_gray, target_img in [("img2", gray2, img2), ("img3", gray3, img3), ("img4", gray4, img4)]:
    warp_matrix = np.eye(2, 3, dtype=np.float32)
    # Mask storefront and street (exclude clouds which move naturally)
    mask = np.zeros(gray1.shape, dtype=np.uint8)
    mask[550:1100, 500:2100] = 255
    try:
        cc, warp_matrix = cv2.findTransformECC(gray1, target_gray, warp_matrix, warp_mode, criteria, inputMask=mask)
        print(f"ECC alignment for {name}: cc={cc:.4f}, tx={warp_matrix[0,2]:.2f}, ty={warp_matrix[1,2]:.2f}")
    except Exception as e:
        print(f"ECC error for {name}: {e}")
