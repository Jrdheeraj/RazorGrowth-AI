import cv2
import numpy as np

img1 = cv2.imread(r"frontend/src/assets/illustrations/gemini-morning.jpeg")
img2 = cv2.imread(r"frontend/src/assets/illustrations/gemini-midday.jpeg")

# The sign plate in 2560x1440:
# y: 625..730, x: 740..1070
# Let's check cross-correlation of the text plate
plate1 = img1[620:735, 730:1080]
plate2 = img2[620:735, 730:1080]

gray1 = cv2.cvtColor(plate1, cv2.COLOR_BGR2GRAY)
gray2 = cv2.cvtColor(plate2, cv2.COLOR_BGR2GRAY)

res = cv2.matchTemplate(gray2, gray1, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

print("Template match:", max_val, max_loc)

# Let's measure exact pixel offset between the sign in img1 and img2
# In plate: let's find the 'R' in RazorGrowth
r1 = cv2.findTransformECC(gray1, gray2, np.eye(2,3,dtype=np.float32), cv2.MOTION_TRANSLATION)
print("Sign offset in midday:", r1[1][0,2], r1[1][1,2])
