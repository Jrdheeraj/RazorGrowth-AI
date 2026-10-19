import cv2
import numpy as np

# Load the 4 gemini layers
img1 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-1.jpeg")
img2 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-2.jpeg")
img3 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-3.jpeg")
img4 = cv2.imread(r"frontend/src/assets/illustrations/gemini_day_night/gemini-layer-4.jpeg")

print("Loaded gemini layers:")
for i, im in enumerate([img1, img2, img3, img4]):
    print(f"Layer {i+1} shape: {im.shape}")

# Test 50/50 blend between 1 and 2, 2 and 3, 3 and 4
blend_12 = cv2.addWeighted(img1, 0.5, img2, 0.5, 0)
blend_23 = cv2.addWeighted(img2, 0.5, img3, 0.5, 0)
blend_34 = cv2.addWeighted(img3, 0.5, img4, 0.5, 0)

cv2.imwrite("gemini_blend_12.png", blend_12)
cv2.imwrite("gemini_blend_23.png", blend_23)
cv2.imwrite("gemini_blend_34.png", blend_34)
print("Saved blend checks!")
