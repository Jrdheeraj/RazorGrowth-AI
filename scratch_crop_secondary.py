import cv2

morn = cv2.imread(r"frontend/src/assets/illustrations/gemini-morning.jpeg")
mid = cv2.imread(r"frontend/src/assets/illustrations/gemini-midday.jpeg")

# Discover Opportunities sign: y: 700..850, x: 1450..1800
cv2.imwrite("crop_disc_morn.png", morn[700:850, 1450:1800])
cv2.imwrite("crop_disc_mid.png", mid[700:850, 1450:1800])

# Right side signs (Optimize Revenue, Automate Growth): y: 650..800, x: 2000..2550
cv2.imwrite("crop_right_morn.png", morn[650:800, 2000:2550])
cv2.imwrite("crop_right_mid.png", mid[650:800, 2000:2550])

print("Saved discover & right crops!")
