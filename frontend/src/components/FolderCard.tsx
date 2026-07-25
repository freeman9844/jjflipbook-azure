"use client";

import React from 'react';

export interface Folder {
    id: string;
    name: string;
    created_at: string;
}

interface FolderCardProps {
    folder: Folder;
    isMobile: boolean;
    onOpen: (id: string) => void;
    onDelete: (id: string) => void;
}

export default function FolderCard({ folder, isMobile, onOpen, onDelete }: FolderCardProps) {
    const cardStyle: React.CSSProperties = {
        backgroundColor: '#f8fafc',
        border: '1px solid #e2e8f0',
        borderRadius: '12px',
        overflow: 'hidden',
        boxShadow: '0 4px 12px rgba(0,0,0,0.04)',
        cursor: 'pointer',
        transition: 'transform 0.2s, box-shadow 0.2s',
        position: 'relative',
    };

    const coverStyle: React.CSSProperties = {
        height: isMobile ? '120px' : '160px',
        background: 'transparent',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderBottom: '1px solid #f0f0f0',
    };

    return (
        <div style={cardStyle} onClick={() => onOpen(folder.id)}>
            <button
                style={deleteBtnStyle}
                onClick={(e) => { e.stopPropagation(); onDelete(folder.id); }}
                title="폴더 삭제"
            >
                <TrashIcon />
            </button>
            <div style={coverStyle}>
                <span style={{ fontSize: '56px' }}>📁</span>
            </div>
            <div style={cardInfoStyle}>
                <h4 style={cardTitleStyle}>{folder.name}</h4>
                <p style={cardSubStyle}>
                    {folder.created_at ? folder.created_at.split('T')[0].replace(/-/g, '/') : ''}
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
