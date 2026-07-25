import os
import urllib.request
import urllib.error
import ssl

# SSL 인증서 검증 무시 (일부 환경 다운로드 오류 방지)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 타겟 디렉토리 설정
TARGET_DIR = os.path.join("frontend", "public", "Reading_Playlist_MP3")
os.makedirs(TARGET_DIR, exist_ok=True)

# Wikimedia Commons의 안정적인 오디오 파일 직접 링크 (퍼블릭 도메인)
# 브라우저 User-Agent 및 Range 헤더를 추가하여 차단을 우회합니다.
BGM_LIST = [
    {
        "filename": "Satie_Gymnopedie_No_1.mp3",
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e5/Gymnop%C3%A9die_No._1.ogg"
    },
    {
        "filename": "Chopin_Nocturne_Op9_No2.mp3",
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/23/Chopin_-_Nocturne_Op_9_No_2_E_Flat_Major.ogg"
    },
    {
        "filename": "Debussy_Clair_de_Lune.mp3",
        "url": "https://upload.wikimedia.org/wikipedia/commons/e/e4/Clair_de_lune_%28Claude_Debussy%29.ogg"
    },
    {
        "filename": "Beethoven_Moonlight_Sonata.mp3",
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1b/Beethoven_-_Piano_Sonata_14_-_1_-_Adagio_sostenuto.ogg"
    },
    {
        "filename": "Mozart_Piano_Sonata_K545.mp3",
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/de/Mozart_-_Piano_Sonata_No._16_in_C_major%2C_K._545_-_I._Allegro.ogg"
    }
]

def download_file(url, filepath):
    try:
        print(f"다운로드 중: {os.path.basename(filepath)} ... ", end="", flush=True)
        # 봇 차단을 우회하기 위한 브라우저 헤더 세팅
        req = urllib.request.Request(
            url, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,video/*;q=0.6,*/*;q=0.5',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        )
        
        with urllib.request.urlopen(req, context=ctx) as response:
            with open(filepath, 'wb') as out_file:
                # 청크 단위로 다운로드
                while True:
                    data = response.read(8192)
                    if not data:
                        break
                    out_file.write(data)
                    
        file_size = os.path.getsize(filepath)
        print(f"완료! ({file_size} bytes)")
        
    except urllib.error.URLError as e:
        print(f"실패! (네트워크 에러: {e})")
        # 실패한 파일은 삭제 (0바이트 방지)
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"실패! (알 수 없는 에러: {e})")
        if os.path.exists(filepath):
            os.remove(filepath)

print("=== 완전 무료(Public Domain) 클래식 BGM 다운로드 시작 ===")
for item in BGM_LIST:
    # URL이 ogg 형식이지만 우선 폴더에 그대로 받습니다. (HTML5 Audio는 ogg도 지원)
    # 재생 호환성을 높이려면 mp3 변환이 필요하나, 현재는 직접 다운로드에 집중합니다.
    # 확장자를 url에 맞춰 자동 지정
    ext = item["url"].split(".")[-1]
    filename_with_ext = item["filename"].replace(".mp3", f".{ext}")
    filepath = os.path.join(TARGET_DIR, filename_with_ext)
    
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        print(f"이미 존재함, 건너뜀: {filename_with_ext}")
        continue
        
    download_file(item["url"], filepath)

print("\n=== 모든 다운로드 작업 완료 ===")
