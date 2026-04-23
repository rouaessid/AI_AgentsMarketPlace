import { useState, useRef, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Cpu, Store, LayoutDashboard, Wallet, Menu, X, Zap, LogOut, Copy, Check,
  ChevronDown, ShoppingBag, Sparkles
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

const NAV_BUYER = [
  { to: '/marketplace', label: 'Marketplace', icon: Store },
  { to: '/solutions', label: 'Orchestrator', icon: Sparkles }
]
const NAV_PROVIDER = [
  { to: '/marketplace', label: 'Marketplace', icon: Store },
  { to: '/solutions', label: 'Orchestrator', icon: Sparkles },
  { to: '/seller', label: 'My Agents', icon: LayoutDashboard },
]

export default function Navbar() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, walletAddress, isLoggedIn, isProvider, logout,
    connectWallet, disconnectWallet, openAuthModal, switchRole } = useAuth()

  const [open, setOpen] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [copied, setCopied] = useState(false)
  const menuRef = useRef(null)
  const NAV = isProvider ? NAV_PROVIDER : NAV_BUYER

  useEffect(() => {
    const h = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setShowMenu(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function copyAddress() {
    if (!walletAddress) return
    navigator.clipboard.writeText(walletAddress)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  function handleLogout() { logout(); setShowMenu(false); navigate('/') }

  const short = walletAddress ? `${walletAddress.slice(0, 6)}…${walletAddress.slice(-4)}` : null
  const roleColor = isProvider ? '#7c3aed' : '#6366f1'
  const RoleIcon = isProvider ? Cpu : ShoppingBag

  return (
    <header className="fixed inset-x-0 top-0 z-50 bg-white/90 backdrop-blur-xl border-b border-am-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">

        {/* Logo */}
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
            <Cpu size={15} className="text-white" />
          </div>
          <span className="font-bold text-am-text text-sm tracking-wide">
            Agent<span className="text-am-indigo">Market</span>
          </span>
          <span className="hidden sm:flex badge-indigo items-center gap-1 ml-1">
            <Zap size={9} /> ERC-8004
          </span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-1">
          {NAV.map(({ to, label, icon: Icon }) => {
            const active = pathname.startsWith(to)
            return (
              <Link key={to} to={to}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${active
                    ? 'bg-indigo-50 text-am-indigo-d border border-indigo-200/80'
                    : 'text-am-text-2 hover:text-am-text hover:bg-am-surface'
                  }`}
              >
                <Icon size={15} /> {label}
              </Link>
            )
          })}
        </nav>

        {/* Right */}
        <div className="flex items-center gap-2">
          {isLoggedIn ? (
            <div className="relative hidden sm:block" ref={menuRef}>
              <button onClick={() => setShowMenu(m => !m)}
                className="flex items-center gap-2.5 text-sm font-medium px-3 py-2 rounded-xl border border-am-border bg-am-surface hover:bg-white hover:shadow-card transition-all duration-200"
              >
                <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
                  style={{ background: `linear-gradient(135deg,${roleColor},#6366f1)` }}>
                  {(user.name || 'U').charAt(0).toUpperCase()}
                </div>
                <span className="text-am-text max-w-[100px] truncate">{user.name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium border"
                  style={{ background: `${roleColor}10`, color: roleColor, borderColor: `${roleColor}30` }}>
                  {isProvider ? 'Provider' : 'Buyer'}
                </span>
                <ChevronDown size={12} className="text-am-muted" />
              </button>

              <AnimatePresence>
                {showMenu && (
                  <motion.div
                    initial={{ opacity: 0, y: 6, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 6, scale: 0.97 }}
                    transition={{ duration: 0.15 }}
                    className="absolute right-0 top-full mt-2 w-64 bg-white rounded-2xl border border-am-border shadow-card-lg overflow-hidden"
                  >
                    {/* User info */}
                    <div className="px-4 py-3.5 border-b border-am-border">
                      <div className="font-semibold text-am-text text-sm">{user.name}</div>
                      {user.email && <div className="text-xs text-am-muted mt-0.5">{user.email}</div>}
                      <div className="flex items-center gap-1.5 mt-2">
                        <RoleIcon size={11} style={{ color: roleColor }} />
                        <span className="text-xs font-medium" style={{ color: roleColor }}>
                          {isProvider ? 'Provider' : 'Buyer'}
                        </span>
                      </div>
                    </div>

                    {/* Wallet */}
                    <div className="px-4 py-3 border-b border-am-border">
                      {walletAddress ? (
                        <>
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <span className="w-2 h-2 rounded-full bg-am-emerald animate-pulse-slow" />
                            <span className="text-xs text-am-emerald font-medium">Wallet connected</span>
                          </div>
                          <div className="flex items-center justify-between bg-am-surface rounded-lg px-3 py-2">
                            <span className="text-xs font-mono text-am-text-2">{short}</span>
                            <button onClick={copyAddress} className="text-am-muted hover:text-am-text transition-colors">
                              {copied ? <Check size={13} className="text-am-emerald" /> : <Copy size={13} />}
                            </button>
                          </div>
                          <button onClick={() => { disconnectWallet(); setShowMenu(false) }}
                            className="text-xs text-am-muted hover:text-am-rose transition-colors mt-1.5 block">
                            Disconnect wallet
                          </button>
                        </>
                      ) : (
                        <button onClick={() => { connectWallet(); setShowMenu(false) }}
                          className="flex items-center gap-2 text-xs text-am-indigo hover:opacity-80 transition-opacity py-1 font-medium">
                          <Wallet size={13} /> Connect MetaMask
                        </button>
                      )}
                    </div>

                    {/* Switch role */}
                    <div className="px-2 py-2 border-b border-am-border">
                      <div className="text-xs text-am-muted px-2 mb-1.5 font-medium">Switch role</div>
                      {[
                        { v: 'buyer', label: 'Buyer', icon: ShoppingBag, color: '#6366f1' },
                        { v: 'provider', label: 'Provider', icon: Cpu, color: '#7c3aed' },
                      ].map(({ v, label, icon: Icon, color }) => (
                        <button key={v}
                          onClick={() => { switchRole(v); setShowMenu(false) }}
                          className={`w-full flex items-center gap-2.5 px-2 py-2 rounded-xl text-sm transition-all ${user.role === v ? 'font-medium' : 'text-am-text-2 hover:text-am-text hover:bg-am-surface'
                            }`}
                          style={user.role === v ? { background: `${color}08`, color } : {}}
                        >
                          <Icon size={13} style={{ color: user.role === v ? color : undefined }} />
                          {label}
                          {user.role === v && <Check size={11} className="ml-auto" style={{ color }} />}
                        </button>
                      ))}
                    </div>

                    <button onClick={handleLogout}
                      className="w-full flex items-center gap-3 px-4 py-3 text-sm text-am-rose/80 hover:text-am-rose hover:bg-rose-50 transition-colors">
                      <LogOut size={14} /> Sign out
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ) : (
            <div className="hidden sm:flex items-center gap-2">
              <button onClick={() => openAuthModal('login')} className="btn-ghost text-sm">
                Sign In
              </button>
              <button onClick={() => openAuthModal('signup')} className="btn-primary text-sm">
                Get Started
              </button>
            </div>
          )}

          <button className="md:hidden text-am-text-2 hover:text-am-text p-1" onClick={() => setOpen(!open)}>
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="md:hidden bg-white border-t border-am-border px-4 py-3 space-y-1"
          >
            {NAV.map(({ to, label, icon: Icon }) => (
              <Link key={to} to={to} onClick={() => setOpen(false)}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-am-text-2 hover:text-am-text hover:bg-am-surface">
                <Icon size={15} /> {label}
              </Link>
            ))}
            {isLoggedIn ? (
              <>
                <div className="px-3 py-2 text-xs text-am-muted">{user.name} · {user.role}</div>
                <button onClick={handleLogout}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-am-rose/80 hover:text-am-rose hover:bg-rose-50">
                  <LogOut size={15} /> Sign out
                </button>
              </>
            ) : (
              <>
                <button onClick={() => { openAuthModal('login'); setOpen(false) }}
                  className="w-full text-left px-3 py-2.5 rounded-xl text-sm text-am-text-2 hover:bg-am-surface">
                  Sign In
                </button>
                <button onClick={() => { openAuthModal('signup'); setOpen(false) }}
                  className="w-full btn-primary text-center mt-1">
                  Get Started
                </button>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}
