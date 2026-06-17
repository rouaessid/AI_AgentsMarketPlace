import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import {
  Plus, TrendingUp, Wallet, Activity, CheckCircle, Clock,
  ChevronRight, Package, AlertCircle, Edit2, BarChart2,
  Zap, Shield, Eye, RefreshCw, ExternalLink, GitBranch
} from 'lucide-react'
import { agentApi, normalizeAgent } from '../api/agentApi'
import { useAuth } from '../context/AuthContext'
import ReputationRing from '../components/common/ReputationRing'

export default function SellerDashboard() {
  const { user, walletAddress } = useAuth()
  const [agents,     setAgents]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [fetchError, setFetchError] = useState('')


  const fetchMyAgents = useCallback(async () => {
    setLoading(true)
    setFetchError('')
    try {
      // 1. Try by owner address
      let addr = walletAddress || user?.wallet
      if (!addr && window.ethereum) {
        const accounts = await window.ethereum.request({ method: 'eth_accounts' })
        if (accounts?.length > 0) addr = accounts[0]
      }
      if (addr) {
        const data = await agentApi.byOwner(addr)
        const list = (data.agents || []).map(normalizeAgent)
        setAgents(list)
      }
    } catch (e) {
      setFetchError(e.message || 'Failed to load agents')
      setAgents([])
    } finally {
      setLoading(false)
    }
  }, [walletAddress, user])

  useEffect(() => { fetchMyAgents() }, [fetchMyAgents])

  // Auto-poll every 4s only while agents are pending — stops automatically
  useEffect(() => {
    const hasPending = agents.some(a =>
      a.status === 'pending_index' || a.status === 'pending_validation'
    )
    if (!hasPending) return
    const id = setInterval(fetchMyAgents, 4000)
    return () => clearInterval(id)
  }, [agents, fetchMyAgents])

  function fmtEth(val) {
    const n = parseFloat(val) || 0
    if (n === 0)    return '0.00'
    if (n < 0.001)  return n.toFixed(6)
    if (n < 0.01)   return n.toFixed(4)
    if (n < 1)      return n.toFixed(3)
    return n.toFixed(2)
  }

  const totalEarnings = agents.reduce((s, a) => s + (parseFloat(a.earnings_eth) || 0), 0)
  const totalTasks    = agents.reduce((s, a) => s + (a.metrics?.tasks_performed || 0), 0)
  const avgReputation = agents.length
    ? Math.round(agents.reduce((s, a) => s + (a.metrics?.reputation_score || 0), 0) / agents.length)
    : 0
  const totalStaked   = agents.reduce((s, a) => s + (parseFloat(a.stake_amount) || 0), 0)

  // Separate provider / judge counts for context labels
  const providerCount = agents.filter(a => a.agent_type !== 'judge').length
  const judgeCount    = agents.filter(a => a.agent_type === 'judge').length

  const ACTIVITY = [
    { id: 'a1', agent: agents[0]?.name || 'Agent', msg: 'Task completed → +0.072 ETH',      time: '2m ago',  ok: true  },
    { id: 'a2', agent: agents[0]?.name || 'Agent', msg: 'Validation VALID by 3/3 judges',    time: '3m ago',  ok: true  },
    { id: 'a3', agent: agents[1]?.name || 'Agent', msg: 'Task completed → +0.045 ETH',      time: '8m ago',  ok: true  },
    { id: 'a4', agent: agents[1]?.name || 'Agent', msg: 'Validation VALID by 2/3 judges',    time: '10m ago', ok: true  },
    { id: 'a5', agent: agents[2]?.name || 'Agent', msg: 'Stake locked for active task',      time: '15m ago', ok: true  },
    { id: 'a6', agent: agents[2]?.name || 'Agent', msg: 'Task timed out — client refunded',  time: '1h ago',  ok: false },
  ]

  return (
    <div className="min-h-screen bg-am-bg">
      {/* Page header */}
      <div className="bg-white border-b border-am-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="section-label">Seller Dashboard</p>
              <h1 className="text-2xl sm:text-3xl font-bold text-am-text">My Agents</h1>
              {(walletAddress || user?.wallet) && (
                <p className="text-am-muted text-sm mt-1 font-mono">
                  {(walletAddress || user.wallet).slice(0,10)}…{(walletAddress || user.wallet).slice(-6)}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={fetchMyAgents} disabled={loading}
                className="btn-ghost flex items-center gap-2 text-sm">
                <RefreshCw size={14} className={loading ? 'animate-spin-slow' : ''} />
                Refresh
              </button>
              <Link to="/seller/register" className="btn-primary flex items-center gap-2">
                <Plus size={15} /> Deploy Agent
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">

        {/* Stats row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total Earnings',  value: `${fmtEth(totalEarnings)} ETH`,  icon: Wallet,     color: '#10b981', sub: 'All-time earnings'                              },
            { label: 'Tasks / Validations', value: totalTasks.toLocaleString(), icon: CheckCircle,color: '#6366f1', sub: `${providerCount} providers · ${judgeCount} judges` },
            { label: 'Avg Reputation',  value: `${avgReputation}/100`,          icon: TrendingUp, color: '#8b5cf6', sub: avgReputation > 0 ? 'Across all agents' : 'No data yet' },
            { label: 'Total Staked',    value: `${fmtEth(totalStaked)} ETH`,    icon: Shield,     color: '#f59e0b', sub: 'Locked as guarantee'                            },
          ].map(({ label, value, icon: Icon, color, sub }) => (
            <motion.div key={label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
              className="card p-5 shadow-card-md">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-am-muted">{label}</span>
                <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                  style={{ background: `${color}12`, border: `1.5px solid ${color}20` }}>
                  <Icon size={14} style={{ color }} />
                </div>
              </div>
              <div className="text-xl font-bold text-am-text">{value}</div>
              <div className="text-xs text-am-muted mt-1">{sub}</div>
            </motion.div>
          ))}
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Agent list */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-am-text">Registered Agents</h2>
              <span className="text-xs text-am-muted badge-slate">{agents.length} total</span>
            </div>

            {fetchError && (
              <div className="card p-4 border border-rose-200 bg-rose-50 text-rose-700 text-sm flex items-center gap-2">
                <AlertCircle size={14} /> {fetchError}
              </div>
            )}

            {!loading && agents.length === 0 && !fetchError && (
              <div className="card p-6 text-center text-am-muted text-sm">
                No agents found. Make sure the backend is running and you have registered agents.
              </div>
            )}

            {loading ? (
              [...Array(3)].map((_, i) => (
                <div key={i} className="card p-5 animate-pulse space-y-3">
                  <div className="flex gap-4">
                    <div className="w-11 h-11 rounded-2xl bg-am-surface" />
                    <div className="flex-1 space-y-2">
                      <div className="h-4 w-1/3 rounded bg-am-surface" />
                      <div className="h-3 w-1/2 rounded bg-am-surface" />
                    </div>
                  </div>
                  <div className="h-3 w-full rounded bg-am-surface" />
                </div>
              ))
            ) : (
              agents.map((agent, i) => <AgentRow key={agent.id || agent.agent_id} agent={agent} index={i} />)
            )}

            {/* Deploy CTA */}
            <Link to="/seller/register"
              className="flex items-center gap-3 card p-5 border-2 border-dashed border-am-border
                         hover:border-am-indigo/30 hover:bg-indigo-50/30 transition-all duration-200 group">
              <div className="w-10 h-10 rounded-2xl bg-am-surface border border-am-border flex items-center justify-center group-hover:border-am-indigo/30">
                <Plus size={18} className="text-am-muted group-hover:text-am-indigo" />
              </div>
              <div>
                <div className="text-sm font-semibold text-am-text-2 group-hover:text-am-text">Deploy another agent</div>
                <div className="text-xs text-am-muted">Stake ETH and start earning</div>
              </div>
              <ChevronRight size={16} className="ml-auto text-am-muted group-hover:text-am-indigo" />
            </Link>
          </div>

          {/* Activity feed */}
          <div>
            <h2 className="font-bold text-am-text mb-4">Live Activity</h2>
            <div className="card divide-y divide-am-border overflow-hidden">
              {ACTIVITY.map(({ id, agent, msg, time, ok }, i) => (
                <motion.div key={id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="px-4 py-3 flex items-start gap-3">
                  <div className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                    ok ? 'bg-emerald-50 border border-emerald-200' : 'bg-rose-50 border border-rose-200'
                  }`}>
                    {ok
                      ? <CheckCircle size={11} className="text-am-emerald" />
                      : <AlertCircle size={11} className="text-am-rose" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-am-text truncate">{agent}</div>
                    <div className="text-xs text-am-muted mt-0.5 leading-relaxed">{msg}</div>
                  </div>
                  <div className="text-xs text-am-muted flex-shrink-0">{time}</div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Edit Agent Modal — description, readme, prix (pas de tx blockchain) ───── */
function EditAgentModal({ agent, onClose }) {
  const [form, setForm] = useState({
    description:    agent.description || '',
    readme:         agent.readme      || '',
    price_per_task: agent.price_per_task != null ? String(agent.price_per_task) : '',
    name:           agent.name        || '',
  })
  const [saving, setSaving] = useState(false)
  const [saved,  setSaved]  = useState(false)
  const [error,  setError]  = useState('')

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function save() {
    setSaving(true)
    setError('')
    try {
      const body = {}
      if (form.description !== (agent.description || ''))     body.description    = form.description
      if (form.readme      !== (agent.readme      || ''))     body.readme         = form.readme
      if (form.name        !== (agent.name        || ''))     body.name           = form.name
      if (form.price_per_task !== '' && Number(form.price_per_task) !== agent.price_per_task)
        body.price_per_task = Number(form.price_per_task)

      if (Object.keys(body).length === 0) { onClose(); return }
      await agentApi.editAgent(agent.agent_id, body)
      setSaved(true)
      setTimeout(onClose, 800)
    } catch (e) {
      setError(e.message || 'Erreur lors de la sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-bold text-am-text flex items-center gap-2">
              <Edit2 size={15} className="text-am-indigo" />
              Edit — <span className="font-mono text-am-indigo">{agent.agent_id}</span>
            </h3>
            <p className="text-xs text-am-muted mt-0.5">Pas de transaction blockchain — modifications immédiates</p>
          </div>
          <button onClick={onClose} className="text-am-muted hover:text-am-text text-xl leading-none">×</button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium text-am-text-2 block mb-1">Nom</label>
            <input className="input w-full text-sm" value={form.name}
              onChange={e => set('name', e.target.value)} placeholder={agent.name} />
          </div>
          <div>
            <label className="text-xs font-medium text-am-text-2 block mb-1">Prix par tâche (ETH)</label>
            <input type="number" min="0" step="0.01" className="input w-full text-sm"
              value={form.price_per_task} onChange={e => set('price_per_task', e.target.value)}
              placeholder={agent.price_per_task || '0.05'} />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-am-text-2 block mb-1">Description</label>
          <textarea rows={3} className="input w-full text-sm resize-none"
            value={form.description} onChange={e => set('description', e.target.value)}
            placeholder="Décrivez votre agent…" />
        </div>

        <div>
          <label className="text-xs font-medium text-am-text-2 block mb-1">README</label>
          <textarea rows={10} className="input w-full text-sm font-mono resize-y"
            value={form.readme} onChange={e => set('readme', e.target.value)}
            placeholder="## Mon Agent&#10;&#10;Usage, inputs, outputs…" />
        </div>

        {error && (
          <p className="text-xs text-red-500 flex items-start gap-1.5">
            <AlertCircle size={12} className="mt-0.5 flex-shrink-0" /> {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost text-sm">Annuler</button>
          <button onClick={save} disabled={saving || saved} className="btn-primary text-sm">
            {saved ? '✓ Sauvegardé' : (saving ? 'Sauvegarde…' : 'Sauvegarder')}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── New Version Modal — nouveau code = nouvelle image Docker → tx blockchain ─ */
function NewVersionModal({ agent, onClose }) {
  const [form, setForm]       = useState({ new_version: '', docker_image: '' })
  const [submitting, setSubmitting] = useState(false)
  const [txHash,     setTxHash]     = useState(null)
  const [error,      setError]      = useState('')

  function set(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function waitForReceipt(hash, maxRetries = 40) {
    for (let i = 0; i < maxRetries; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const receipt = await window.ethereum.request({ method: 'eth_getTransactionReceipt', params: [hash] })
      if (receipt?.status === '0x1') return receipt
      if (receipt?.status === '0x0') throw new Error('Transaction revertée on-chain')
    }
    throw new Error('Transaction non confirmée après 80s')
  }

  async function submit() {
    if (!form.new_version)  return setError('Version requise (ex: 2.0.0)')
    if (!/^\d+\.\d+\.\d+$/.test(form.new_version)) return setError('Format invalide — ex: 2.0.0')
    if (!form.docker_image) return setError('Image Docker requise (ex: myagent:v2)')
    if (!window.ethereum) return setError('MetaMask non détecté.')
    setSubmitting(true)
    setError('')
    try {
      // Step 1 — IPFS upload + build unsigned tx
      const res = await agentApi.newVersion(agent.agent_id, {
        agent_id:     agent.agent_id,
        new_version:  form.new_version,
        docker_image: form.docker_image,
      })

      // Step 2 — Switch to Base Sepolia and sign mintNewVersion() with MetaMask
      if (res.unsigned_tx?.data) {
        try {
          await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14A34' }] })
        } catch (sw) {
          if (sw.code === 4902) {
            await window.ethereum.request({
              method: 'wallet_addEthereumChain',
              params: [{ chainId: '0x14A34', chainName: 'Base Sepolia',
                rpcUrls: ['https://base-sepolia-rpc.publicnode.com', 'https://sepolia.base.org'],
                nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 } }],
            })
          }
        }
        const accounts = await window.ethereum.request({ method: 'eth_accounts' })
        const from = accounts[0]
        if (!from) throw new Error('Aucun compte connecté dans MetaMask.')
        const gasHex = '0x' + res.unsigned_tx.estimated_gas.toString(16)
        const txHash = await window.ethereum.request({
          method: 'eth_sendTransaction',
          params: [{ from, to: res.unsigned_tx.contract_address, data: res.unsigned_tx.data, gas: gasHex }],
        })

        // Step 3 — Wait for receipt and parse newTokenId from AgentVersionMinted (topics[1])
        const receipt = await waitForReceipt(txHash)
        let tokenId = null
        for (const log of (receipt?.logs || [])) {
          if (
            log.address?.toLowerCase() === res.unsigned_tx.contract_address?.toLowerCase() &&
            log.topics?.length >= 2
          ) {
            tokenId = parseInt(log.topics[1], 16)
            break
          }
        }

        // Step 4 — Notify backend (recalcule embedding pour providers)
        await agentApi.confirmVersion(agent.agent_id, { tx_hash: txHash, token_id: tokenId }).catch(() => {})

        setTxHash(txHash)
      } else {
        setTxHash(res.tx_hash || 'submitted')
      }
    } catch (e) {
      if (e.code !== 4001) setError(e.message || 'Erreur lors de la soumission')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md flex flex-col gap-5 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-bold text-am-text flex items-center gap-2">
              <GitBranch size={15} className="text-am-indigo" />
              New Version — <span className="font-mono text-am-indigo">{agent.agent_id}</span>
            </h3>
            <p className="text-xs text-am-muted mt-0.5">Nouveau code → transaction blockchain → nouveau token NFT</p>
          </div>
          <button onClick={onClose} className="text-am-muted hover:text-am-text text-xl leading-none">×</button>
        </div>

        {txHash ? (
          <div className="text-center py-6">
            <CheckCircle size={40} className="text-emerald-500 mx-auto mb-3" />
            <p className="font-semibold text-am-text">Version soumise sur blockchain</p>
            <p className="text-xs text-am-muted mt-1">En attente de confirmation indexer…</p>
            {txHash.startsWith('0x') && (
              <p className="mt-2 font-mono text-xs text-am-indigo break-all">{txHash.slice(0,30)}…</p>
            )}
            <button onClick={onClose} className="btn-primary mt-4 text-sm">Fermer</button>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <div>
                <label className="text-xs font-medium text-am-text-2 block mb-1">
                  Numéro de version <span className="text-red-400">*</span>
                </label>
                <input className="input w-full text-sm" placeholder="2.0.0"
                  value={form.new_version} onChange={e => set('new_version', e.target.value)} />
              </div>
              <div>
                <label className="text-xs font-medium text-am-text-2 block mb-1">
                  Nouvelle image Docker <span className="text-red-400">*</span>
                </label>
                <input className="input w-full text-sm font-mono"
                  placeholder={agent.docker_image ? agent.docker_image.split('@')[0] + ':v2' : 'myagent:v2'}
                  value={form.docker_image} onChange={e => set('docker_image', e.target.value)} />
                <p className="text-xs text-am-muted mt-0.5">
                  Faites <code className="bg-gray-100 px-1 rounded">docker build</code> avant de soumettre
                </p>
              </div>
            </div>

            {error && (
              <p className="text-xs text-red-500 flex items-start gap-1.5">
                <AlertCircle size={12} className="mt-0.5 flex-shrink-0" /> {error}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="btn-ghost text-sm">Annuler</button>
              <button onClick={submit} disabled={submitting}
                className="btn-primary text-sm flex items-center gap-1.5">
                <GitBranch size={13} />
                {submitting ? 'Soumission…' : 'Publier nouvelle version'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function AgentRow({ agent, index }) {
  const [editAgent,       setEditAgent]       = useState(false)
  const [newVersion,      setNewVersion]      = useState(false)
  const [retrying,  setRetrying]  = useState(false)
  const [retryErr,  setRetryErr]  = useState('')
  const m         = agent.metrics || {}
  const isJudge   = agent.agent_type === 'judge' || agent.agent_type === 1
  const accent    = isJudge ? '#7c3aed' : '#6366f1'
  const isPending = agent.status === 'pending_signature'

  async function retryRegistration() {
    setRetrying(true); setRetryErr('')
    try {
      const res = await fetch(`/api/v1/agents/${agent.agent_id}/retry-register`, { method: 'POST' })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      const utx = data.unsigned_tx
      if (!utx?.data) throw new Error('Backend did not return unsigned_tx.data')

      try {
        await window.ethereum.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: '0x14A34' }],
        })
      } catch (sw) {
        if (sw.code === 4902) {
          await window.ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [{ chainId: '0x14A34', chainName: 'Base Sepolia',
              rpcUrls: ['https://base-sepolia-rpc.publicnode.com', 'https://sepolia.base.org'],
              nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 } }],
          })
        }
      }

      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{ from: (await window.ethereum.request({ method: 'eth_accounts' }))[0],
          to: utx.contract_address, data: utx.data,
          gas: '0x' + utx.estimated_gas.toString(16) }],
      })

      // Wait for on-chain confirmation
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 2000))
        const receipt = await window.ethereum.request({ method: 'eth_getTransactionReceipt', params: [txHash] })
        if (receipt?.status === '0x1') break
        if (receipt?.status === '0x0') throw new Error('Transaction reverted on-chain')
      }

      await fetch('/api/v1/agents/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ registration_id: data.registration_id, tx_hash: txHash }),
      })
      window.location.reload()
    } catch (e) {
      if (e.code !== 4001) setRetryErr(e.message || 'Retry failed')
    } finally {
      setRetrying(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07 }}
      className="card p-5 hover:shadow-card-md transition-shadow duration-200"
    >
      <div className="flex items-start gap-4">
        {/* Avatar */}
        <div className="w-11 h-11 rounded-2xl flex items-center justify-center font-bold text-lg text-white flex-shrink-0"
          style={{ background: `linear-gradient(135deg,${accent},${isJudge ? '#8b5cf6' : '#0ea5e9'})` }}>
          {agent.name?.charAt(0) || '?'}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-semibold text-am-text">{agent.name}</span>
            <span className="badge text-xs" style={{
              background: `${accent}10`, color: accent, borderColor: `${accent}25`,
              border: `1px solid ${accent}25`, padding: '2px 8px', borderRadius: '999px',
            }}>
              {isJudge ? 'Judge' : 'Provider'}
            </span>
            <span className="text-xs text-am-muted font-mono">v{agent.version}</span>
            <span className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium border ${
              isPending || agent.status === 'pending_index'
                ? 'bg-amber-50 text-amber-700 border-amber-300'
                : agent.status === 'pending_validation'
                ? 'bg-violet-50 text-violet-700 border-violet-300'
                : agent.status === 'rejected'
                ? 'bg-rose-50 text-rose-700 border-rose-300'
                : 'badge-emerald'
            }`}>
              {agent.status === 'pending_validation' ? 'Pending Validation'
               : agent.status === 'rejected'         ? 'Technical Test Failed'
               : agent.status || 'active'}
            </span>
          </div>

          {/* Metrics */}
          <div className="flex flex-wrap gap-3 mt-2 mb-3">
            {[
              { icon: CheckCircle, val: isJudge && !(m.tasks_performed > 0) ? '—' : `${m.success_rate ?? 0}%`, label: 'success', color: '#10b981' },
              { icon: Activity,    val: (m.tasks_performed ?? 0).toLocaleString(), label: 'tasks',  color: accent   },
              { icon: Zap,         val: `${m.avg_response_time ?? 0}s`,          label: 'avg resp', color: '#8b5cf6' },
              { icon: Wallet,      val: `${agent.earnings_eth || '0'} ETH`,      label: 'earned',   color: '#f59e0b' },
            ].map(({ icon: Icon, val, label, color }) => (
              <div key={label} className="flex items-center gap-1.5 text-xs">
                <Icon size={11} style={{ color }} />
                <span className="text-am-text font-medium">{val}</span>
                <span className="text-am-muted">{label}</span>
              </div>
            ))}
          </div>

          {/* Statut test technique — juges seulement */}
          {isJudge && (
            <div className="flex items-center gap-2 mb-2">
              {agent.status === 'active' && (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 font-medium">
                  <CheckCircle size={10} /> Juge validé
                </span>
              )}
              {agent.status === 'pending_validation' && (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border bg-amber-50 text-amber-700 border-amber-200 font-medium">
                  <Clock size={10} /> Test technique en cours...
                </span>
              )}
              {agent.status === 'validation_failed' && (
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border bg-rose-50 text-rose-700 border-rose-200 font-medium">
                  <AlertCircle size={10} /> Validation échouée — déployez une nouvelle version
                </span>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            {isJudge ? (
              <Link to={`/seller/judge/${agent.agent_id}`}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border
                           border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100 transition-all font-medium">
                <Eye size={11} /> View
              </Link>
            ) : (
              <Link to={`/marketplace/${agent.agent_id}`}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-am-border
                           text-am-text-2 hover:text-am-text hover:bg-am-surface transition-all">
                <Eye size={11} /> View
              </Link>
            )}
            <button onClick={() => setEditAgent(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-am-border
                         text-am-text-2 hover:text-am-text hover:bg-am-surface transition-all">
              <Edit2 size={11} /> Edit
            </button>
            <button onClick={() => setNewVersion(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-am-indigo/40
                         text-am-indigo hover:bg-indigo-50 transition-all">
              <GitBranch size={11} /> New Version
            </button>
            <button className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-am-border
                               text-am-text-2 hover:text-am-text hover:bg-am-surface transition-all">
              <BarChart2 size={11} /> Analytics
            </button>
            {isPending && (
              <button onClick={retryRegistration} disabled={retrying}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-amber-400
                           text-amber-700 hover:bg-amber-50 transition-all disabled:opacity-50">
                <RefreshCw size={11} className={retrying ? 'animate-spin' : ''} />
                {retrying ? 'Signing…' : 'Retry Registration'}
              </button>
            )}
            {retryErr && (
              <p className="text-xs text-rose-500 w-full mt-1 flex items-center gap-1">
                <AlertCircle size={11} /> {retryErr}
              </p>
            )}
            {agent.platform_endpoint && (
              <a href={agent.platform_endpoint} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-am-border
                           text-am-indigo hover:bg-indigo-50 transition-all">
                <ExternalLink size={11} /> Endpoint
              </a>
            )}
          </div>
        </div>

        {!(m.tasks_performed > 0) ? (
          <div className="w-[52px] h-[52px] rounded-full border-2 border-dashed border-am-border flex items-center justify-center">
            <span className="text-xs text-am-muted">New</span>
          </div>
        ) : (
          <ReputationRing score={m.reputation_score ?? 0} size={52} stroke={4} />
        )}
      </div>

      {/* Footer bar */}
      <div className="mt-4 pt-3 border-t border-am-border flex items-center gap-4 text-xs text-am-muted flex-wrap">
        <span className="flex items-center gap-1.5"><Shield size={10} /> {agent.stake_amount || 0} ETH staked</span>
        <span className="flex items-center gap-1.5"><Clock size={10} /> Last active {m.last_active || 'recently'}</span>
        {agent.docker_image && (
          <span className="flex items-center gap-1.5"><Package size={10} />
            <span className="truncate max-w-[140px] font-mono">{agent.docker_image}</span>
          </span>
        )}
        {isJudge && (
          <span className="flex items-center gap-1.5 text-violet-500 ml-auto font-medium">
            <Eye size={10} className="opacity-40" /> Not visible in marketplace
          </span>
        )}
      </div>

      {editAgent  && <EditAgentModal  agent={agent} onClose={() => setEditAgent(false)}  />}
      {newVersion && <NewVersionModal agent={agent} onClose={() => setNewVersion(false)} />}
    </motion.div>
  )
}
