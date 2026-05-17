import { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)
const STORAGE_KEY = 'agentmarket_auth'

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? JSON.parse(saved) : null
    } catch { return null }
  })
  const [authModal, setAuthModal]   = useState({ open: false })
  const [connecting, setConnecting] = useState(false)

  useEffect(() => {
    if (auth) localStorage.setItem(STORAGE_KEY, JSON.stringify(auth))
    else localStorage.removeItem(STORAGE_KEY)
  }, [auth])

  // Logout when MetaMask account switches or disconnects
  useEffect(() => {
    if (!window.ethereum) return
    function handleAccountsChanged(accounts) {
      if (accounts.length === 0) {
        logout()
      } else if (auth && accounts[0].toLowerCase() !== auth.wallet) {
        logout()
      }
    }
    window.ethereum.on('accountsChanged', handleAccountsChanged)
    return () => window.ethereum.removeListener('accountsChanged', handleAccountsChanged)
  }, [auth])

  async function connectWallet() {
    if (!window.ethereum) {
      alert('MetaMask not detected. Please install MetaMask.')
      return null
    }
    setConnecting(true)
    try {
      // 1. Request account
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      if (!accounts.length) return null
      const wallet = accounts[0].toLowerCase()

      // 2. Get nonce + message from backend
      const nonceRes = await fetch(`/api/v1/auth/nonce?wallet=${encodeURIComponent(wallet)}`)
      if (!nonceRes.ok) throw new Error('Failed to get nonce')
      const { message } = await nonceRes.json()

      // 3. Sign message with MetaMask (personal_sign)
      const signature = await window.ethereum.request({
        method: 'personal_sign',
        params: [message, wallet],
      })

      // 4. Verify signature → JWT + roles
      const verifyRes = await fetch('/api/v1/auth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wallet, signature }),
      })
      if (!verifyRes.ok) throw new Error('Signature verification failed')
      const { token, roles } = await verifyRes.json()

      const newAuth = { wallet, token, isProvider: roles.isProvider, isBuyer: roles.isBuyer }
      setAuth(newAuth)
      return newAuth
    } catch (e) {
      if (e.code !== 4001) console.error('SIWE error:', e)
      throw e
    } finally {
      setConnecting(false)
    }
  }

  function logout() {
    setAuth(null)
    localStorage.removeItem(STORAGE_KEY)
  }

  function openAuthModal() { setAuthModal({ open: true }) }
  function closeAuthModal() { setAuthModal({ open: false }) }

  const walletAddress = auth?.wallet ?? null
  const user = auth
    ? {
        wallet: auth.wallet,
        name: `${auth.wallet.slice(0, 6)}…${auth.wallet.slice(-4)}`,
        email: null,
      }
    : null

  return (
    <AuthContext.Provider value={{
      user,
      walletAddress,
      token:       auth?.token ?? null,
      isLoggedIn:  !!auth,
      isProvider:  auth?.isProvider ?? false,
      isBuyer:     auth?.isBuyer    ?? false,
      connecting,
      connectWallet,
      logout,
      openAuthModal,
      closeAuthModal,
      authModal,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
