"use client";

import React, { useEffect, useState, use, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import HTMLFlipBook from 'react-pageflip';
import MusicPlayer from '@/components/MusicPlayer';

interface FlipbookData {
    uuid_key: string;
    title: string;
    page_count: number;
    image_urls: string[];
    pdf_url?: string;
    status?: string;
}

interface Overlay {
    id?: string;
    page: number;
    type: string;
    x: number;
    y: number;
    width: number;
    height: number;
    data_url: string;
}

export default function FlipbookViewer({ params }: { params: Promise<{ uuidKey: string }> }) {
    const resolvedParams = use(params);
    const uuidKey = resolvedParams.uuidKey;
    const router = useRouter();

    const [book, setBook] = useState<FlipbookData | null>(null);
    const [overlays, setOverlays] = useState<Overlay[]>([]);
    const [error, setError] = useState<string>("");
    const [currentPage, setCurrentPage] = useState<number>(1);
    const [isAdmin, setIsAdmin] = useState(false);
    const [zoom, setZoom] = useState<number>(100);
    const [windowWidth, setWindowWidth] = useState(1200);
    const [windowHeight, setWindowHeight] = useState(800);
    const [isMounted, setIsMounted] = useState(false);
    // react-pageflip은 TypeScript 타입 미지원 - any 사용 불가피
    const flipBookRef = useRef<any>(null);

    useEffect(() => {
        if (typeof window === "undefined") return;
        setWindowWidth(window.innerWidth);
        setWindowHeight(window.innerHeight);
        setIsMounted(true);
        const handleResize = () => {
            setWindowWidth(window.innerWidth);
            setWindowHeight(window.innerHeight);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    useEffect(() => {
        if (typeof window !== "undefined") {
            setIsAdmin(localStorage.getItem("isAuthenticated") === "true");
        }
    }, []);

    // 키보드 화살표 네비게이션
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!flipBookRef.current) return;
            const pageFlip = flipBookRef.current.pageFlip();
            if (e.key === 'ArrowRight') pageFlip.flipNext();
            else if (e.key === 'ArrowLeft') pageFlip.flipPrev();
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    useEffect(() => {
        const fetchBook = async () => {
            try {
                const res = await fetch(`/api/backend/flipbook/${uuidKey}`);
                if (!res.ok) throw new Error("플립북을 찾을 수 없거나 불러오지 못했습니다.");
                const data: FlipbookData = await res.json();
                setBook(data);

                const overlayRes = await fetch(`/api/backend/flipbook/${uuidKey}/overlays`);
                if (overlayRes.ok) {
                    const overlayData: Overlay[] = await overlayRes.json();
                    setOverlays(overlayData);
                }
            } catch (err) {
                setError(err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다.");
            }
        };
        fetchBook();
    }, [uuidKey]);

    const isMobile = windowWidth < 768;
    const styles = useMemo(() => getStyles(isMobile), [isMobile]);

    if (error) return <div style={{ color: 'red', padding: 20 }}>에러: {error}</div>;
    if (!book) return <div style={{ color: '#5f6368', padding: 20 }}>로딩 중...</div>;
    if (!isMounted) return <div style={styles.container} />;

    const hasImages = book.image_urls && book.image_urls.length > 0;
    // transform: scale() 대신 직접 크기 계산 → iOS 터치 좌표 불일치 방지
    const maxBookW = windowWidth - (isMobile ? 40 : 240);
    const maxBookH = windowHeight - (isMobile ? 220 : 80);
    const fitScale = Math.min(maxBookW / 500, maxBookH / 700);
    const bookWidth = Math.max(100, Math.round(500 * fitScale * (zoom / 100)));
    const bookHeight = Math.max(150, Math.round(700 * fitScale * (zoom / 100)));

    return (
        <div style={styles.container}>
            {/* 음악 플레이어 (사이드바 내부 또는 하단 바에서 렌더링) */}

            {/* 좌측 사이드바 (데스크탑) */}
            {!isMobile && (
                <div style={styles.sidebar}>
                    <div style={styles.logoArea}>
                        <span style={styles.logoText}>JJFlipBook</span>
                    </div>
                    <div style={styles.sidebarMenu}>
                        {isAdmin && (
                            <button style={styles.sidebarTab} onClick={() => router.push('/')}>My Documents</button>
                        )}
                        <button style={{ ...styles.sidebarTab, ...styles.sidebarTabActive }}>View</button>
                    </div>
                </div>
            )}

            {/* 중앙 플립북 영역 */}
            <div style={styles.workspaceArea}>
                {hasImages ? (
                    <div style={{
                        width: `${bookWidth}px`,
                        height: `${bookHeight}px`,
                        position: 'relative',
                        marginTop: isMobile ? '20px' : '0',
                    }}>
                        {/* @ts-ignore - react-pageflip 라이브러리 타입 미지원 */}
                        <HTMLFlipBook
                            ref={flipBookRef}
                            width={bookWidth}
                            height={bookHeight}
                            size="fixed"
                            minWidth={100}
                            maxWidth={1500}
                            minHeight={150}
                            maxHeight={2000}
                            maxShadowOpacity={0.5}
                            showCover={false}
                            mobileScrollSupport={true}
                            drawShadow={false}
                            flippingTime={600}
                            onFlip={(e: { data: number }) => setCurrentPage(e.data + 1)}
                        >
                            {book.image_urls.map((url: string, index: number) => (
                                <div key={index} style={styles.pageItem}>
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                        src={url}
                                        alt={`Page ${index + 1}`}
                                        style={styles.pageImage}
                                    />
                                    {overlays
                                        .filter((o) => o.page === index + 1)
                                        .map((o, i) => (
                                            <div key={i} style={{
                                                position: 'absolute',
                                                left: `${o.x}%`,
                                                top: `${o.y}%`,
                                                width: `${o.width}%`,
                                                height: `${o.height}%`,
                                                zIndex: 10,
                                                pointerEvents: 'auto',
                                            }}>
                                                {o.type === 'video' ? (
                                                    <iframe
                                                        src={o.data_url.includes("youtube.com/watch") ? o.data_url.replace("watch?v=", "embed/") : o.data_url}
                                                        style={{ width: '100%', height: '100%', border: 'none' }}
                                                        allowFullScreen
                                                    />
                                                ) : (
                                                    <a
                                                        href={o.data_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        style={{ display: 'block', width: '100%', height: '100%', backgroundColor: 'rgba(0, 195, 255, 0.1)' }}
                                                    />
                                                )}
                                            </div>
                                        ))}
                                </div>
                            ))}
                        </HTMLFlipBook>
                    </div>
                ) : (
                    <div style={{ color: 'gray' }}>변환된 페이지가 없습니다.</div>
                )}

                {/* 하단 컨트롤 바 */}
                {hasImages && (
                    <div style={styles.bottomBar}>
                        {/* 줌 컨트롤 */}
                        <div style={styles.zoomControl}>
                            <button style={styles.pillBtn} onClick={() => setZoom(z => Math.max(50, z - 10))}>-</button>
                            <span style={styles.zoomText}>{zoom}%</span>
                            <button style={styles.pillBtn} onClick={() => setZoom(z => Math.min(200, z + 10))}>+</button>
                        </div>

                        {/* 페이지 컨트롤 */}
                        <div style={styles.pagerControl}>
                            <button
                                style={styles.pagerBtn}
                                disabled={currentPage === 1}
                                onClick={() => flipBookRef.current?.pageFlip().flipPrev()}
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                            </button>
                            <span style={styles.pagerText}>{currentPage} / {book.image_urls.length}</span>
                            <button
                                style={styles.pagerBtn}
                                disabled={currentPage === book.image_urls.length}
                                onClick={() => flipBookRef.current?.pageFlip().flipNext()}
                            >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                            </button>
                        </div>

                        {/* 다운로드 + 음악 */}
                        <div style={styles.musicControl}>
                            {book.pdf_url && (
                                <a
                                    href={book.pdf_url}
                                    download
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    style={{ ...styles.musicBtn, color: '#5f6368', backgroundColor: 'transparent', textDecoration: 'none' }}
                                    title="원본 PDF 다운로드"
                                >
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                        <polyline points="7 10 12 15 17 10"></polyline>
                                        <line x1="12" y1="15" x2="12" y2="3"></line>
                                    </svg>
                                </a>
                            )}
                            <MusicPlayer />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

const getStyles = (isMobile: boolean): Record<string, React.CSSProperties> => ({
    container: { display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100dvh', width: '100vw', backgroundColor: '#f5f7f9', color: '#1a1a1a', fontFamily: 'system-ui, -apple-system, sans-serif', overflow: 'hidden' },
    sidebar: { width: '220px', backgroundColor: 'white', borderRight: '1px solid #e4e7eb', display: 'flex', flexDirection: 'column', padding: '32px 16px', boxSizing: 'border-box', gap: '32px', zIndex: 10 },
    logoArea: { display: 'flex', alignItems: 'center', paddingBottom: '16px', borderBottom: '1px solid #f1f3f5', marginLeft: '8px' },
    logoText: { fontSize: '20px', fontWeight: 'bold', color: '#1a1a1a', letterSpacing: '-0.5px' },
    sidebarMenu: { display: 'flex', flexDirection: 'column', gap: '8px', flex: 1 },
    sidebarTab: { background: 'none', border: 'none', fontSize: '15px', color: '#4b5563', cursor: 'pointer', padding: '12px 16px', borderRadius: '10px', textAlign: 'left', fontWeight: 500, transition: 'all 0.2s', width: '100%' },
    sidebarTabActive: { backgroundColor: '#eef2ff', color: '#2563eb', fontWeight: 600 },
    workspaceArea: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative', padding: isMobile ? '12px' : '24px', overflow: 'hidden' },
    pageItem: { backgroundColor: 'white', boxShadow: '0 0 15px rgba(0,0,0,0.15)', display: 'flex', justifyContent: 'center', alignItems: 'center', position: 'relative', width: '100%', height: '100%' },
    pageImage: { width: '100%', height: '100%', objectFit: 'contain', pointerEvents: 'none' },
    bottomBar: { position: 'absolute', bottom: isMobile ? '12px' : '24px', display: 'flex', gap: isMobile ? '16px' : '24px', backgroundColor: 'rgba(255, 255, 255, 0.97)', padding: isMobile ? '6px 12px' : '7px 16px', borderRadius: '24px', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.06)', backdropFilter: isMobile ? 'none' : 'blur(10px)', alignItems: 'center' },
    zoomControl: { display: 'flex', alignItems: 'center', gap: '8px' },
    pillBtn: { width: '22px', height: '22px', border: 'none', backgroundColor: '#f1f3f4', borderRadius: '50%', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', color: '#5f6368', touchAction: 'manipulation' },
    zoomText: { fontSize: '12px', fontWeight: 500, color: '#3c4043', width: '36px', textAlign: 'center' },
    pagerControl: { display: 'flex', alignItems: 'center', gap: '12px', borderLeft: '1px solid #e8eaed', paddingLeft: '16px' },
    pagerBtn: { background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', color: '#5f6368', padding: 0, touchAction: 'manipulation' },
    pagerText: { fontSize: '12px', fontWeight: 500, color: '#3c4043' },
    musicControl: { display: 'flex', alignItems: 'center', gap: '12px', borderLeft: '1px solid #e8eaed', paddingLeft: '16px' },
    musicBtn: { border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '6px', borderRadius: '50%', transition: 'all 0.2s', width: '32px', height: '32px' },
});
