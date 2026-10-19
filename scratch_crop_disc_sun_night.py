import cv2
sun = cv2.imread(r"frontend/src/assets/illustrations/gemini-sunset.jpeg")
night = cv2.imread(r"frontend/src/assets/illustrations/gemini-night.jpeg")

cv2.imwrite("crop_disc_sun.png", sun[700:850, 1450:1800])
cv2.imwrite("crop_disc_night.png", night[700:850, 1450:1800])
print("Saved disc sun & night!")
