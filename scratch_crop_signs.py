import cv2

img1 = cv2.imread(r"frontend/src/assets/illustrations/gemini-morning.jpeg")
img2 = cv2.imread(r"frontend/src/assets/illustrations/gemini-midday.jpeg")
img3 = cv2.imread(r"frontend/src/assets/illustrations/gemini-sunset.jpeg")
img4 = cv2.imread(r"frontend/src/assets/illustrations/gemini-night.jpeg")

# Crop the RazorGrowth AI sign: y 600..750, x 700..1100 (in 2560x1440)
# Let's find where the sign is
# In 2560x1440:
cv2.imwrite("crop_sign_morn.png", img1[600:750, 700:1100])
cv2.imwrite("crop_sign_mid.png", img2[600:750, 700:1100])
cv2.imwrite("crop_sign_sun.png", img3[600:750, 700:1100])
cv2.imwrite("crop_sign_night.png", img4[600:750, 700:1100])

print("Saved sign crops!")
