import { useState, useEffect, useCallback, useRef, Component } from 'react'
import { useParams, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Shield, Zap, Clock, TrendingUp, CheckCircle, Users,
  Copy, Check, Terminal, Code2, BookOpen, Activity, Play,
  Package, Cpu, Layers, Globe, Hash, AlertCircle, Lock,
  ShoppingCart, Loader2, XCircle, FileText, List, BarChart2,
  ExternalLink, ChevronDown, ChevronUp,
} from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ReputationRing from '../components/common/ReputationRing'
import { agentApi, normalizeAgent } from '../api/agentApi'
import { useAuth } from '../context/AuthContext'

// Tabs visible to everyone
const PUBLIC_TABS  = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'readme',   label: 'README',   icon: BookOpen },
]
// Tabs unlocked after purchase
const PRIVATE_TABS = [
  { id: 'integrate', label: 'Integrate', icon: Code2 },
  { id: 'test',      label: 'Live Test', icon: Play  },
]
const ALL_TABS = [...PUBLIC_TABS, ...PRIVATE_TABS]

const MONTHS    = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
const WEEK_DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

function hasValue(v) { return v !== null && v !== undefined && v !== '' }
function displayValue(v, suffix = '') { return hasValue(v) ? `${v}${suffix}` : '--' }
function formatCount(v) {
  if (!hasValue(v)) return '--'
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}

// ── Validation status helpers ─────────────────────────────────────────────────
const VAL_CONFIG = {
  awaiting_run: { color: '#6366f1', bg: '#eef2ff', border: '#c7d2fe', label: 'Run the agent to start validation', icon: Play,        spin: false },
  pending:      { color: '#f59e0b', bg: '#fffbeb', border: '#fde68a', label: 'Validation starting...',             icon: Loader2,     spin: true  },
  in_progress:  { color: '#6366f1', bg: '#eef2ff', border: '#c7d2fe', label: 'Judges evaluating...',               icon: Loader2,     spin: true  },
  validated:    { color: '#10b981', bg: '#ecfdf5', border: '#a7f3d0', label: 'Agent Validated',                    icon: CheckCircle, spin: false },
  rejected:     { color: '#ef4444', bg: '#fef2f2', border: '#fecaca', label: 'Validation Failed',                  icon: XCircle,     spin: false },
  not_started:  { color: '#94a3b8', bg: '#f8fafc', border: '#e2e8f0', label: 'Not validated yet',                  icon: Shield,      spin: false },
}

// ─────────────────────────────────────────────────────────────────────────────

