"use client";

import React from 'react';
import Image from 'next/image';

export interface Flipbook {
    id: string;
    uuid_key: string;
    title: string;
    page_count: number;
    image_urls?: string[];
    status?: string;
    folder_id?: string | null;
    created_at: string;
}

interface FlipbookCardProps {
    book: Flipbook;
    isMobile: boolean;
    onDelete: (uuid: string) => void;
    onOpen: (uuid: string) => void;
}

export default function FlipbookCard({ book, isMobile, onDelete, onOpen }: FlipbookCardProps) {
    const coverUrl = book.image_urls && book.image_urls.length > 0 ? book.image_urls[0] : null;
    const isFailed = book.status === 'failed';
    const isProcessing = book.page_count === 0 && !isFailed;

    const cardStyle: React.CSSProperties = {
        backgroundColor: 'white',
        borderRadius: '12px',
        overflow: 'hidden',
        boxShadow: '0 4px 12px rgba(0,0,0,0.04)',
        cursor: isProcessing ? 'not-allowed' : 'pointer',
        transition: 'transform 0.2s, box-shadow 0.2s',
        position: 'relative',
        opacity: isProcessing ? 0.75 : 1,
    };

    const coverStyle: React.CSSProperties = {
        height: isMobile ? '180px' : '260px',
        backgroundColor: '#f5f5f5',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderBottom: '1px solid #f0f0f0',
        position: 'relative',
        overflow: 'hidden',
    };

    return (
        <div
            style={cardStyle}
            onClick={() => { if (!isProcessing && !isFailed) onOpen(book.uuid_key); }}
        >
            <button
                style={deleteBtnStyle}
                onClick={(e) => { e.stopPropagation(); onDelete(book.uuid_key); }}
                title="문서 삭제"
            >
                <TrashIcon />
            </button>

            {isProcessing && (
                <div style={overlayStyle}>
                    <div style={spinnerStyle}></div>
                    <span style={processingTextStyle}>변환 처리 중...</span>
                </div>
            )}

            {isFailed && (
                <div style={overlayStyle}>
                    <span style={{ fontSize: '24px' }}>❌</span>
                    <span style={{ ...processingTextStyle, color: '#ef4444' }}>변환 실패</span>
                </div>
            )}

            <div style={coverStyle}>
                {coverUrl ? (
                    <Image
                        src={coverUrl}
                        alt={book.title}
                        fill
                        style={{ objectFit: 'cover' }}
                        sizes="(max-width: 768px) 100vw, 33vw"
                    />
                ) : (
                    <span style={{ fontSize: '32px' }}>📖</span>
                )}
            </div>

            <div style={cardInfoStyle}>
                <h4 style={cardTitleStyle}>{book.title}</h4>
                <p style={cardSubStyle}>
                    {isProcessing
                        ? '분석 중...'
                        : `${book.created_at ? book.created_at.split('T')[0].replace(/-/g, '/') : ''} | 페이지 수: ${book.page_count}p`}
                </p>
            </div>
        </div>
    );
}

function TrashIcon() {
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
    );
}

const deleteBtnStyle: React.CSSProperties = {
    position: 'absolute',
    top: '12px',
    right: '12px',
    width: '28px',
    height: '28px',
    borderRadius: '50%',
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    border: '1px solid #f1f3f4',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    zIndex: 12,
    boxShadow: '0 2px 6px rgba(0,0,0,0.08)',
    transition: 'all 0.2s',
};

const overlayStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    backgroundColor: 'rgba(255, 255, 255, 0.8)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
    borderRadius: '12px',
    gap: '12px',
};

const spinnerStyle: React.CSSProperties = {
    width: '24px',
    height: '24px',
    border: '3px solid #f3f3f3',
    borderTop: '3px solid #1a73e8',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
};

const processingTextStyle: React.CSSProperties = {
    fontSize: '14px',
    color: '#1a73e8',
    fontWeight: 600,
};

const cardInfoStyle: React.CSSProperties = { padding: '16px' };
const cardTitleStyle: React.CSSProperties = {
    fontSize: '15px',
    fontWeight: 600,
    color: '#1a1a1a',
    margin: '0 0 4px 0',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
};
const cardSubStyle: React.CSSProperties = { fontSize: '12px', color: '#5f6368', margin: 0 };
