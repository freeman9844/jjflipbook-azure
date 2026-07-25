"use client";

import React from 'react';

interface ConfirmModalProps {
    title: string;
    message: string;
    confirmLabel: string;
    confirmDanger?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
}

export default function ConfirmModal({
    title,
    message,
    confirmLabel,
    confirmDanger = false,
    onConfirm,
    onCancel,
}: ConfirmModalProps) {
    return (
        <div style={backdropStyle}>
            <div style={contentStyle}>
                <h3 style={{ margin: '0 0 12px 0', fontSize: '18px', color: '#1a1a1a' }}>{title}</h3>
                <p style={{ margin: '0 0 24px 0', fontSize: '14px', color: confirmDanger ? '#e11d48' : '#5f6368', fontWeight: confirmDanger ? 600 : 400 }}>
                    {message}
                </p>
                <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                    <button onClick={onCancel} style={cancelBtnStyle}>취소</button>
                    <button
                        onClick={onConfirm}
                        style={confirmDanger ? dangerBtnStyle : primaryBtnStyle}
                    >
                        {confirmLabel}
                    </button>
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

const dangerBtnStyle: React.CSSProperties = {
    padding: '8px 16px',
    backgroundColor: '#e11d48',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    fontSize: '14px',
};
