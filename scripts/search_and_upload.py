import os
import unicodedata
import requests

downloads_dir = "/Users/jungwoonlee/Downloads"
upload_url = "http://localhost:8000/upload"

found = False
for filename in os.listdir(downloads_dir):
    # Mac NFD 매칭용 노멀라이즈
    norm_nfc = unicodedata.normalize('NFC', filename)
    if filename == "%5B%EA%B5%90%ED%86%B5%EC%95%88%EC%A0%84+%EA%B7%B8%EB%A6%BC%EC%B1%85%5D+%EA%B3%A0%EC%96%91%EC%9D%B4+%EB%B3%84%EB%A1%9C+%EA%B0%80%EB%8A%94+%EA%B8%B8.pdf":
        filepath = os.path.join(downloads_dir, filename)
        print(f"✅ 일치하는 파일 발견: {norm_nfc}")
        print(f"🚀 업로드 중: {filepath}")
        
        try:
            with open(filepath, 'rb') as f:
                # requests를 이용하여 multipart/form-data 업로드
                files = {'file': (norm_nfc, f, 'application/pdf')}
                res = requests.post(upload_url, files=files)
                print(f"📊 응답 결과: [{res.status_code}] {res.text}")
                found = True
                break
        except Exception as e:
            print(f"❌ 에러 발생: {e}")

if not found:
    print("⚠️ '고양이' 키워드를 포함한 PDF 파일을 찾지 못했습니다.")
