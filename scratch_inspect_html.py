import re
import base64
from PIL import Image
import io
import hashlib
import os

html_path = r"frontend/src/assets/illustrations/RazorGrowth AI – Day to Night.html"
with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()

img_matches = list(re.finditer(r'<img\s+([^>]+)>', text, re.IGNORECASE))
print(f"Total img tags: {len(img_matches)}")

out_dir = r"frontend/src/assets/illustrations/gemini_day_night"
os.makedirs(out_dir, exist_ok=True)

for i, m in enumerate(img_matches):
    attrs = m.group(1)
    src_m = re.search(r'src=["\']data:image/jpeg;base64,([^"\']+)["\']', attrs)
    alt_m = re.search(r'alt=["\']([^"\']*)["\']', attrs)
    if src_m:
        raw_b64 = src_m.group(1)
        data = base64.b64decode(raw_b64)
        im = Image.open(io.BytesIO(data))
        alt = alt_m.group(1) if alt_m else f"image_{i}"
        md5 = hashlib.md5(data).hexdigest()
        filename = f"gemini-layer-{i+1}.jpeg"
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "wb") as img_file:
            img_file.write(data)
        print(f"Layer {i}: {alt} | Size: {im.size} | Bytes: {len(data)} | MD5: {md5} -> saved to {filename}")

# Also compare with existing Home-page-image-1..4
for k in range(1, 5):
    p = f"frontend/src/assets/illustrations/Home-page-image-{k}.jpeg"
    if os.path.exists(p):
        with open(p, "rb") as f:
            d = f.read()
        im = Image.open(p)
        print(f"Existing Home-page-image-{k}.jpeg: Size: {im.size} | Bytes: {len(d)} | MD5: {hashlib.md5(d).hexdigest()}")
