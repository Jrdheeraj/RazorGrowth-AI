import re
import base64
import os

html_path = r"frontend/src/assets/illustrations/RazorGrowth AI – Day to Night.html"
with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()

img_matches = list(re.finditer(r'<img\s+([^>]+)>', text, re.IGNORECASE))
filenames = [
    "gemini-morning.jpeg",
    "gemini-midday.jpeg",
    "gemini-sunset.jpeg",
    "gemini-night.jpeg",
]

out_dir = r"frontend/src/assets/illustrations"

for i, m in enumerate(img_matches):
    attrs = m.group(1)
    src_m = re.search(r'src=["\']data:image/jpeg;base64,([^"\']+)["\']', attrs)
    if src_m and i < len(filenames):
        raw_b64 = src_m.group(1)
        data = base64.b64decode(raw_b64)
        out_path = os.path.join(out_dir, filenames[i])
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"Saved {filenames[i]} ({len(data)} bytes, 2560x1440)")
