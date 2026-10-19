import cv2
import numpy as np

morn = cv2.imread(r"frontend/src/assets/illustrations/gemini-morning.jpeg")
mid = cv2.imread(r"frontend/src/assets/illustrations/gemini-midday.jpeg")
sun = cv2.imread(r"frontend/src/assets/illustrations/gemini-sunset.jpeg")
night = cv2.imread(r"frontend/src/assets/illustrations/gemini-night.jpeg")

# Fix midday signs:
# 1. RazorGrowth AI main sign: y: 620..735, x: 730..1080
# 2. Discover Opportunities sign: y: 690..860, x: 1530..1780
# 3. Optimize Revenue sign: y: 650..750, x: 2070..2280
# 4. Automate Growth sign: y: 650..750, x: 2320..2520

mid_perfect = mid.copy()

def blend_patch(bg, fg, y1, y2, x1, x2, ksize=11):
    h, w = bg.shape[:2]
    mask = np.zeros((h, w), dtype=np.float32)
    mask[y1+5:y2-5, x1+5:x2-5] = 1.0
    mask = cv2.GaussianBlur(mask, (ksize, ksize), 0)
    mask_3ch = np.dstack([mask] * 3)
    return (bg.astype(np.float32) * (1 - mask_3ch) + fg.astype(np.float32) * mask_3ch).astype(np.uint8)

# Apply patches from morning to midday
mid_perfect = blend_patch(mid_perfect, morn, 625, 732, 735, 1075) # RazorGrowth AI
mid_perfect = blend_patch(mid_perfect, morn, 695, 855, 1535, 1775) # Discover Opportunities
mid_perfect = blend_patch(mid_perfect, morn, 665, 745, 2075, 2275) # Optimize Revenue
mid_perfect = blend_patch(mid_perfect, morn, 665, 745, 2325, 2515) # Automate Growth

# Save the perfect midday image
cv2.imwrite(r"frontend/src/assets/illustrations/gemini-midday.jpeg", mid_perfect)

# Check all pairwise 50/50 blends
blend12 = cv2.addWeighted(morn, 0.5, mid_perfect, 0.5, 0)
blend23 = cv2.addWeighted(mid_perfect, 0.5, sun, 0.5, 0)
blend34 = cv2.addWeighted(sun, 0.5, night, 0.5, 0)

cv2.imwrite("check_perfect_gemini_12.png", blend12)
cv2.imwrite("check_perfect_gemini_23.png", blend23)
cv2.imwrite("check_perfect_gemini_34.png", blend34)

print("Generated check_perfect_gemini_12, 23, 34!")
