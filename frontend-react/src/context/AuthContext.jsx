import { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('agentmarket_user')
      return saved ? JSON.parse(saved) : null
    } catch { return null }
  })

  const [walletAddress, setWalletAddress] = useState(null)
  const [authModal, setAuthModal] = useState({ open: false, defaultTab: 'login' })

  // Persist user to localStorage
  useEffect(() => {
    if (user) localStorage.setItem('agentmarket_user', JSON.stringify(user))
    else localStorage.removeItem('agentmarket_user')
  }, [user])

  // Auto-reconnect wallet if previously connected
  useEffect(() => {
    async function tryReconnect() {
      if (window.ethereum === undefined) return
      try {
        const accounts = await window.ethereum.request({ method: 'eth_accounts' })
        if (accounts.length > 0) setWalletAddress(accounts[0])
      } catch {}
    }
    tryReconnect()
  }, [])

  function login(userData) {
    setUser(userData)
  }

  function logout() {
    setUser(null)
    setWalletAddress(null)
    localStorage.removeItem('agentmarket_user')
  }

  function switchRole(role) {
    if (!user) return
    const updated = { ...user, role }
    setUser(updated)
  }

  async function connectWallet() {
    if (window.ethereum === undefined) {
      alert('MetaMask not detected. Please install MetaMask.')
      return null
    }
    try {
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      if (accounts.length > 0) {
        setWalletAddress(accounts[0])
        // If user logged in, attach wallet to their account
        if (user) setUser(u => ({ ...u, wallet: accounts[0] }))
        return accounts[0]
      }
    } catch (e) {
      if (e.code !== 4001) alert(`Wallet error: ${e.message}`)
    }
    return null
  }

  function disconnectWallet() {
    setWalletAddress(null)
    if (user) setUser(u => { const { wallet, ...rest } = u; return rest })
  }

  function openAuthModal(tab = 'login') {
    setAuthModal({ open: true, defaultTab: tab })
  }

  function closeAuthModal() {
    setAuthModal({ open: false, defaultTab: 'login' })
  }

  return (
    <AuthContext.Provider value={{
      user,
      walletAddress,
      isLoggedIn:  !!user,
      isProvider:  user?.role === 'provider',
      isBuyer:     user?.role === 'buyer',
      login,
      logout,
      switchRole,
      connectWallet,
      disconnectWallet,
      authModal,
      openAuthModal,
      closeAuthModal,
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
