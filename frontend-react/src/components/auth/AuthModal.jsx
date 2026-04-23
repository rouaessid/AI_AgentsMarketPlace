import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Wallet, Mail, Eye, EyeOff, Cpu, ShoppingBag, ArrowRight, Check, Zap } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

export default function AuthModal() {
  const { authModal, closeAuthModal, login, connectWallet } = useAuth()
  const { open, defaultTab } = authModal

  const [tab,      setTab]      = useState(defaultTab || 'login')
  const [role,     setRole]     = useState('buyer')
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [name,     setName]     = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  if (!open) return null

  function reset() {
    setError(''); setEmail(''); setPassword(''); setName(''); setRole('buyer'); setTab('login')
  }
  function handleClose() { reset(); closeAuthModal() }

  async function handleWalletLogin() {
    setLoading(true); setError('')
    try {
      const address = await connectWallet()
      if (address) {
        login({ id: address, name: `${address.slice(0,6)}…${address.slice(-4)}`,
                email: null, role, wallet: address, authType: 'wallet', avatar: null })
        handleClose()
      }
    } catch (e) { setError(e.message) }
    setLoading(false)
  }

  async function handleEmailSubmit(e) {
    e.preventDefault(); setError('')
    if (!email || !password) { setError('Please fill all fields.'); return }
    if (tab === 'signup' && !name) { setError('Name is required.'); return }
    if (password.length < 6) { setError('Password must be at least 6 characters.'); return }
    setLoading(true)
    await new Promise(r => setTimeout(r, 600))
    login({ id: email, name: tab === 'signup' ? name : email.split('@')[0],
            email, role, wallet: null, authType: 'email', avatar: null })
    setLoading(false)
    handleClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={handleClose}
            className="fixed inset-0 z-50 bg-am-text/40 backdrop-blur-sm" />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 16 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
          >
            <div className="relative w-full max-w-md bg-white rounded-3xl shadow-card-lg border border-am-border pointer-events-auto overflow-hidden">

              {/* Top accent */}
              <div className="h-1 w-full" style={{ background: 'linear-gradient(90deg,#6366f1,#8b5cf6,#0ea5e9)' }} />

              <button onClick={handleClose}
                className="absolute top-4 right-4 text-am-muted hover:text-am-text transition-colors z-10 p-1 rounded-lg hover:bg-am-surface">
                <X size={18} />
              </button>

              <div className="p-7">
                {/* Logo */}
                <div className="flex items-center gap-2 mb-6">
                  <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
                    <Cpu size={15} className="text-white" />
                  </div>
                  <span className="font-bold text-am-text text-sm">
                    Agent<span className="text-am-indigo">Market</span>
                  </span>
                  <span className="badge-indigo ml-1"><Zap size={9} /> ERC-8004</span>
                </div>

                {/* Tab switcher */}
                <div className="flex gap-1 p-1 rounded-xl bg-am-surface border border-am-border mb-6">
                  {['login', 'signup'].map(t => (
                    <button key={t} onClick={() => { setTab(t); setError('') }}
                      className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-all ${
                        t === tab
                          ? 'bg-white text-am-text shadow-card border border-am-border'
                          : 'text-am-muted hover:text-am-text-2'
                      }`}>
                      {t === 'login' ? 'Sign In' : 'Sign Up'}
                    </button>
                  ))}
                </div>

                {/* Role selector */}
                <div className="mb-5">
                  <div className="text-xs font-semibold text-am-muted uppercase tracking-wider mb-2.5">I am a…</div>
                  <div className="grid grid-cols-2 gap-2.5">
                    {[
                      { v: 'buyer',    label: 'Buyer',    sub: 'Hire AI agents',   icon: ShoppingBag, color: '#6366f1' },
                      { v: 'provider', label: 'Provider', sub: 'Deploy AI agents', icon: Cpu,         color: '#7c3aed' },
                    ].map(({ v, label, sub, icon: Icon, color }) => (
                      <button key={v} onClick={() => setRole(v)}
                        className={`relative flex items-center gap-3 p-3 rounded-xl border-2 text-left transition-all duration-200 ${
                          role === v ? 'shadow-card' : 'border-am-border text-am-text-2 hover:border-am-indigo/20 hover:bg-indigo-50/40'
                        }`}
                        style={role === v ? { borderColor: color, background: `${color}06` } : {}}
                      >
                        <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                          style={{ background: `${color}12`, border: `1.5px solid ${color}25` }}>
                          <Icon size={15} style={{ color }} />
                        </div>
                        <div>
                          <div className="text-sm font-semibold" style={role === v ? { color } : {}}>{label}</div>
                          <div className="text-xs text-am-muted mt-0.5">{sub}</div>
                        </div>
                        {role === v && (
                          <div className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center"
                            style={{ background: color }}>
                            <Check size={10} className="text-white" />
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div className="mb-4 px-3 py-2.5 rounded-xl text-sm text-am-rose bg-rose-50 border border-rose-200">
                    {error}
                  </div>
                )}

                {/* Wallet connect */}
                <button onClick={handleWalletLogin} disabled={loading}
                  className="w-full flex items-center justify-center gap-2.5 py-3 rounded-xl font-semibold text-sm mb-4
                             border-2 border-am-indigo/25 text-am-indigo bg-indigo-50/60 hover:bg-indigo-50
                             transition-all duration-200 disabled:opacity-50">
                  <Wallet size={16} />
                  {tab === 'login' ? 'Sign in with Wallet' : 'Sign up with Wallet'}
                </button>

                {/* Divider */}
                <div className="flex items-center gap-3 mb-4">
                  <div className="flex-1 h-px bg-am-border" />
                  <span className="text-xs text-am-muted">or continue with email</span>
                  <div className="flex-1 h-px bg-am-border" />
                </div>

                {/* Email form */}
                <form onSubmit={handleEmailSubmit} className="space-y-3">
                  {tab === 'signup' && (
                    <div>
                      <label htmlFor="auth-name" className="text-xs font-medium text-am-text-2 mb-1.5 block">Full Name</label>
                      <input id="auth-name" type="text" placeholder="Satoshi Nakamoto" value={name}
                        onChange={e => setName(e.target.value)} className="input" />
                    </div>
                  )}
                  <div>
                    <label htmlFor="auth-email" className="text-xs font-medium text-am-text-2 mb-1.5 block">Email</label>
                    <div className="relative">
                      <Mail size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-am-muted" />
                      <input id="auth-email" type="email" placeholder="you@example.com" value={email}
                        onChange={e => setEmail(e.target.value)} className="input pl-9" />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="auth-password" className="text-xs font-medium text-am-text-2 mb-1.5 block">Password</label>
                    <div className="relative">
                      <input id="auth-password" type={showPass ? 'text' : 'password'} placeholder="••••••••"
                        value={password} onChange={e => setPassword(e.target.value)} className="input pr-10" />
                      <button type="button" onClick={() => setShowPass(s => !s)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-am-muted hover:text-am-text transition-colors">
                        {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>

                  <button type="submit" disabled={loading}
                    className="w-full btn-primary justify-center py-3 rounded-xl text-sm mt-1 disabled:opacity-50">
                    {loading ? (
                      <span className="flex items-center gap-2">
                        <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                        {tab === 'login' ? 'Signing in…' : 'Creating account…'}
                      </span>
                    ) : (
                      <span className="flex items-center gap-2">
                        {tab === 'login' ? 'Sign In' : 'Create Account'}
                        <ArrowRight size={14} />
                      </span>
                    )}
                  </button>
                </form>

                <p className="text-center text-xs text-am-muted mt-4">
                  {tab === 'login' ? "Don't have an account? " : 'Already have an account? '}
                  <button onClick={() => { setTab(tab === 'login' ? 'signup' : 'login'); setError('') }}
                    className="text-am-indigo hover:underline font-medium">
                    {tab === 'login' ? 'Sign up' : 'Sign in'}
                  </button>
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
