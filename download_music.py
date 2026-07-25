import os
import yt_dlp

def download_playlist():
    # 다운로드 받을 20곡의 검색 쿼리 리스트 (No Copyright / Audio 위주로 검색)
    songs = [
        "Erik Satie - Gymnopédie No. 1 No Copyright Audio",
        "Claude Debussy - Clair de Lune No Copyright Audio",
        "Chopin - Nocturne Op. 9 No. 2 No Copyright Audio",
        "Bach - Prelude in C Major No Copyright Audio",
        "Saint-Saëns - The Swan No Copyright Audio",
        "Debussy - Rêverie No Copyright Audio",
        "Beethoven - Moonlight Sonata 1st Movement No Copyright Audio",
        "Pachelbel - Canon in D No Copyright Audio",
        "Vivaldi - Winter Largo No Copyright Audio",
        "Grieg - Morning Mood No Copyright Audio",
        "Purrple Cat - Equinox Royalty Free Lofi",
        "Ghostrifter Official - Morning Routine Royalty Free",
        "Kupla - Sleepy Little One Royalty Free Lofi",
        "lōland - Echoes Royalty Free Lofi",
        "StreamBeats - Chill Vibes Ambient",
        "Hotham - The Point Royalty Free",
        "Sappheiros - Embrace Royalty Free",
        "eugenio izzi - Quiet Time Royalty Free Lofi",
        "Lukrembo - Storybook Royalty Free Lofi",
        "FASSounds - Lofi Study Royalty Free"
    ]

    # 저장할 디렉토리 생성
    output_dir = "Reading_Playlist_WAV"
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 '{output_dir}' 폴더에 다운로드를 시작합니다...\n")

    # yt-dlp 옵션 설정 (.wav 고음질 추출)
    ydl_opts = {
        'format': 'bestaudio/best',      # 최고 품질의 오디오 선택
        'noplaylist': True,              # 재생목록 무시하고 단일 영상만 다운
        'extract_audio': True,           # 오디오 추출 활성화
        'audio_format': 'wav',           # wav 포맷으로 지정
        'audio_quality': '0',            # 최고 음질 (0)
        'outtmpl': f'{output_dir}/%(title)s.%(ext)s', # 파일명 저장 규칙
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '0',
        }],
        'quiet': True,                   # 터미널 출력이 너무 길어지지 않게 True로 변경
        'no_warnings': True
    }

    # 다운로드 실행
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, song in enumerate(songs, 1):
            print(f"⏳ [{i}/{len(songs)}] 검색 및 다운로드 중: {song}")
            try:
                # ytsearch1: 쿼리로 검색된 첫 번째 영상 다운로드
                ydl.download([f"ytsearch1:{song}"])
                print(f"✅ 완료: {song}")
            except Exception as e:
                print(f"❌ '{song}' 다운로드 실패: {e}")
                
    print("\n🎉 모든 다운로드 및 .wav 변환이 완료되었습니다!")

if __name__ == "__main__":
    download_playlist()
