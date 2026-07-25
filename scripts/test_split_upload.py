import requests
import os
import time

# 1. Google Drive 다운로드 획득
file_id = "19Kuax6pYoYsTgwhaeWgaykP76uPlqILg"
download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
output_pdf_path = "spread_sample.pdf"

print(f"1. Downloading from Google Drive...")
try:
    res = requests.get(download_url, stream=True)
    with open(output_pdf_path, "wb") as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"✅ Downloaded successfully to {output_pdf_path} (Size: {os.path.getsize(output_pdf_path)} bytes)")
except Exception as e:
    print(f"❌ Download Failed: {e}")
    exit(1)

# 2. 업로드 가동 (split_pages=true)
upload_url = "http://localhost:8000/upload?split_pages=true"
print(f"\n2. Uploading to {upload_url}...")

try:
    with open(output_pdf_path, "rb") as f:
         files = {'file': ('spread_sample.pdf', f, 'application/pdf')}
         # split_pages는 쿼리스트링 전달
         res = requests.post(upload_url, files=files)
         print(f"📊 Response: [{res.status_code}] {res.text}")
         
         if res.status_code == 200:
              book_id = res.json().get("book_id")
              print(f"🎉 Upload Success! Book ID: {book_id}")
              print("잠시 후 5초 뒤 해당 ID 를 뷰어에서 검증을 개시하세요.")
except Exception as e:
    print(f"❌ Upload Failed: {e}")
