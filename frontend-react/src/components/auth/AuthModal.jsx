import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Wallet, Cpu, Zap, ShieldCheck } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

export default function AuthModal() {
  const { authModal, closeAuthModal, connectWallet } = useAuth()
  const { open } = authModal

  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  if (!open) return null

  async function handleConnect() {
    setLoading(true)
    setError('')
    try {
      await connectWallet()
      closeAuthModal()
    } catch (e) {
      if (e.code !== 4001) setError(e.message || 'Connection failed. Please try again.')
    }
    setLoading(false)
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={closeAuthModal}
            className="fixed inset-0 z-50 bg-am-text/40 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 16 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
          >
            <div className="relative w-full max-w-sm bg-white rounded-3xl shadow-card-lg border border-am-border pointer-events-auto overflow-hidden">

              <div className="h-1 w-full" style={{ background: 'linear-gradient(90deg,#6366f1,#8b5cf6,#0ea5e9)' }} />

              <button onClick={closeAuthModal}
                className="absolute top-4 right-4 text-am-muted hover:text-am-text transition-colors z-10 p-1 rounded-lg hover:bg-am-surface">
                <X size={18} />
              </button>

              <div className="p-8 text-center">

                {/* Logo */}
                <div className="flex items-center justify-center gap-2 mb-6">
                  <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
                    <Cpu size={15} className="text-white" />
                  </div>
                  <span className="font-bold text-am-text text-sm">
                    Agent<span className="text-am-indigo">Market</span>
                  </span>
                  <span className="badge-indigo ml-1 flex items-center gap-1"><Zap size={9} /> ERC-8004</span>
                </div>

                {/* Icon */}
                <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
                  style={{ background: 'linear-gradient(135deg,#6366f115,#8b5cf615)', border: '1.5px solid #6366f125' }}>
                  <ShieldCheck size={28} className="text-am-indigo" />
                </div>

                <h2 className="text-lg font-bold text-am-text mb-2">Connect Your Wallet</h2>
                <p className="text-xs text-am-muted mb-6 leading-relaxed max-w-xs mx-auto">
                  Sign a one-time message with MetaMask to authenticate.<br />
                  Your roles as buyer and/or provider are auto-detected.
                </p>

                {error && (
                  <div className="mb-4 px-3 py-2.5 rounded-xl text-sm text-am-rose bg-rose-50 border border-rose-200 text-left">
                    {error}
                  </div>
                )}

                <button onClick={handleConnect} disabled={loading}
                  className="w-full flex items-center justify-center gap-2.5 py-3.5 rounded-xl font-semibold text-sm
                             bg-am-indigo text-white hover:bg-indigo-700 transition-all duration-200 disabled:opacity-50 shadow-sm">
                  {loading ? (
                    <>
                      <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                      Waiting for signature…
                    </>
                  ) : (
                    <>
                      <Wallet size={16} />
                      Connect with MetaMask
                    </>
                  )}
                </button>

                <p className="text-xs text-am-muted mt-5">
                  No password required — your wallet is your identity.
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
