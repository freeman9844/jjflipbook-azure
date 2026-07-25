"use client";

import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import FolderCard, { type Folder } from '@/components/FolderCard';
import FlipbookCard, { type Flipbook } from '@/components/FlipbookCard';
import ConfirmModal from '@/components/ConfirmModal';
import CreateFolderModal from '@/components/CreateFolderModal';

export default function Home() {
    const router = useRouter();

    const [books, setBooks] = useState<Flipbook[]>([]);
    const [folders, setFolders] = useState<Folder[]>([]);
    const [isLoadingData, setIsLoadingData] = useState<boolean>(true);
    const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);

    const [uploading, setUploadLoading] = useState(false);
    const [uploadDots, setUploadDots] = useState("");

    const [deletingUuid, setDeletingUuid] = useState<string | null>(null);
    const [deletingFolderId, setDeletingFolderId] = useState<string | null>(null);
    const [isCreatingFolder, setIsCreatingFolder] = useState<boolean>(false);
    const [newFolderName, setNewFolderName] = useState<string>("");

    const [splitPages, setSplitPages] = useState<boolean>(true);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [pollTrigger, setPollTrigger] = useState<number>(0);

    const [windowWidth, setWindowWidth] = useState(1200);

    // 업로드 중 점 애니메이션
    useEffect(() => {
        if (!uploading) { setUploadDots(""); return; }
        const interval = setInterval(() => {
            setUploadDots(prev => prev.length >= 3 ? "" : prev + ".");
        }, 400);
        return () => clearInterval(interval);
    }, [uploading]);

    useEffect(() => {
        if (typeof window === "undefined") return;
        setWindowWidth(window.innerWidth);
        const handleResize = () => setWindowWidth(window.innerWidth);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const pollDelay = useRef(3000);
    const isMobile = windowWidth < 768;
    const styles = useMemo(() => getStyles(isMobile), [isMobile]);

    const fetchAllData = useCallback(async () => {
        try {
            const [booksRes, foldersRes] = await Promise.all([
                fetch(`/api/backend/flipbooks`),
                fetch(`/api/backend/folders`)
            ]);

            if (booksRes.status === 401 || foldersRes.status === 401) {
                // AuthGuard가 로그인 화면으로 전환하므로 localStorage만 정리
                localStorage.removeItem("isAuthenticated");
                return;
            }

            if (booksRes.ok) {
                const data: Flipbook[] = await booksRes.json();
                setBooks(data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()));
            }
            if (foldersRes.ok) {
                const fData: Folder[] = await foldersRes.json();
                setFolders(fData);
            }
        } catch {
            // 네트워크 오류는 조용히 처리 (사용자가 화면을 보고 있음)
        } finally {
            setIsLoadingData(false);
        }
    }, []);

    useEffect(() => {
        fetchAllData();
    }, [fetchAllData]);

    // 처리 중인 플립북 폴링
    useEffect(() => {
        const processingBooks = books.filter(b => b.page_count === 0 && b.status !== 'failed');
        if (processingBooks.length === 0) {
            pollDelay.current = 3000;
            return;
        }

        const timerId = setTimeout(async () => {
            const updatedBooks = [...books];
            let hasUpdates = false;

            await Promise.all(processingBooks.map(async (pb) => {
                try {
                    const res = await fetch(`/api/backend/flipbook/${pb.uuid_key}`);
                    if (!res.ok) return;
                    const updatedBook: Flipbook = await res.json();
                    if (updatedBook.page_count > 0 || updatedBook.status === 'failed') {
                        const idx = updatedBooks.findIndex(b => b.uuid_key === pb.uuid_key);
                        if (idx !== -1) {
                            updatedBooks[idx] = { ...updatedBooks[idx], ...updatedBook };
                            hasUpdates = true;
                        }
                    }
                } catch {
                    // 개별 폴링 실패는 무시
                }
            }));

            if (hasUpdates) {
                pollDelay.current = 3000;
                setBooks(updatedBooks);
            } else {
                pollDelay.current = Math.min(pollDelay.current * 1.5, 30000);
                setPollTrigger(prev => prev + 1);
            }
        }, pollDelay.current);

        return () => clearTimeout(timerId);
    }, [books, pollTrigger]);

    const handleUploadClick = useCallback(() => {
        fileInputRef.current?.click();
    }, []);

    const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploadLoading(true);
        const formData = new FormData();
        formData.append("file", file);

        const url = currentFolderId
            ? `/api/backend/upload?split_pages=${splitPages}&folder_id=${currentFolderId}`
            : `/api/backend/upload?split_pages=${splitPages}`;

        try {
            const res = await fetch(url, { method: "POST", body: formData });
            if (res.ok) {
                alert("🎉 PDF 업로드 및 변환이 완료되었습니다. 썸네일을 불러옵니다.");
                setTimeout(() => fetchAllData(), 5000);
            } else {
                alert("❌ 업로드 처리 실패가 발생했습니다.");
            }
        } catch {
            alert("❌ 통신 중 에러가 발생했습니다.");
        } finally {
            setUploadLoading(false);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    }, [currentFolderId, splitPages, fetchAllData]);

    const handleCreateFolder = useCallback(async () => {
        if (!newFolderName.trim()) return;
        try {
            const res = await fetch('/api/backend/folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newFolderName.trim() })
            });
            if (res.ok) {
                setNewFolderName("");
                setIsCreatingFolder(false);
                fetchAllData();
            } else {
                alert("❌ 폴더 생성 실패");
            }
        } catch {
            alert("❌ 통신 에러");
        }
    }, [newFolderName, fetchAllData]);

    const confirmDeleteFolder = useCallback(async () => {
        if (!deletingFolderId) return;
        try {
            const res = await fetch(`/api/backend/folder/${deletingFolderId}`, { method: 'DELETE' });
            if (res.ok) {
                setFolders(prev => prev.filter(f => f.id !== deletingFolderId));
                setBooks(prev => prev.filter(b => b.folder_id !== deletingFolderId));
                if (currentFolderId === deletingFolderId) setCurrentFolderId(null);
            } else {
                alert("❌ 폴더 삭제 실패");
            }
        } catch {
            alert("❌ 통신 에러");
        } finally {
            setDeletingFolderId(null);
        }
    }, [deletingFolderId, currentFolderId]);

    const confirmDeleteFile = useCallback(async () => {
        if (!deletingUuid) return;
        try {
            const res = await fetch(`/api/backend/flipbook/${deletingUuid}`, { method: "DELETE" });
            if (res.ok) {
                setBooks(prev => prev.filter(b => b.uuid_key !== deletingUuid));
            } else {
                alert("❌ 문서 삭제 실패");
            }
        } catch {
            alert("❌ 통신 에러");
        } finally {
            setDeletingUuid(null);
        }
    }, [deletingUuid]);

    const handleLogout = useCallback(async () => {
        await fetch('/api/backend/logout', { method: 'POST' });
        localStorage.removeItem("isAuthenticated");
        router.refresh();
    }, [router]);

    const filteredBooks = books.filter(b => (b.folder_id || null) === currentFolderId);

    return (
        <div style={styles.container}>
            {/* 사이드바 */}
            <div style={styles.sidebar}>
                <div style={styles.logoArea}>
                    <span style={styles.logoText}>JJFlipBook</span>
                </div>
                <div style={styles.sidebarMenu}>
                    <button style={{ ...styles.sidebarTab, ...styles.sidebarTabActive }} onClick={() => setCurrentFolderId(null)}>My Documents</button>
                    <button style={styles.sidebarTab} onClick={() => alert("개별 문서를 선택해 주세요")}>View</button>
                    {!isMobile && (
                        <button
                            style={{ ...styles.sidebarTab, marginTop: 'auto', color: '#e11d48', fontWeight: 600 }}
                            onClick={handleLogout}
                        >
                            🚪 로그아웃
                        </button>
                    )}
                </div>
            </div>

            {/* 대시보드 메인 */}
            <div style={styles.dashboardArea}>
                <div style={styles.dashHeader}>
                    <div>
                        <h1 style={styles.dashTitle}>
                            {currentFolderId
                                ? folders.find(f => f.id === currentFolderId)?.name || "폴더"
                                : "My Documents"}
                        </h1>
                        <p style={styles.dashSub}>
                            {currentFolderId ? "폴더 내 업로드된 문서를 관리합니다." : "문서 및 폴더 목록을 관리하고 읽어보세요."}
                        </p>
                    </div>
                    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', alignItems: isMobile ? 'stretch' : 'center', gap: '12px', width: isMobile ? '100%' : 'auto' }}>
                        {currentFolderId !== null && (
                            <button onClick={() => setCurrentFolderId(null)} style={{ ...styles.uploadBtn, backgroundColor: '#f1f3f4', color: '#1a1a1a' }}>
                                ← 최상위로
                            </button>
                        )}
                        {currentFolderId === null && (
                            <button onClick={() => setIsCreatingFolder(true)} style={{ ...styles.uploadBtn, backgroundColor: '#eef2ff', color: '#2563eb' }}>
                                + 새 폴더
                            </button>
                        )}
                        <label style={{ display: 'flex', alignItems: 'center', justifyContent: isMobile ? 'flex-start' : 'center', gap: '6px', cursor: 'pointer', fontSize: '14px', color: '#5f6368', background: isMobile ? '#f8fafc' : 'transparent', padding: isMobile ? '12px' : '0', borderRadius: isMobile ? '8px' : '0', width: isMobile ? '100%' : 'auto', boxSizing: 'border-box' }}>
                            <input type="checkbox" checked={splitPages} onChange={(e) => setSplitPages(e.target.checked)} style={{ cursor: 'pointer', width: '16px', height: '16px' }} />
                            2장 분할
                        </label>
                        <input type="file" accept=".pdf" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileChange} />
                        <button style={styles.uploadBtn} onClick={handleUploadClick} disabled={uploading}>
                            {uploading ? `업로드 중${uploadDots}` : "+ PDF 업로드"}
                        </button>
                    </div>
                </div>

                {isLoadingData ? (
                    <div style={styles.emptyState}>
                        <div style={styles.spinner}></div>
                        <p style={styles.emptyText}>데이터를 불러오는 중입니다...</p>
                    </div>
                ) : folders.length === 0 && filteredBooks.length === 0 ? (
                    <div style={styles.emptyState}>
                        <div style={{ fontSize: '48px' }}>📂</div>
                        <p style={styles.emptyText}>항목이 비어있습니다. 폴더를 생성하거나 pdf를 투입해주세요!</p>
                    </div>
                ) : (
                    <div style={styles.gridContainer}>
                        {currentFolderId === null && folders.map(folder => (
                            <FolderCard
                                key={folder.id}
                                folder={folder}
                                isMobile={isMobile}
                                onOpen={setCurrentFolderId}
                                onDelete={setDeletingFolderId}
                            />
                        ))}
                        {filteredBooks.map(book => (
                            <FlipbookCard
                                key={book.id}
                                book={book}
                                isMobile={isMobile}
                                onDelete={setDeletingUuid}
                                onOpen={(uuid) => router.push(`/view/${uuid}`)}
                            />
                        ))}
                    </div>
                )}

                {isMobile && (
                    <div style={{ marginTop: '32px', display: 'flex', justifyContent: 'center' }}>
                        <button
                            style={{ padding: '12px 24px', width: '100%', backgroundColor: '#fff0f2', color: '#e11d48', border: '1px solid #ffe4e6', borderRadius: '8px', fontWeight: 600, fontSize: '15px', cursor: 'pointer' }}
                            onClick={handleLogout}
                        >
                            🚪 로그아웃
                        </button>
                    </div>
                )}
            </div>

            {/* 모달들 */}
            {isCreatingFolder && (
                <CreateFolderModal
                    folderName={newFolderName}
                    onFolderNameChange={setNewFolderName}
                    onSubmit={handleCreateFolder}
                    onCancel={() => { setIsCreatingFolder(false); setNewFolderName(''); }}
                />
            )}

            {deletingFolderId !== null && (
                <ConfirmModal
                    title="폴더 삭제"
                    message="이 폴더와 안에 담긴 모든 PDF 문서를 영구적으로 삭제하시겠습니까? (이 작업은 되돌릴 수 없습니다!)"
                    confirmLabel="완전 삭제"
                    confirmDanger
                    onConfirm={confirmDeleteFolder}
                    onCancel={() => setDeletingFolderId(null)}
                />
            )}

            {deletingUuid !== null && (
                <ConfirmModal
                    title="문서 삭제"
                    message="정말 이 문서를 삭제하시겠습니까? 관련 데이터가 모두 소멸됩니다."
                    confirmLabel="삭제하기"
                    confirmDanger
                    onConfirm={confirmDeleteFile}
                    onCancel={() => setDeletingUuid(null)}
                />
            )}
        </div>
    );
}

