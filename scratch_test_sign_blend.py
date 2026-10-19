import cv2
import numpy as np

morn = cv2.imread(r"frontend/src/assets/illustrations/gemini-morning.jpeg")
mid = cv2.imread(r"frontend/src/assets/illustrations/gemini-midday.jpeg")

# Test 50/50 blend in the sign region
crop_morn = morn[620:740, 720:1100]
crop_mid = mid[620:740, 720:1100]

blend_raw = cv2.addWeighted(crop_morn, 0.5, crop_mid, 0.5, 0)
cv2.imwrite("test_sign_blend_raw.png", blend_raw)

# If we replace the sign text plate in mid with morn (since the background color of the sign plate is cream in both):
# In morn, sign plate is y: 627..730, x: 735..1075
mid_fixed = mid.copy()
# Let's match the lighting/luminance of the plate
plate_morn = morn[627:730, 735:1075]
# Alpha blend the edges so there is no seam
mask = np.zeros(mid.shape[:2], dtype=np.float32)
mask[630:727, 738:1072] = 1.0
mask = cv2.GaussianBlur(mask, (15, 15), 0)
mask_3ch = np.dstack([mask]*3)

mid_seamless = (mid.astype(np.float32) * (1 - mask_3ch) + morn.astype(np.float32) * mask_3ch).astype(np.uint8)
blend_fixed = cv2.addWeighted(morn[620:740, 720:1100], 0.5, mid_seamless[620:740, 720:1100], 0.5, 0)
cv2.imwrite("test_sign_blend_fixed.png", blend_fixed)
cv2.imwrite("gemini-midday-perfect.jpeg", mid_seamless)

print("Saved test sign blends!")
