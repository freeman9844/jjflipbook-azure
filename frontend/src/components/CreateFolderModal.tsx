"use client";

import React from 'react';

interface CreateFolderModalProps {
    folderName: string;
    onFolderNameChange: (name: string) => void;
    onSubmit: () => void;
    onCancel: () => void;
}

export default function CreateFolderModal({
    folderName,
    onFolderNameChange,
    onSubmit,
    onCancel,
}: CreateFolderModalProps) {
    return (
        <div style={backdropStyle}>
            <div style={contentStyle}>
                <h3 style={{ margin: '0 0 12px 0', fontSize: '18px', color: '#1a1a1a' }}>새 폴더 만들기</h3>
                <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#5f6368' }}>폴더 이름을 입력해주세요.</p>
                <input
                    type="text"
                    style={inputStyle}
                    value={folderName}
                    onChange={(e) => onFolderNameChange(e.target.value)}
                    placeholder="폴더 이름"
                    autoFocus
                    onKeyDown={(e) => { if (e.key === 'Enter') onSubmit(); }}
                />
                <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                    <button onClick={onCancel} style={cancelBtnStyle}>취소</button>
                    <button onClick={onSubmit} style={primaryBtnStyle}>생성하기</button>
                </div>
            </div>
        </div>
    );
}

const backdropStyle: React.CSSProperties = {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '100vw',
    height: '100vh',
    backgroundColor: 'rgba(0,0,0,0.4)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 100,
};

const contentStyle: React.CSSProperties = {
    backgroundColor: 'white',
    padding: '24px',
    borderRadius: '12px',
    width: '360px',
    boxShadow: '0 12px 36px rgba(0,0,0,0.15)',
    display: 'flex',
    flexDirection: 'column',
};

const inputStyle: React.CSSProperties = {
    padding: '10px',
    borderRadius: '6px',
    border: '1px solid #ddd',
    marginBottom: '24px',
    width: '100%',
    boxSizing: 'border-box',
    fontSize: '14px',
};

const cancelBtnStyle: React.CSSProperties = {
    padding: '8px 16px',
    backgroundColor: '#f1f3f4',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
};

const primaryBtnStyle: React.CSSProperties = {
    padding: '8px 16px',
    backgroundColor: '#1a73e8',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
};
