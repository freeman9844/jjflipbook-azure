"use client";

import React, { useEffect, useState, use, useRef } from 'react';
import { useRouter } from 'next/navigation';

interface FlipbookData {
    uuid_key: string;
    title: string;
    page_count: number;
    image_urls: string[];
}

interface Overlay {
    page: number;
    type: string;
    x: number;
    y: number;
    width: number;
    height: number;
    data_url: string;
}

interface ModalData {
    type: string;
    data_url: string;
}

export default function FlipbookEditor({ params }: { params: Promise<{ bookId: string }> }) {
    const resolvedParams = use(params);
    const bookId = resolvedParams.bookId;
    const router = useRouter();

    const [book, setBook] = useState<FlipbookData | null>(null);
    const [overlays, setOverlays] = useState<Overlay[]>([]);
    const [activePage, setActivePage] = useState<number>(1);
    const [error, setError] = useState<string>("");

    // 드래그 상태
    const [isDrawing, setIsDrawing] = useState(false);
    const [startPos, setStartPos] = useState({ x: 0, y: 0 });
    const [currentPos, setCurrentPos] = useState({ x: 0, y: 0 });
    const workspaceRef = useRef<HTMLDivElement>(null);

    // 오버레이 모달 상태
    const [selectedOverlayIndex, setSelectedOverlayIndex] = useState<number | null>(null);
    const [modalData, setModalData] = useState<ModalData>({ type: 'link', data_url: '' });

    useEffect(() => {
        const fetchData = async () => {
            try {
                const bookRes = await fetch(`/api/backend/flipbook/${bookId}`);
                if (!bookRes.ok) throw new Error("플립북 데이터를 불러오지 못했습니다.");
                const bookData: FlipbookData = await bookRes.json();
                setBook(bookData);

                const overlayRes = await fetch(`/api/backend/flipbook/${bookId}/overlays`);
                if (overlayRes.ok) {
                    const overlayData: Overlay[] = await overlayRes.json();
                    setOverlays(overlayData);
                }
            } catch (err) {
                setError(err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다.");
            }
        };
        fetchData();
    }, [bookId]);

    const handleMouseDown = (e: React.MouseEvent) => {
        if (!workspaceRef.current) return;
        const rect = workspaceRef.current.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * 100;
        const y = ((e.clientY - rect.top) / rect.height) * 100;
        setIsDrawing(true);
        setStartPos({ x, y });
        setCurrentPos({ x, y });
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (!isDrawing || !workspaceRef.current) return;
        const rect = workspaceRef.current.getBoundingClientRect();
        setCurrentPos({
            x: ((e.clientX - rect.left) / rect.width) * 100,
            y: ((e.clientY - rect.top) / rect.height) * 100,
        });
    };

    const handleMouseUp = () => {
        if (!isDrawing) return;
        setIsDrawing(false);

        const x = Math.min(startPos.x, currentPos.x);
        const y = Math.min(startPos.y, currentPos.y);
        const width = Math.abs(currentPos.x - startPos.x);
        const height = Math.abs(currentPos.y - startPos.y);

        if (width > 0.5 && height > 0.5) {
            const newOverlay: Overlay = { page: activePage, type: 'link', x, y, width, height, data_url: '' };
            const newOverlays = [...overlays, newOverlay];
            setOverlays(newOverlays);
            setSelectedOverlayIndex(newOverlays.length - 1);
            setModalData({ type: 'link', data_url: '' });
        }
    };

    const handleSaveModal = () => {
        if (selectedOverlayIndex === null) return;
        setOverlays(prev => prev.map((o, i) =>
            i === selectedOverlayIndex ? { ...o, type: modalData.type, data_url: modalData.data_url } : o
        ));
        setSelectedOverlayIndex(null);
    };

    const handleOverlayDelete = (idx: number) => {
        setOverlays(prev => prev.filter((_, i) => i !== idx));
        setSelectedOverlayIndex(null);
    };

    const handleSaveChanges = async () => {
        try {
            const res = await fetch(`/api/backend/flipbook/${bookId}/overlays`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(overlays),
            });
            if (res.ok) alert("🎉 설정 및 오버레이가 저장되었습니다.");
            else alert("❌ 저장 실패가 발생했습니다.");
        } catch {
            alert("❌ 통신 중 에러가 발생했습니다.");
        }
    };

    if (error) return <div style={styles.error}>에러: {error}</div>;
    if (!book) return <div style={styles.loading}>데이터 로딩 중...</div>;

    const currentPageUrl = book.image_urls[activePage - 1];

    return (
        <div style={styles.container}>
            {/* 상단 네비게이션 바 */}
            <div style={styles.navbar}>
                <div style={styles.navLeft}>
                    <span style={styles.logoText}>JJFlipBook</span>
                </div>
                <div style={styles.navCenter}>
                    <button style={styles.navTab} onClick={() => router.push('/')}>My Documents</button>
                    <button style={styles.navTab} onClick={() => router.push(`/view/${bookId}`)}>View</button>
                </div>
                <div style={styles.navRight} />
            </div>

            <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative', backgroundColor: '#fcfcfc' }}>
                {/* 중앙 워크스페이스 */}
                <div style={styles.workspaceArea}>
                    <button style={styles.saveBtn} onClick={handleSaveChanges}>저장하기</button>

                    <div
                        ref={workspaceRef}
                        style={styles.canvasContainer}
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                    >
                        {currentPageUrl ? (
                            <>
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                    src={currentPageUrl}
                                    alt="edit"
                                    style={styles.pageImage}
                                    draggable={false}
                                />
                                {overlays.filter(o => o.page === activePage).map((overlay, index) => (
                                    <div
                                        key={index}
                                        style={{
                                            position: 'absolute',
                                            border: '2px solid #1a73e8',
                                            backgroundColor: 'rgba(26, 115, 232, 0.12)',
                                            left: `${overlay.x}%`,
                                            top: `${overlay.y}%`,
                                            width: `${overlay.width}%`,
                                            height: `${overlay.height}%`,
                                            cursor: 'pointer',
                                            borderRadius: '2px',
                                        }}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            setSelectedOverlayIndex(index);
                                            setModalData({ type: overlay.type, data_url: overlay.data_url });
                                        }}
                                    />
                                ))}
                                {isDrawing && (
                                    <div style={{
                                        position: 'absolute',
                                        border: '2px dashed #1a73e8',
                                        backgroundColor: 'rgba(26, 115, 232, 0.2)',
                                        left: `${Math.min(startPos.x, currentPos.x)}%`,
                                        top: `${Math.min(startPos.y, currentPos.y)}%`,
                                        width: `${Math.abs(currentPos.x - startPos.x)}%`,
                                        height: `${Math.abs(currentPos.y - startPos.y)}%`,
                                        borderRadius: '2px',
                                    }} />
                                )}
                            </>
                        ) : (
                            <div style={{ color: '#5f6368' }}>이미지를 불러올 수 없습니다.</div>
                        )}
                    </div>

                    {/* 하단 컨트롤 바 */}
                    <div style={styles.bottomBar}>
                        <div style={styles.pagerControl}>
                            <button style={styles.pagerBtn} disabled={activePage === 1} onClick={() => setActivePage(p => p - 1)}>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
                            </button>
                            <span style={styles.pagerText}>{activePage} / {book.page_count}</span>
                            <button style={styles.pagerBtn} disabled={activePage === book.page_count} onClick={() => setActivePage(p => p + 1)}>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* 오버레이 편집 모달 */}
            {selectedOverlayIndex !== null && (
                <div style={styles.modalBackdrop}>
                    <div style={styles.modalContent}>
                        <h3 style={styles.modalTitle}>오버레이 상세 설정</h3>
                        <div style={styles.formGroup}>
                            <label style={styles.label}>타입 선택</label>
                            <select
                                value={modalData.type}
                                onChange={(e) => setModalData(prev => ({ ...prev, type: e.target.value }))}
                                style={styles.input}
                            >
                                <option value="link">하이퍼링크 (Link)</option>
                                <option value="video">YouTube 비디오 (Embed)</option>
                            </select>
                        </div>
                        <div style={styles.formGroup}>
                            <label style={styles.label}>URL 주소</label>
                            <input
                                placeholder="https://..."
                                value={modalData.data_url}
                                onChange={(e) => setModalData(prev => ({ ...prev, data_url: e.target.value }))}
                                style={styles.input}
                            />
                        </div>
                        <div style={styles.modalButtons}>
                            <button onClick={handleSaveModal} style={styles.primaryBtn}>승인</button>
                            <button onClick={() => handleOverlayDelete(selectedOverlayIndex!)} style={styles.dangerBtn}>삭제</button>
                            <button onClick={() => setSelectedOverlayIndex(null)} style={styles.cancelBtn}>취소</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

const styles: Record<string, React.CSSProperties> = {
    container: { display: 'flex', flexDirection: 'column', height: '100dvh', width: '100vw', backgroundColor: '#ffffff', color: '#1a1a1a', fontFamily: 'system-ui, -apple-system, sans-serif' },
    navbar: { height: '56px', backgroundColor: 'white', borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px' },
    navLeft: { display: 'flex', alignItems: 'center' },
    navRight: { width: '200px' },
    logoText: { fontSize: '20px', fontWeight: 'bold', color: '#1a1a1a', letterSpacing: '-0.5px' },
    navCenter: { display: 'flex', gap: '32px' },
    navTab: { background: 'none', border: 'none', fontSize: '15px', color: '#5f6368', cursor: 'pointer', padding: '16px 4px', position: 'relative', fontWeight: 500 },
    workspaceArea: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative', padding: '40px', overflow: 'hidden' },
    canvasContainer: { position: 'relative', width: 'min(90vw, 600px)', height: 'min(85vh, calc(min(90vw, 600px) * 1.414))', backgroundColor: 'white', overflow: 'hidden', boxShadow: '0 10px 30px rgba(0,0,0,0.08)', borderRadius: '8px' },
    pageImage: { width: '100%', height: '100%', objectFit: 'contain', userSelect: 'none' },
    saveBtn: { position: 'absolute', top: '24px', right: '40px', padding: '10px 24px', backgroundColor: '#1a73e8', color: 'white', border: 'none', borderRadius: '24px', fontWeight: 500, cursor: 'pointer', boxShadow: '0 4px 6px rgba(26, 115, 232, 0.25)', transition: 'all 0.2s' },
    bottomBar: { position: 'absolute', bottom: '32px', display: 'flex', gap: '40px', backgroundColor: 'rgba(255, 255, 255, 0.95)', padding: '12px 24px', borderRadius: '32px', boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)', backdropFilter: 'blur(10px)', alignItems: 'center' },
    pagerControl: { display: 'flex', alignItems: 'center', gap: '16px' },
    pagerBtn: { background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', color: '#5f6368' },
    pagerText: { fontSize: '14px', fontWeight: 500, color: '#3c4043' },
    modalBackdrop: { position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', backgroundColor: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 },
    modalContent: { backgroundColor: 'white', padding: '28px', borderRadius: '12px', width: '420px', display: 'flex', flexDirection: 'column', gap: '20px', boxShadow: '0 20px 40px rgba(0,0,0,0.15)' },
    modalTitle: { margin: 0, fontSize: '18px', fontWeight: 600, color: '#202124' },
    formGroup: { display: 'flex', flexDirection: 'column', gap: '8px' },
    label: { fontSize: '13px', fontWeight: 500, color: '#5f6368' },
    input: { padding: '12px', border: '1px solid #dadce0', borderRadius: '6px', fontSize: '14px', outline: 'none' },
    modalButtons: { display: 'flex', gap: '12px', marginTop: '12px' },
    primaryBtn: { flex: 2, padding: '12px', backgroundColor: '#1a73e8', color: 'white', border: 'none', borderRadius: '6px', fontWeight: 500, cursor: 'pointer' },
    dangerBtn: { flex: 1, padding: '12px', backgroundColor: '#fdf4f4', color: '#d93025', border: '1px solid #fecaca', borderRadius: '6px', fontWeight: 500, cursor: 'pointer' },
    cancelBtn: { flex: 1, padding: '12px', backgroundColor: 'white', color: '#5f6368', border: '1px solid #dadce0', borderRadius: '6px', fontWeight: 500, cursor: 'pointer' },
    error: { padding: '24px', color: '#d93025' },
    loading: { padding: '24px', color: '#5f6368' },
};
