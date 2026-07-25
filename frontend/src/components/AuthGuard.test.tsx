import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import AuthGuard from './AuthGuard'

// Mock next/navigation
jest.mock('next/navigation', () => ({
    usePathname: () => '/',
}))

describe('AuthGuard Unit Tests', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
    })

    it('renders the children if authentication passes', async () => {
        // Mock successful login state in localStorage
        localStorage.setItem('isAuthenticated', 'true')

        render(<AuthGuard><div>Protected Content</div></AuthGuard>)
        
        await waitFor(() => {
            expect(screen.getByText('Protected Content')).toBeInTheDocument()
        })
    })

    it('shows login screen if not authenticated', async () => {
        // Mock unauthenticated state
        localStorage.removeItem('isAuthenticated')

        render(<AuthGuard><div>Protected Content</div></AuthGuard>)
        
        await waitFor(() => {
            expect(screen.getByText('JJFlipBook 로그인')).toBeInTheDocument()
            expect(screen.queryByText('Protected Content')).not.toBeInTheDocument()
        })
    })
})
