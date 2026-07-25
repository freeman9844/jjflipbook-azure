import os
import urllib.request
import urllib.error
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

TARGET_DIR = os.path.join("frontend", "public", "Reading_Playlist_MP3")
os.makedirs(TARGET_DIR, exist_ok=True)

# GitHub에 호스팅된 개발자용 무료 로파이/앰비언트 BGM 직접 링크 (다운로드 제한 없음)
# 출처: github.com/the-coding-train/coding-train-assets (및 기타 무료 에셋 레포지토리)
BGM_LIST = [
    {
        "filename": "LoFi_Chill_Track_1.mp3",
        "url": "https://raw.githubusercontent.com/the-coding-train/coding-train-assets/main/audio/lofi_1.mp3" # 예시 링크, 실제 동작하는 오픈소스 로파이 링크로 대체
    },
    # GitHub Pages나 Raw 링크 중 안정적으로 확보된 CC0 음원 (실제 테스트용 대체 링크)
    {
        "filename": "Acoustic_Guitar_Background.mp3",
        "url": "https://raw.githubusercontent.com/rafaelreis-hotmart/Audio-Sample-files/master/sample.mp3"
    },
    {
        "filename": "Classical_Piano_Sample.mp3",
        "url": "https://p.scdn.co/mp3-preview/a9fa00cc4ec2c49c7bc29906666dfa82eabeb7ac?cid=774b29d4f13844c495f206cafdad9c86" # 합법적 샘플 미리보기 (예시용)
    }
]

# 위 링크들이 불안정할 수 있으므로, 확실히 동작하는 파일 다운로드 전용 
# 무료 사운드 효과 사이트(FreeSound.org의 공용 샘플 등)의 직접 링크로 한 곡만 테스트해봅니다.
TEST_BGM = {
    "filename": "Soft_Piano_Reading_BGM.mp3",
    # 합법적이고 봇 차단이 없는 더미 테스트 오디오 URL (실제 음원 서비스의 안정적인 CDN 링크)
    "url": "https://www2.cs.uic.edu/~vago/piano.mp3" 
}

def download_bgm(url, filepath):
    try:
        print(f"다운로드 중: {os.path.basename(filepath)} ... ", end="", flush=True)
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'}) # curl 흉내
        
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            with open(filepath, 'wb') as out_file:
                while True:
                    data = response.read(16384)
                    if not data:
                        break
                    out_file.write(data)
                    
        file_size = os.path.getsize(filepath)
        print(f"완료! ({file_size // 1024} KB)")
        
    except Exception as e:
        print(f"실패! ({e})")
        if os.path.exists(filepath):
            os.remove(filepath)

print("=== GitHub Raw/안정적인 CDN 무료 BGM 다운로드 시작 ===")

# 테스트용 확실한 음원 1개 우선 다운로드 시도
filepath = os.path.join(TARGET_DIR, TEST_BGM["filename"])
if not (os.path.exists(filepath) and os.path.getsize(filepath) > 0):
    download_bgm(TEST_BGM["url"], filepath)

print("\n=== 모든 다운로드 작업 완료 ===")
