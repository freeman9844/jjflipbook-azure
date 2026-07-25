"use client";

import React, { useEffect, useState, useRef } from 'react';

export default function MusicPlayer() {
    const [musicFiles, setMusicFiles] = useState<string[]>([]);
    const [currentSong, setCurrentSong] = useState<string | null>(null);
    const [isPlaying, setIsPlaying] = useState<boolean>(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    // 음악 목록 로드
    useEffect(() => {
        fetch('/api/music')
            .then(res => res.json())
            .then((data: { files?: string[] }) => {
                if (data.files && data.files.length > 0) {
                    setMusicFiles(data.files);
                    const randomSong = data.files[Math.floor(Math.random() * data.files.length)];
                    setCurrentSong(randomSong);
                }
            })
            .catch(() => {
                // 음악 로드 실패 시 조용히 무시
            });
    }, []);

    // 재생 상태 연동 + 모바일 첫 터치 언락
    useEffect(() => {
        if (currentSong && audioRef.current && isPlaying) {
            audioRef.current.play().catch(() => { /* 자동재생 차단 시 무시 */ });
        }

        const unlockAudio = async () => {
            if (audioRef.current && currentSong && !isPlaying) {
                try {
                    await audioRef.current.play();
                    setIsPlaying(true);
                } catch {
                    // 아직 언락 불가 - 다음 인터랙션에서 재시도
                }
            }
        };

        if (typeof window !== 'undefined' && !isPlaying) {
            // pointerdown만 사용: touchstart를 중복 등록하면 iOS 첫 탭을 이중 소비
            window.addEventListener('pointerdown', unlockAudio, { once: true });
            window.addEventListener('keydown', unlockAudio, { once: true });
        }

        return () => {
            if (typeof window !== 'undefined') {
                window.removeEventListener('pointerdown', unlockAudio);
                window.removeEventListener('keydown', unlockAudio);
            }
        };
    }, [currentSong, isPlaying]);

    const handleSongEnd = () => {
        if (musicFiles.length === 0) return;
        const otherSongs = musicFiles.filter(s => s !== currentSong);
        const nextList = otherSongs.length > 0 ? otherSongs : musicFiles;
        setCurrentSong(nextList[Math.floor(Math.random() * nextList.length)]);
    };

    const toggleMusic = () => {
        if (!audioRef.current || !currentSong) return;
        if (isPlaying) {
            audioRef.current.pause();
            setIsPlaying(false);
        } else {
            audioRef.current.play().catch(() => { /* 재생 실패 무시 */ });
            setIsPlaying(true);
        }
    };

    const songDisplayName = currentSong
        ? (currentSong.split('/').pop()?.replace('.mp3', '') ?? '')
        : null;

    return (
        <>
            {currentSong && (
                <audio
                    ref={audioRef}
                    src={currentSong}
                    onEnded={handleSongEnd}
                />
            )}

            {isPlaying && songDisplayName && (
                <div style={musicTitleStyle}>
                    🎵 {songDisplayName}
                </div>
            )}

            <button
                style={{
                    ...musicBtnStyle,
                    color: isPlaying ? '#2563eb' : '#5f6368',
                    backgroundColor: isPlaying ? '#eef2ff' : 'transparent',
                }}
                onClick={toggleMusic}
                title={songDisplayName ?? "음악 없음"}
            >
                {isPlaying ? <SoundOnIcon /> : <SoundOffIcon />}
            </button>
        </>
    );
}

function SoundOnIcon() {
    return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
        </svg>
    );
}

function SoundOffIcon() {
    return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
            <line x1="23" y1="9" x2="17" y2="15"></line>
            <line x1="17" y1="9" x2="23" y2="15"></line>
        </svg>
    );
}

const musicBtnStyle: React.CSSProperties = {
    border: 'none',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '6px',
    borderRadius: '50%',
    transition: 'all 0.2s',
    width: '32px',
    height: '32px',
};

const musicTitleStyle: React.CSSProperties = {
    fontSize: '11px',
    color: '#2563eb',
    fontWeight: 500,
    maxWidth: '120px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
};