export default function AgentDetail() {
  const { agentId }  = useParams()
  const { walletAddress, connectWallet } = useAuth()

  const [agent,      setAgent]      = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [tab,        setTab]        = useState('overview')
  const [hasAccess,  setHasAccess]  = useState(false)
  const [valStatus,  setValStatus]  = useState(null)   // full validation object
  const [purchasing, setPurchasing] = useState(false)
  const [purchaseErr,setPurchaseErr]= useState('')
  const [showBuyModal, setShowBuyModal] = useState(false)
  const [purchaseInfo, setPurchaseInfo] = useState(null)
  // ── Run result — kept at parent level so it survives tab switches ─────────
  const [runResult,  setRunResult]  = useState(null)
  const [runError,   setRunError]   = useState(null)

  const pollingRef    = useRef(null)
  const metricsRef    = useRef(null)

  // ── Fetch agent ───────────────────────────────────────────────────────────
  const fetchAgent = useCallback(async () => {
    setLoading(true)
    try {
      const [data, endpointInfo] = await Promise.all([
        agentApi.get(agentId),
        agentApi.endpoint(agentId).catch(() => null),
      ])
      const merged = data ? {
        ...data,
        api_endpoint: endpointInfo?.platform_endpoint || data.platform_endpoint || null,
      } : null
      setAgent(merged ? normalizeAgent(merged) : null)
    } catch {
      setAgent(null)
    } finally {
      setLoading(false)
    }
  }, [agentId])

  // ── Check access ──────────────────────────────────────────────────────────
  const checkAccess = useCallback(async (wallet) => {
    if (!wallet) return
    try {
      const data = await agentApi.checkAccess(agentId, wallet)
      setHasAccess(data.has_access)
      if (data.has_access) fetchValidation()
    } catch {}
  }, [agentId])  // eslint-disable-line

  // ── Fetch validation ──────────────────────────────────────────────────────
  const fetchValidation = useCallback(async () => {
    try {
      const data = await agentApi.getValidation(agentId)
      setValStatus(data)
      // Stop polling once finalised and refresh agent card (reputation/success_rate updated)
      if (data.status === 'validated' || data.status === 'rejected') {
        clearInterval(pollingRef.current)
        pollingRef.current = null
        fetchAgent()
      }
    } catch {}
  }, [agentId, fetchAgent])

  // ── Start polling only when judges are actively running ──────────────────
  useEffect(() => {
    const activeStatuses = ['pending', 'in_progress']
    if (!hasAccess || !activeStatuses.includes(valStatus?.status)) {
      // Stop any existing poll if status is no longer active
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      return
    }
    if (pollingRef.current) return
    pollingRef.current = setInterval(fetchValidation, 5000)
    return () => { clearInterval(pollingRef.current); pollingRef.current = null }
  }, [hasAccess, valStatus?.status, fetchValidation])

  useEffect(() => { fetchAgent() }, [fetchAgent])
  useEffect(() => { checkAccess(walletAddress) }, [walletAddress, checkAccess])
  useEffect(() => { setRunResult(null); setRunError(null) }, [agentId])

  // Poll metrics every 30s so stats update after runs/validation without manual refresh
  useEffect(() => {
    metricsRef.current = setInterval(fetchAgent, 30_000)
    return () => clearInterval(metricsRef.current)
  }, [fetchAgent])

  // ── Guard: if tab is private but no access, fall back ────────────────────
  useEffect(() => {
    if (!hasAccess && (tab === 'integrate' || tab === 'test')) setTab('overview')
  }, [hasAccess, tab])

  // ── Buy flow ──────────────────────────────────────────────────────────────
  async function openBuyModal() {
    let wallet = walletAddress
    if (!wallet) {
      wallet = await connectWallet()
      if (!wallet) return
    }
    try {
      const info = await agentApi.getPurchaseInfo(agentId)
      setPurchaseInfo(info)
      setShowBuyModal(true)
    } catch (e) {
      setPurchaseErr(e.message)
    }
  }

  async function confirmPurchase() {
    if (!purchaseInfo || !walletAddress) return
    setPurchasing(true)
    setPurchaseErr('')
    try {
      if (!window.ethereum) throw new Error('MetaMask not detected')

      const priceWei = BigInt(purchaseInfo.required_wei)

      // Send MetaMask tx to EscrowManager.depositPayment()
      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{
          from:  walletAddress,
          to:    purchaseInfo.escrow_address,
          value: '0x' + priceWei.toString(16),
          data:  purchaseInfo.call_data,
        }],
      })

      // Wait for confirmation (poll for receipt)
      await waitForReceipt(txHash)

      // Notify backend
      await agentApi.purchase(agentId, {
        task_id:      purchaseInfo.task_id,
        tx_hash:      txHash,
        buyer_wallet: walletAddress,
      })

      setHasAccess(true)
      setShowBuyModal(false)
      fetchValidation()
    } catch (e) {
      if (e.code !== 4001) setPurchaseErr(e.message || 'Transaction failed')
    } finally {
      setPurchasing(false)
    }
  }

  async function waitForReceipt(txHash, maxRetries = 30) {
    for (let i = 0; i < maxRetries; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const receipt = await window.ethereum.request({
        method: 'eth_getTransactionReceipt',
        params: [txHash],
      })
      if (receipt && receipt.status === '0x1') return receipt
      if (receipt && receipt.status === '0x0') throw new Error('Transaction reverted')
    }
    throw new Error('Transaction not confirmed after 60s')
  }

  // ─────────────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-am-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-am-indigo border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="min-h-screen bg-am-bg flex items-center justify-center">
        <div className="text-center">
          <Cpu size={40} className="mx-auto mb-4 text-am-muted" />
          <p className="text-am-text font-semibold">Agent not found</p>
          <Link to="/marketplace" className="text-am-indigo text-sm mt-2 inline-block hover:underline">
            ← Back to marketplace
          </Link>
        </div>
      </div>
    )
  }

  const m       = agent.metrics || {}
  const isJudge = agent.agent_type === 'judge'
  const accent  = isJudge ? '#7c3aed' : '#6366f1'
  const hasMonthlyMetrics = (m.monthly_tasks || []).length > 0
  const hasWeeklyMetrics  = (m.weekly_success || []).length > 0
  const monthlyData = (hasMonthlyMetrics ? m.monthly_tasks : Array(12).fill(0)).map((v, i) => ({ month: MONTHS[i], tasks: v }))
  const weeklyData  = (hasWeeklyMetrics  ? m.weekly_success : Array(7).fill(0)).map((v, i) => ({ day: WEEK_DAYS[i], rate: v }))

  const summaryStats = [
    { icon: CheckCircle, label: 'Success Rate',  value: displayValue(m.success_rate, '%'),         color: '#10b981', pending: !hasValue(m.success_rate) },
    { icon: Activity,    label: 'Tasks Done',     value: formatCount(m.tasks_performed),             color: accent,    pending: !hasValue(m.tasks_performed) },
    { icon: Users,       label: 'Total Usage',    value: formatCount(m.usage_count),                 color: '#8b5cf6', pending: !hasValue(m.usage_count) },
    { icon: Clock,       label: 'Avg Response',   value: displayValue(m.avg_response_time, 's'),     color: '#f59e0b', pending: !hasValue(m.avg_response_time) },
    { icon: Zap,         label: 'Uptime',         value: displayValue(m.uptime, '%'),                color: '#10b981', pending: !hasValue(m.uptime) },
    { icon: TrendingUp,  label: 'Completion',     value: displayValue(m.task_completion_rate, '%'),  color: accent,    pending: !hasValue(m.task_completion_rate) },
  ]

  const visibleTabs = hasAccess ? ALL_TABS : PUBLIC_TABS

  return (
    <div className="min-h-screen bg-am-bg">
      {/* Buy modal */}
      <AnimatePresence>
        {showBuyModal && purchaseInfo && (
          <BuyModal
            agent={agent}
            info={purchaseInfo}
            walletAddress={walletAddress}
            purchasing={purchasing}
            error={purchaseErr}
            onConfirm={confirmPurchase}
            onClose={() => { setShowBuyModal(false); setPurchaseErr('') }}
          />
        )}
      </AnimatePresence>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <Link to="/marketplace" className="inline-flex items-center gap-2 text-sm text-am-muted hover:text-am-text mb-6 transition-colors">
          <ArrowLeft size={15} /> Back to Marketplace
        </Link>

        {/* ── Hero card ─────────────────────────────────────────────────── */}
        <div className="card shadow-card-md p-6 sm:p-8 mb-6 relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 rounded-t-2xl"
            style={{ background: isJudge ? 'linear-gradient(90deg,#8b5cf6,#6366f1)' : 'linear-gradient(90deg,#6366f1,#0ea5e9)' }}
          />
          <div className="flex flex-col sm:flex-row gap-6 items-start">
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center text-3xl font-bold text-white flex-shrink-0"
              style={{ background: `linear-gradient(135deg,${accent},${isJudge ? '#8b5cf6' : '#0ea5e9'})` }}>
              {agent.name?.charAt(0) || '?'}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <h1 className="text-2xl font-bold text-am-text">{agent.name}</h1>
                <span className="text-xs px-2.5 py-1 rounded-full font-medium border"
                  style={{ background: `${accent}10`, color: accent, borderColor: `${accent}25` }}>
                  {isJudge ? 'Judge' : 'Provider'}
                </span>
                {hasValue(agent.version) && (
                  <span className="text-xs text-am-muted font-mono border border-am-border px-2 py-0.5 rounded-full">
                    v{agent.version}
                  </span>
                )}
                {hasAccess && (
                  <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 font-medium flex items-center gap-1">
                    <CheckCircle size={10} /> Access granted
                  </span>
                )}
              </div>
              <p className="text-am-text-2 leading-relaxed max-w-2xl mb-4">
                {agent.description || 'No description published for this agent yet.'}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {(agent.categories || []).map((c) => (
                  <span key={c} className="text-xs px-2.5 py-1 rounded-full text-am-text-2 bg-am-surface border border-am-border">{c}</span>
                ))}
                {(agent.badges || []).map((b) => (
                  <span key={b} className="badge badge-amber text-xs">{b}</span>
                ))}
              </div>
            </div>

            <div className="flex flex-col items-center sm:items-end gap-4 flex-shrink-0">
              <ReputationRing score={hasValue(m.reputation_score) ? m.reputation_score : 0} size={80} stroke={6} />
              <div className="text-right">
                <div className="text-2xl font-bold text-am-text">{displayValue(agent.price_per_task, ' ETH')}</div>
                <div className="text-xs text-am-muted">per task · max {displayValue(agent.max_calls_per_day)}/day</div>
              </div>
              {!hasAccess && (
                <button onClick={openBuyModal} className="btn-primary w-full sm:w-auto text-center flex items-center gap-2 justify-center">
                  <ShoppingCart size={14} /> Get Agent
                </button>
              )}
              {hasAccess && (
                <button onClick={() => setTab('test')} className="btn-primary w-full sm:w-auto text-center flex items-center gap-2 justify-center">
                  <Play size={14} /> Run Agent
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── Stats row ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {summaryStats.map(({ icon: Icon, label, value, color, pending }) => (
            <div key={label} className="card p-3 text-center shadow-sm">
              <Icon size={14} className="mx-auto mb-2" style={{ color: pending ? '#94a3b8' : color }} />
              <div className="text-sm font-bold text-am-text">{value}</div>
              <div className="text-xs text-am-muted mt-0.5">{label}</div>
              {pending && <div className="text-[10px] text-am-muted mt-1">Pending</div>}
            </div>
          ))}
        </div>

        {/* ── Validation banner (visible after purchase) ────────────────── */}
        {hasAccess && valStatus && (
          <ValidationBanner valStatus={valStatus} />
        )}

        {/* ── Tabs ──────────────────────────────────────────────────────── */}
        <div className="flex gap-1 p-1 rounded-xl bg-am-surface border border-am-border mb-6">
          {visibleTabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                tab === id
                  ? 'bg-white shadow-sm text-am-indigo border border-am-border'
                  : 'text-am-muted hover:text-am-text'
              }`}
            >
              <Icon size={14} />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
          {/* Locked tab hint (only when not purchased) */}
          {!hasAccess && (
            <div className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm text-am-muted/50 cursor-not-allowed select-none">
              <Lock size={13} />
              <span className="hidden sm:inline">Integrate & Test</span>
            </div>
          )}
        </div>

        {/* ── Tab content ───────────────────────────────────────────────── */}
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {tab === 'overview'  && <OverviewTab agent={agent} monthlyData={monthlyData} weeklyData={weeklyData} accent={accent} hasMonthlyMetrics={hasMonthlyMetrics} hasWeeklyMetrics={hasWeeklyMetrics} />}
            {tab === 'readme'    && <ReadmeTab agent={agent} />}
            {tab === 'integrate' && hasAccess && <IntegrateTab agent={agent} />}
            {tab === 'test'      && hasAccess && <TestTab agent={agent} buyerWallet={walletAddress} onValidationStarted={fetchValidation} onRunComplete={fetchAgent} result={runResult} error={runError} onResult={setRunResult} onError={setRunError} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

// ── Buy modal ─────────────────────────────────────────────────────────────────

function BuyModal({ agent, info, walletAddress, purchasing, error, onConfirm, onClose }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <motion.div
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95 }}
        className="card p-6 w-full max-w-md shadow-card-md"
      >
        <h2 className="text-lg font-bold text-am-text mb-1">Get Access to {agent.name}</h2>
        <p className="text-sm text-am-muted mb-5">This will lock your payment in escrow. Funds are released once the agent is validated by 3 independent judges.</p>

        <div className="space-y-3 mb-5">
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Price</span>
            <span className="font-bold text-am-text">{info.required_eth} ETH</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Escrow contract</span>
            <span className="font-mono text-xs text-am-muted truncate max-w-[180px]">{info.escrow_address || 'Not configured'}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Your wallet</span>
            <span className="font-mono text-xs text-am-muted truncate max-w-[180px]">
              {walletAddress ? `${walletAddress.slice(0,8)}...${walletAddress.slice(-6)}` : 'Not connected'}
            </span>
          </div>
        </div>

        {error && (
          <div className="rounded-lg p-3 bg-rose-50 border border-rose-200 text-xs text-rose-600 mb-4 flex items-start gap-2">
            <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 btn-secondary text-sm py-2.5">Cancel</button>
          <button
            onClick={onConfirm}
            disabled={purchasing || !walletAddress || !info.escrow_address}
            className="flex-1 btn-primary text-sm py-2.5 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {purchasing ? (
              <><Loader2 size={14} className="animate-spin" /> Confirming...</>
            ) : (
              <><ShoppingCart size={14} /> Pay {info.required_eth} ETH</>
            )}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── Validation banner ─────────────────────────────────────────────────────────

function ValidationBanner({ valStatus }) {
  const cfg = VAL_CONFIG[valStatus.status] || VAL_CONFIG.not_started
  const Icon = cfg.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl p-4 mb-6 border"
      style={{ background: cfg.bg, borderColor: cfg.border }}
    >
      <div className="flex items-center gap-3 mb-3">
        <Icon size={18} style={{ color: cfg.color }} className={cfg.spin ? 'animate-spin' : ''} />
        <span className="font-semibold text-sm" style={{ color: cfg.color }}>{cfg.label}</span>
        {valStatus.aggregated_score != null && (
          <span className="ml-auto text-xs font-mono px-2 py-0.5 rounded-full border"
            style={{ color: cfg.color, borderColor: cfg.border, background: '#fff' }}>
            Score: {valStatus.aggregated_score}/100
          </span>
        )}
      </div>

      {valStatus.judges && valStatus.judges.length > 0 && (
        <div className="grid sm:grid-cols-3 gap-2">
          {valStatus.judges.map((j) => (
            <JudgeCard key={j.judge_id} judge={j} />
          ))}
        </div>
      )}

      {valStatus.status === 'rejected' && (
        <p className="text-xs text-rose-600 mt-3">
          Validation failed — if payment was made, a refund is being processed by the escrow contract.
        </p>
      )}
    </motion.div>
  )
}

function JudgeCard({ judge }) {
  const isValid  = judge.verdict === 'VALID'
  const [open, setOpen] = useState(false)
  return (
    <div
      className="rounded-lg p-3 border bg-white cursor-pointer hover:shadow-sm transition-shadow"
      style={{ borderColor: isValid ? '#a7f3d0' : '#fecaca' }}
      onClick={() => setOpen(o => !o)}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-am-text">{judge.judge_name}</span>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${isValid ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>
          {judge.verdict}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div className="h-full rounded-full transition-all" style={{ width: `${judge.score}%`, background: isValid ? '#10b981' : '#ef4444' }} />
        </div>
        <span className="text-xs font-mono text-am-muted">{judge.score}</span>
      </div>
      <AnimatePresence>
        {open && (
          <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="text-[11px] text-am-muted mt-2 leading-relaxed overflow-hidden">
            {judge.justification}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Tab components (identical to before, no changes needed) ──────────────────

function OverviewTab({ agent, monthlyData, weeklyData, accent, hasMonthlyMetrics, hasWeeklyMetrics }) {
  const m = agent.metrics || {}
  const technicalItems = [
    { label: 'LLM Model',    value: agent.llm_model,    icon: Cpu     },
    { label: 'Framework',    value: agent.framework,    icon: Layers  },
    { label: 'Language',     value: agent.language,     icon: Code2   },
    { label: 'Docker Image', value: agent.docker_image, icon: Package },
    { label: 'Max Tokens',   value: agent.max_tokens,   icon: Hash    },
    { label: 'Last Active',  value: m.last_active,      icon: Clock   },
  ]
  const economics = [
    { label: 'Price / Task',    value: displayValue(agent.price_per_task, ' ETH'),  color: '#10b981' },
    { label: 'Stake Locked',    value: displayValue(agent.stake_amount, ' ETH'),    color: accent    },
    { label: 'Access Duration', value: displayValue(agent.access_duration_days,'d'),color: '#8b5cf6' },
    { label: 'Max Calls / Day', value: displayValue(agent.max_calls_per_day),        color: '#f59e0b' },
  ]
  return (
    <div className="space-y-5">
      <div className="grid lg:grid-cols-2 gap-5">
        <ChartCard title="Monthly Task Volume" subtitle={hasMonthlyMetrics ? 'Live values' : 'Will fill over time'}>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={monthlyData}>
              <defs>
                <linearGradient id="taskGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={accent} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={accent} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} width={35} />
              <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="tasks" stroke={accent} fill="url(#taskGrad)" strokeWidth={2} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Weekly Success Rate" subtitle={hasWeeklyMetrics ? 'Live values' : 'Filled by validation phase'}>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={weeklyData}>
              <XAxis dataKey="day" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} width={35} />
              <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="rate" fill="#10b981" opacity={0.75} radius={[3,3,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
      <div className="grid sm:grid-cols-2 gap-5">
        <div className="card shadow-card-md p-5">
          <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
            <Cpu size={14} style={{ color: accent }} /> Technical Config
          </h3>
          <div className="space-y-3">
            {technicalItems.map(({ label, value, icon: Icon }) => (
              <div key={label} className="flex items-center justify-between text-sm">
                <span className="text-am-muted flex items-center gap-2"><Icon size={12} />{label}</span>
                <span className="text-am-text font-mono text-xs truncate max-w-[160px]">{hasValue(value) ? value : '--'}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card shadow-card-md p-5">
          <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
            <Shield size={14} style={{ color: accent }} /> Capabilities
          </h3>
          <div className="space-y-3">
            <CapabilityGroup title="Supported Tasks"      values={agent.supported_tasks} badgeClass="badge badge-indigo text-xs"  empty="No supported tasks." />
            <CapabilityGroup title="Special Capabilities" values={agent.special_caps}    badgeClass="badge badge-violet text-xs"  empty="No special capabilities." />
            <CapabilityGroup title="Required API Keys"    values={agent.env_var_keys}    badgeClass="badge badge-amber text-xs font-mono" empty="No required API keys." />
          </div>
        </div>
      </div>
      <div className="card shadow-card-md p-5">
        <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
          <TrendingUp size={14} style={{ color: accent }} /> Economics & Stake
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {economics.map(({ label, value, color }) => (
            <div key={label} className="rounded-xl p-3 text-center border" style={{ background: `${color}08`, borderColor: `${color}20` }}>
              <div className="text-lg font-bold text-am-text">{value}</div>
              <div className="text-xs text-am-muted mt-1">{label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function CapabilityGroup({ title, values, badgeClass, empty }) {
  return (
    <div>
      <div className="text-xs text-am-muted mb-2">{title}</div>
      {(values || []).length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => <span key={v} className={badgeClass}>{v}</span>)}
        </div>
      ) : (
        <p className="text-sm text-am-muted">{empty}</p>
      )}
    </div>
  )
}

function ReadmeTab({ agent }) {
  return (
    <div className="card shadow-card-md p-6 sm:p-8">
      <div className="flex items-center gap-2 mb-6 pb-4 border-b border-am-border">
        <BookOpen size={16} className="text-am-indigo" />
        <span className="font-semibold text-am-text">{agent.name}</span>
        <span className="text-am-muted">·</span>
        <span className="text-sm text-am-muted">README.md</span>
        {hasValue(agent.version) && (
          <span className="ml-auto text-xs text-am-muted font-mono border border-am-border px-2 py-0.5 rounded-full">v{agent.version}</span>
        )}
      </div>
      <div className="prose-light max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {agent.readme || '_No documentation published for this agent._'}
        </ReactMarkdown>
      </div>
    </div>
  )
}

function IntegrateTab({ agent }) {
  const [lang, setLang]     = useState('python')
  const [copied, setCopied] = useState(false)
  const endpoint      = agent.api_endpoint || null
  const paramsBlock   = (agent.env_var_keys || []).map((k) => `      "${k}": "YOUR_${k}"`).join(',\n')
  const jsParamsBlock = (agent.env_var_keys || []).map((k) => `      ${k}: process.env.${k}`).join(',\n')
  const tsParamsBlock = (agent.env_var_keys || []).map((k) => `    ${k}: process.env.${k}!`).join(',\n')

  const snippets = endpoint ? {
    python: `import requests\n\nresponse = requests.post(\n    "${endpoint}",\n    json={\n        "prompt": "Your task description here",\n        "params": {\n${paramsBlock}\n        }\n    }\n)\n\nprint(response.json())`,
    javascript: `const response = await fetch("${endpoint}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify({\n    prompt: "Your task description here",\n    params: {\n${jsParamsBlock}\n    }\n  })\n});\n\nconsole.log(await response.json());`,
    typescript: `const result = await fetch("${endpoint}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify({\n    prompt: "Your task description here",\n    params: {\n${tsParamsBlock}\n    }\n  })\n}).then((r) => r.json());`,
    curl: `curl -X POST "${endpoint}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "prompt": "Your task description here",\n    "params": {\n${paramsBlock}\n    }\n  }'`,
  } : {}

  function copy() {
    navigator.clipboard.writeText(snippets[lang] || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-5">
      <div className="card shadow-card-md p-5 flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div>
          <h3 className="font-semibold text-am-text mb-1">Integrate {agent.name}</h3>
          <p className="text-sm text-am-text-2">Real endpoint · real API keys</p>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-am-muted bg-am-surface border border-am-border rounded-lg px-3 py-2 whitespace-nowrap">
          <Globe size={12} />
          <span className="truncate max-w-[280px]">{endpoint || 'No public endpoint published'}</span>
        </div>
      </div>

      {(agent.env_var_keys || []).length > 0 && (
        <div className="rounded-xl p-4 flex items-start gap-3 bg-amber-50 border border-amber-200">
          <AlertCircle size={16} className="text-amber-500 flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-medium text-amber-700 mb-1">API Keys Required</div>
            <p className="text-xs text-amber-600 flex flex-wrap items-center gap-1">
              {(agent.env_var_keys || []).map((k) => (
                <code key={k} className="text-amber-700 bg-amber-100 border border-amber-200 px-1.5 py-0.5 rounded font-mono">{k}</code>
              ))}
            </p>
          </div>
        </div>
      )}

      {endpoint ? (
        <>
          <div className="card shadow-card-md overflow-hidden">
            <div className="flex border-b border-am-border px-1 pt-1 bg-am-surface">
              {['python','javascript','typescript','curl'].map((l) => (
                <button key={l} onClick={() => setLang(l)}
                  className={`px-4 py-2 text-xs font-mono font-medium rounded-t-lg transition-colors ${l === lang ? 'text-am-indigo bg-white border-t border-l border-r border-am-border -mb-px' : 'text-am-muted hover:text-am-text'}`}>
                  {l}
                </button>
              ))}
              <div className="flex-1" />
              <button onClick={copy} className="flex items-center gap-1.5 px-3 py-2 text-xs text-am-muted hover:text-am-text transition-colors">
                {copied ? <><Check size={12} className="text-am-emerald" /> Copied</> : <><Copy size={12} /> Copy</>}
              </button>
            </div>
            <pre className="p-5 text-sm font-mono text-slate-200 overflow-x-auto leading-relaxed bg-slate-900">
              <code>{snippets[lang]}</code>
            </pre>
          </div>
          <div className="card shadow-card-md p-5">
            <h4 className="text-sm font-semibold text-am-text mb-3 flex items-center gap-2">
              <Hash size={14} className="text-am-indigo" /> Response Structure
            </h4>
            <pre className="text-xs font-mono text-slate-200 leading-relaxed overflow-x-auto bg-slate-900 p-4 rounded-xl">
{`{
  "run_id": "...",
  "status": "...",
  "output": "...",
  "manifest_hash": "...",
  "platform_sig": "...",
  "duration_sec": 0,
  "proxy_metrics": {},
  "docker_image": "${agent.docker_image || ''}"
}`}
            </pre>
          </div>
        </>
      ) : (
        <div className="card shadow-card-md p-5">
          <p className="text-sm text-am-muted">This agent has no published public endpoint yet.</p>
        </div>
      )}
    </div>
  )
}

function TestTab({ agent, buyerWallet, onValidationStarted, onRunComplete, result, error, onResult, onError }) {
  const [prompt,   setPrompt]  = useState('')
  const [params,   setParams]  = useState(Object.fromEntries((agent.env_var_keys || []).map((k) => [k, ''])))
  const [running,  setRunning] = useState(false)
  const [elapsed,  setElapsed] = useState(0)
  const timerRef = useRef(null)

  useEffect(() => {
    setParams(Object.fromEntries((agent.env_var_keys || []).map((k) => [k, ''])))
  }, [agent.env_var_keys])

  // Tick elapsed time while running so user knows it's working
  useEffect(() => {
    if (running) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [running])

  async function run() {
    if (!prompt.trim()) return
    setRunning(true); onResult(null); onError(null)
    try {
      const data = await agentApi.run(agent.agent_id, { prompt, params }, buyerWallet)
      onResult(data)
      if (onRunComplete) onRunComplete()
      if (data.validation_started && onValidationStarted) {
        setTimeout(onValidationStarted, 2000)
      }
    } catch (e) {
      onError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const isSuccess = result?.status === 'success'
  const statusColor = isSuccess ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'

  return (
    <div className="space-y-4">
      <div className="card shadow-card-md p-5">
        <h3 className="font-semibold text-am-text mb-1 flex items-center gap-2">
          <Terminal size={15} className="text-am-indigo" /> Live Test
        </h3>
        <p className="text-sm text-am-text-2 mb-5">Execute {agent.name} directly against the live backend.</p>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-medium text-am-muted uppercase tracking-wider mb-2 block">
              Task Prompt <span className="text-rose-400">*</span>
            </label>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder={`Describe what you want ${agent.name} to do...`}
              rows={4} className="input resize-none" />
          </div>
          {(agent.env_var_keys || []).map((k) => (
            <div key={k}>
              <label className="text-xs font-mono font-medium text-amber-600 uppercase tracking-wider mb-2 block">{k}</label>
              <input type="password" placeholder={`Enter your ${k}`}
                value={params[k] || ''} onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
                className="input" />
            </div>
          ))}
          <button onClick={run} disabled={running || !prompt.trim()}
            className="btn-primary w-full py-3 flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed">
            {running ? (
              <>
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Running agent... {elapsed > 0 && <span className="font-mono text-white/70 text-xs">({elapsed}s)</span>}
              </>
            ) : (
              <><Play size={14} /> Run Agent</>
            )}
          </button>
          {!prompt.trim() && (
            <p className="text-xs text-am-muted text-center">Type a prompt above to enable the run button.</p>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl p-4 bg-rose-50 border border-rose-200 flex items-start gap-3">
          <AlertCircle size={16} className="text-rose-500 flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-medium text-rose-700 mb-1">Error</div>
            <pre className="text-xs text-rose-600 whitespace-pre-wrap">{error}</pre>
          </div>
        </div>
      )}

      {result && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className="card shadow-card-md p-5 space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h4 className="font-semibold text-am-text flex items-center gap-2">
              {isSuccess
                ? <CheckCircle size={15} className="text-emerald-500" />
                : <AlertCircle size={15} className="text-rose-500" />}
              Result
            </h4>
            <div className="flex items-center gap-2">
              {result.duration_sec != null && (
                <span className="text-xs text-am-muted font-mono">{result.duration_sec}s</span>
              )}
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${statusColor}`}>
                {result.status}
              </span>
            </div>
          </div>

          {/* Show error detail when agent failed */}
          {result.error && (
            <div className="rounded-lg p-3 bg-rose-50 border border-rose-200 text-xs text-rose-700 font-mono whitespace-pre-wrap">
              {result.error}
            </div>
          )}

          {/* Output */}
          <OutputErrorBoundary rawOutput={result.output}>
            <AgentOutputRenderer output={result.output} hasError={!!result.error} />
          </OutputErrorBoundary>

          {/* Proxy metrics */}
          {result.proxy_metrics && (result.proxy_metrics.llm_calls > 0 || result.proxy_metrics.search_calls > 0) && (
            <div className="flex flex-wrap gap-3 text-xs text-am-muted pt-1 border-t border-am-border">
              {result.proxy_metrics.llm_calls   > 0 && <span>LLM calls: <b className="text-am-text">{result.proxy_metrics.llm_calls}</b></span>}
              {result.proxy_metrics.search_calls > 0 && <span>Search calls: <b className="text-am-text">{result.proxy_metrics.search_calls}</b></span>}
              {result.proxy_metrics.total_tokens > 0 && <span>Tokens: <b className="text-am-text">{result.proxy_metrics.total_tokens}</b></span>}
            </div>
          )}
        </motion.div>
      )}
    </div>
  )
}

// ── Output error boundary ─────────────────────────────────────────────────────

class OutputErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { crashed: false, msg: '' } }
  static getDerivedStateFromError(e) { return { crashed: true, msg: e.message } }
  render() {
    if (this.state.crashed)
      return (
        <pre className="bg-slate-900 text-rose-300 rounded-xl p-4 font-mono text-xs overflow-x-auto">
          [Render error: {this.state.msg}]{'\n'}
          {JSON.stringify(this.props.rawOutput, null, 2)}
        </pre>
      )
    return this.props.children
  }
}

// ── Smart output renderer ─────────────────────────────────────────────────────

function isResearchReport(output) {
  return (
    output &&
    typeof output === 'object' &&
    typeof output.summary === 'string' &&
    (Array.isArray(output.key_findings) || Array.isArray(output.trends) || Array.isArray(output.data_points))
  )
}

function AgentOutputRenderer({ output, hasError }) {
  const [showRaw, setShowRaw] = useState(false)

  if (output == null) {
    return (
      <pre className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-sm">
        {hasError ? '(no output — see error above)' : '(empty output)'}
      </pre>
    )
  }

  if (typeof output === 'string') {
    return (
      <pre className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-sm overflow-x-auto max-h-96 whitespace-pre-wrap">
        {output}
      </pre>
    )
  }

  if (isResearchReport(output)) {
    return (
      <div className="space-y-3">
        {/* Toggle raw */}
        <div className="flex justify-end">
          <button
            onClick={() => setShowRaw(v => !v)}
            className="flex items-center gap-1.5 text-xs text-am-muted hover:text-am-indigo transition-colors"
          >
            {showRaw ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {showRaw ? 'Hide raw JSON' : 'View raw JSON'}
          </button>
        </div>

        {showRaw ? (
          <pre className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs overflow-x-auto max-h-96">
            {JSON.stringify(output, null, 2)}
          </pre>
        ) : (
          <div className="space-y-3">
            {/* Summary */}
            <div className="rounded-xl p-4 bg-indigo-50 border border-indigo-100">
              <div className="flex items-center gap-2 mb-2">
                <FileText size={13} className="text-am-indigo" />
                <span className="text-xs font-semibold text-am-indigo uppercase tracking-wider">Summary</span>
              </div>
              <p className="text-sm text-slate-700 leading-relaxed">{output.summary}</p>
            </div>

            {/* Key findings */}
            {Array.isArray(output.key_findings) && output.key_findings.length > 0 && (
              <div className="rounded-xl p-4 bg-white border border-am-border">
                <div className="flex items-center gap-2 mb-3">
                  <List size={13} className="text-emerald-500" />
                  <span className="text-xs font-semibold text-emerald-600 uppercase tracking-wider">Key Findings</span>
                </div>
                <ul className="space-y-2">
                  {output.key_findings.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                      <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                      <span>
                        {typeof f === 'object' ? f.point : f}
                        {typeof f === 'object' && f.source && (
                          <a href={f.source} target="_blank" rel="noopener noreferrer"
                            className="ml-2 inline-flex items-center gap-0.5 text-xs text-am-indigo hover:underline">
                            <ExternalLink size={10} /> source
                          </a>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Trends + Data points — side by side when both present */}
            <div className={`grid gap-3 ${Array.isArray(output.trends) && Array.isArray(output.data_points) ? 'grid-cols-2' : 'grid-cols-1'}`}>
              {Array.isArray(output.trends) && output.trends.length > 0 && (
                <div className="rounded-xl p-4 bg-white border border-am-border">
                  <div className="flex items-center gap-2 mb-3">
                    <BarChart2 size={13} className="text-violet-500" />
                    <span className="text-xs font-semibold text-violet-600 uppercase tracking-wider">Trends</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {output.trends.map((t, i) => (
                      <span key={i} className="px-2 py-1 rounded-full bg-violet-50 border border-violet-100 text-xs text-violet-700">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(output.data_points) && output.data_points.length > 0 && (
                <div className="rounded-xl p-4 bg-white border border-am-border">
                  <div className="flex items-center gap-2 mb-3">
                    <BarChart2 size={13} className="text-amber-500" />
                    <span className="text-xs font-semibold text-amber-600 uppercase tracking-wider">Data Points</span>
                  </div>
                  <ul className="space-y-1.5">
                    {output.data_points.map((d, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                        <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Conclusion */}
            {output.conclusion && (
              <div className="rounded-xl p-4 bg-slate-50 border border-am-border">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle size={13} className="text-slate-400" />
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Conclusion</span>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed italic">{output.conclusion}</p>
              </div>
            )}

            {/* Sources */}
            {Array.isArray(output.sources) && output.sources.length > 0 && (
              <div className="rounded-xl p-3 bg-white border border-am-border">
                <div className="flex items-center gap-2 mb-2">
                  <Globe size={12} className="text-am-muted" />
                  <span className="text-xs font-semibold text-am-muted uppercase tracking-wider">Sources</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {output.sources.map((s, i) => {
                    let hostname = s
                    try { hostname = new URL(s).hostname.replace('www.', '') } catch {}
                    const isUrl = s.startsWith('http')
                    return (
                      <a key={i} href={isUrl ? s : undefined} target={isUrl ? '_blank' : undefined}
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-xs text-am-indigo hover:bg-indigo-50 transition-colors truncate max-w-xs">
                        <ExternalLink size={9} />
                        {hostname}
                      </a>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  // Generic JSON object fallback
  return (
    <pre className="bg-slate-900 text-slate-200 rounded-xl p-4 font-mono text-xs overflow-x-auto max-h-96">
      {JSON.stringify(output, null, 2)}
    </pre>
  )
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="card shadow-card-md p-5">
      <div className="mb-4">
        <div className="font-semibold text-am-text text-sm">{title}</div>
        <div className="text-xs text-am-muted mt-0.5">{subtitle}</div>
      </div>
      {children}
    </div>
  )
}