const getStyles = (isMobile: boolean): Record<string, React.CSSProperties> => ({
    container: { display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100dvh', width: '100vw', backgroundColor: '#f4f6f8', color: '#1a1a1a', fontFamily: 'system-ui, -apple-system, sans-serif', overflowX: 'hidden' },
    sidebar: { width: isMobile ? '100%' : '220px', backgroundColor: 'white', borderRight: isMobile ? 'none' : '1px solid #e4e7eb', borderBottom: isMobile ? '1px solid #e4e7eb' : 'none', display: 'flex', flexDirection: isMobile ? 'row' : 'column', padding: isMobile ? '16px' : '32px 16px', boxSizing: 'border-box', gap: isMobile ? '16px' : '32px', zIndex: 10, alignItems: isMobile ? 'center' : 'stretch' },
    logoArea: { display: 'flex', alignItems: 'center', paddingBottom: isMobile ? '0' : '16px', borderBottom: isMobile ? 'none' : '1px solid #f1f3f5', marginLeft: '8px' },
    logoText: { fontSize: '20px', fontWeight: 'bold', color: '#1a1a1a', letterSpacing: '-0.5px' },
    sidebarMenu: { display: 'flex', flexDirection: isMobile ? 'row' : 'column', gap: '8px', flex: isMobile ? 'none' : 1, width: isMobile ? 'auto' : '100%', marginLeft: isMobile ? 'auto' : '0' },
    sidebarTab: { background: 'none', border: 'none', fontSize: '15px', color: '#4b5563', cursor: 'pointer', padding: '12px 16px', borderRadius: '10px', textAlign: 'left', fontWeight: 500, transition: 'all 0.2s', width: isMobile ? 'auto' : '100%' },
    sidebarTabActive: { backgroundColor: '#eef2ff', color: '#2563eb', fontWeight: 600 },
    dashboardArea: { flex: 1, padding: isMobile ? '24px' : '40px 60px', overflowY: 'auto' },
    dashHeader: { display: 'flex', flexDirection: isMobile ? 'column' : 'row', justifyContent: 'space-between', alignItems: isMobile ? 'flex-start' : 'center', marginBottom: '32px', gap: isMobile ? '16px' : '0', flexWrap: 'wrap' },
    dashTitle: { fontSize: '24px', fontWeight: 'bold', margin: '0 0 4px 0', color: '#1a1a1a' },
    dashSub: { fontSize: '14px', color: '#5f6368', margin: 0 },
    uploadBtn: { padding: '12px 24px', backgroundColor: '#1a73e8', color: 'white', border: 'none', borderRadius: '24px', fontWeight: 500, cursor: 'pointer', boxShadow: '0 4px 6px rgba(26, 115, 232, 0.2)', transition: 'all 0.2s', width: isMobile ? '100%' : 'auto' },
    gridContainer: { display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? '140px' : '200px'}, 1fr))`, gap: isMobile ? '16px' : '32px' },
    emptyState: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '300px', gap: '16px' },
    emptyText: { color: '#5f6368', fontSize: '15px' },
    spinner: { width: '24px', height: '24px', border: '3px solid #f3f3f3', borderTop: '3px solid #1a73e8', borderRadius: '50%', animation: 'spin 1s linear infinite' },
});
