import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sparkles, Send, Loader2, CheckCircle, XCircle,
  Zap, GitBranch, DollarSign, Play, AlertCircle,
  Clock, RotateCcw, Package, Star, ArrowLeft,
  Code2, Lock, Globe, Terminal, Copy, Check, ShoppingCart,
} from 'lucide-react'
import { taskApi, agentApi } from '../api/agentApi'
import { useAuth } from '../context/AuthContext'
import SubTaskCard from '../components/common/SubTaskCard'
import AgentSelector from '../components/common/AgentSelector'

// ── Constants ──────────────────────────────────────────────────────────────────

const PAGE_STATES = {
  idle: 'idle',
  planning: 'planning',
  pack_selecting: 'pack_selecting',
  pack_detail: 'pack_detail',
  plan_ready: 'plan_ready',
  executing: 'executing',
  validating: 'validating',
  done: 'done',
  failed: 'failed',
}

const PACK_PALETTE = [
  { icon: Package, color: '#6366f1' },
  { icon: Zap, color: '#10b981' },
  { icon: Star, color: '#f59e0b' },
]

const DOMAIN_COLORS = {
  research:  { bg: '#eef2ff', color: '#6366f1', border: '#c7d2fe' },
  code:      { bg: '#f0fdf4', color: '#16a34a', border: '#bbf7d0' },
  summarize: { bg: '#fff7ed', color: '#ea580c', border: '#fed7aa' },
  analyze:   { bg: '#fdf4ff', color: '#9333ea', border: '#e9d5ff' },
  write:     { bg: '#eff6ff', color: '#2563eb', border: '#bfdbfe' },
  translate: { bg: '#fefce8', color: '#ca8a04', border: '#fef08a' },
  generate:  { bg: '#fff1f2', color: '#e11d48', border: '#fecdd3' },
  review:    { bg: '#f0fdfa', color: '#0d9488', border: '#99f6e4' },
}

function domainStyle(domain) {
  return DOMAIN_COLORS[domain?.toLowerCase()] || { bg: '#f8fafc', color: '#64748b', border: '#e2e8f0' }
}

const PACK_DETAIL_TABS = [
  { id: 'overview', label: 'Overview', icon: Package },
  { id: 'live-test', label: 'Live Test', icon: Play },
  { id: 'integrate', label: 'Integrate', icon: Code2 },
]

const SENSITIVE_ENV_KEY_PARTS = [
  'PRIVATE_KEY',
  'SECRET_KEY',
  'WALLET_KEY',
  'MNEMONIC',
  'SEED_PHRASE',
]

function isBuyerProvidedEnvKey(key) {
  const normalized = String(key || '').toUpperCase()
  return normalized && !SENSITIVE_ENV_KEY_PARTS.some(part => normalized.includes(part))
}

function isFailedStepStatus(status) {
  return ['error', 'failed', 'failure', 'timeout'].includes(status)
}

function validationBadgeClass(result) {
  const verdict = result?.consensus_verdict
  const status = result?.status
  if (verdict === 'VALID' || status === 'validated') return 'bg-emerald-50 text-emerald-700'
  if (verdict === 'INVALID' || ['rejected', 'failed'].includes(status)) return 'bg-rose-50 text-rose-700'
  return 'bg-indigo-50 text-am-indigo'
}

// ── Small shared helpers ───────────────────────────────────────────────────────

function PackCard({ pack, index, onSelect }) {
  const slot = PACK_PALETTE[index % PACK_PALETTE.length]
  const Icon = slot.icon
  const color = slot.color
  const stars = Math.round((pack.quality_score || 0) * 5)
  return (
    <motion.button
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={() => onSelect(pack)}
      className="w-full text-left card p-5 border-2 hover:shadow-card-lg transition-all duration-200"
      style={{ borderColor: `${color}30` }}
    >
      <div className="flex items-start gap-3 mb-3">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: `${color}15` }}>
          <Icon size={16} style={{ color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-am-text text-sm">{pack.name}</div>
          <div className="text-xs text-am-muted mt-0.5 line-clamp-2">{pack.description}</div>
        </div>
        <div className="text-xs font-mono font-semibold shrink-0" style={{ color }}>
          {pack.total_eth > 0 ? `${pack.total_eth.toFixed(5)} ETH` : 'Free'}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(pack.agents || []).map(a => (
          <span key={a.agent_id}
            className="text-xs px-2 py-0.5 rounded-full bg-am-surface border border-am-border text-am-text-2">
            {a.agent_name || a.agent_id}
          </span>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <Star key={i} size={10}
              className={i < stars ? 'text-amber-400 fill-amber-400' : 'text-am-border'} />
          ))}
          <span className="text-xs text-am-muted ml-1">~{pack.estimated_duration_min} min</span>
        </div>
        <span className="text-xs font-medium px-3 py-1 rounded-full"
          style={{ background: `${color}12`, color }}>
          View →
        </span>
      </div>
    </motion.button>
  )
}

function ModeBadge({ mode }) {
  const isPipeline = mode === 'pipeline'
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${isPipeline ? 'bg-violet-50 text-violet-700 border-violet-200' : 'bg-indigo-50 text-am-indigo border-indigo-200'
      }`}>
      {isPipeline ? <GitBranch size={11} /> : <Zap size={11} />}
      {isPipeline ? 'Pipeline' : 'Solo'}
    </span>
  )
}

function TotalPrice({ agents }) {
  const total = agents.reduce((sum, a) => sum + (a.price_per_task || 0), 0)
  if (total === 0) return null
  return (
    <div className="flex items-center gap-1.5 text-sm font-semibold text-am-text">
      <DollarSign size={14} className="text-am-emerald" />
      {total.toFixed(4)} ETH total
    </div>
  )
}

// ── Pack Payment Modal ─────────────────────────────────────────────────────────

function PackPayModal({ pack, purchaseInfo, walletAddress, purchasing, error, onConfirm, onClose }) {
  const isFree = !purchaseInfo?.total_eth || purchaseInfo.total_eth === 0
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <motion.div
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95 }}
        className="card p-6 w-full max-w-md shadow-card-md"
      >
        <h2 className="text-lg font-bold text-am-text mb-1">Get Access · {pack.name}</h2>
        <p className="text-sm text-am-muted mb-5">
          {isFree
            ? 'This pack is free. Confirm to unlock Live Test and Integrate tabs.'
            : 'Payment will be locked in escrow and distributed to agents after validation.'}
        </p>

        <div className="space-y-3 mb-5">
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Agents</span>
            <span className="text-am-text font-medium">{(pack.agents || []).length} agent{(pack.agents || []).length > 1 ? 's' : ''}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Total cost</span>
            <span className="font-bold text-am-text">
              {isFree ? 'Free' : `${purchaseInfo.total_eth.toFixed(5)} ETH`}
            </span>
          </div>
          {!isFree && (
            <div className="flex justify-between text-sm">
              <span className="text-am-muted">Escrow contract</span>
              <span className="font-mono text-xs text-am-muted truncate max-w-[200px]">
                {purchaseInfo.contract_address || 'Not configured'}
              </span>
            </div>
          )}
          <div className="flex justify-between text-sm">
            <span className="text-am-muted">Your wallet</span>
            <span className="font-mono text-xs text-am-muted">
              {walletAddress ? `${walletAddress.slice(0, 8)}…${walletAddress.slice(-6)}` : 'Not connected'}
            </span>
          </div>
        </div>

        {error && (
          <div className="rounded-lg p-3 bg-rose-50 border border-rose-200 text-xs text-rose-600 mb-4 flex items-start gap-2">
            <AlertCircle size={14} className="shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 btn-secondary text-sm py-2.5">Cancel</button>
          <button
            onClick={onConfirm}
            disabled={purchasing}
            className="flex-1 btn-primary text-sm py-2.5 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {purchasing ? (
              <><Loader2 size={14} className="animate-spin" /> Processing…</>
            ) : isFree ? (
              <><CheckCircle size={14} /> Confirm Access</>
            ) : (
              <><ShoppingCart size={14} /> Pay {purchaseInfo.total_eth.toFixed(5)} ETH</>
            )}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── Pack Detail Tabs ───────────────────────────────────────────────────────────

function PackOverviewTab({ pack, agents, subtasks, apiKeys, setApiKeys, requiredKeys, onGetAccess, isGettingAccess, hasAccess }) {
  const color = '#6366f1'
  const stars = Math.round((pack.quality_score || 0) * 5)
  const displayAgents = agents.length > 0 ? agents : (pack.agents || [])
  const displaySubtasks = subtasks.length > 0 ? subtasks : (pack.subtasks || [])

  return (
    <div className="space-y-5">
      {/* Pack hero */}
      <div className="card p-5 shadow-card-md">
        <div className="flex items-start gap-4 mb-4">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `${color}15`, border: `1px solid ${color}30` }}>
            <Package size={20} style={{ color }} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-bold text-am-text text-base">{pack.name}</div>
            <div className="text-sm text-am-muted mt-1 leading-relaxed">{pack.description}</div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-lg font-bold text-am-text">
              {pack.total_eth > 0 ? `${pack.total_eth.toFixed(5)} ETH` : 'Free'}
            </div>
            <div className="flex items-center gap-1 justify-end mt-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <Star key={i} size={10} className={i < stars ? 'text-amber-400 fill-amber-400' : 'text-am-border'} />
              ))}
              <span className="text-xs text-am-muted ml-1">~{pack.estimated_duration_min} min</span>
            </div>
          </div>
        </div>

        {/* Agents */}
        <div className="mb-4">
          <div className="text-xs font-semibold text-am-muted uppercase tracking-wide mb-2">Agents in this pack</div>
          <div className="flex flex-wrap gap-2">
            {displayAgents.map((a, i) => (
              <div key={a.agent_id || i}
                className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-am-surface border border-am-border text-sm">
                <div className="w-6 h-6 rounded-lg flex items-center justify-center text-xs font-bold text-white"
                  style={{ background: PACK_PALETTE[i % PACK_PALETTE.length].color }}>
                  {(a.agent_name || a.agent_id || '?')[0].toUpperCase()}
                </div>
                <span className="text-am-text font-medium">{a.agent_name || a.agent_id}</span>
                {a.price_per_task > 0 && (
                  <span className="text-xs text-am-muted font-mono">{a.price_per_task.toFixed(5)} ETH</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Subtasks */}
        {displaySubtasks.length > 0 && (
          <div className="mb-4">
            <div className="text-xs font-semibold text-am-muted uppercase tracking-wide mb-2">
              Execution plan · {displaySubtasks.length} subtask{displaySubtasks.length > 1 ? 's' : ''}
            </div>
            <div className="space-y-1.5">
              {displaySubtasks.map((st, i) => (
                <div key={st.id || i}
                  className="flex items-start gap-2.5 p-2.5 rounded-lg bg-am-surface border border-am-border">
                  <div className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 mt-0.5"
                    style={{ background: color }}>
                    {i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-am-text">{st.description}</div>
                    {st.domain && <span className="text-xs text-am-muted font-mono">{st.domain}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <ModeBadge mode={pack.mode} />
          {pack.total_eth > 0 && (
            <span className="text-xs text-am-muted">
              · distributed to {displayAgents.length} agents via escrow
            </span>
          )}
        </div>
      </div>

      {/* CTA */}
      {!hasAccess ? (
        <button
          onClick={onGetAccess}
          disabled={isGettingAccess}
          className="btn-primary w-full py-3.5 flex items-center justify-center gap-2 text-sm font-semibold disabled:opacity-60"
        >
          {isGettingAccess
            ? <><Loader2 size={16} className="animate-spin" /> Preparing…</>
            : <><ShoppingCart size={16} /> Get Access</>
          }
        </button>
      ) : (
        <div className="flex items-center justify-center gap-2 text-sm text-am-emerald font-medium py-2">
          <CheckCircle size={16} />
          Access granted — go to Live Test to run the pipeline
        </div>
      )}
    </div>
  )
}

function AgentFeedbackInline({ agentId }) {
  const [stars,   setStars]   = useState(0)
  const [hover,   setHover]   = useState(0)
  const [loading, setLoading] = useState(false)
  const [done,    setDone]    = useState(false)
  const [error,   setError]   = useState('')

  if (done) return (
    <div className="flex items-center gap-1.5 text-xs text-emerald-600 mt-2">
      <CheckCircle size={11} /> Avis soumis ✓
    </div>
  )
  return (
    <div className="flex items-center gap-2 mt-2 pt-2 border-t border-am-border">
      <span className="text-xs text-am-muted">Votre avis :</span>
      {[1,2,3,4,5].map(s => (
        <button key={s} onClick={() => setStars(s)}
          onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(0)}
          className="text-lg focus:outline-none">
          <span style={{ color: s <= (hover || stars) ? '#f59e0b' : '#cbd5e1' }}>★</span>
        </button>
      ))}
      {stars > 0 && (
        <button onClick={async () => {
          setLoading(true); setError('')
          try {
            if (!window.ethereum) throw new Error('MetaMask requis')
            const info = await agentApi.getFeedbackInfo(agentId, stars)
            if (!info.reputation_address || info.call_data === '0x')
              throw new Error('Contrat non configuré')
            const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
            const chainHex = await window.ethereum.request({ method: 'eth_chainId' })
            if (parseInt(chainHex, 16) !== 84532) {
              try { await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14A34' }] }) }
              catch { throw new Error('Veuillez passer sur Base Sepolia dans MetaMask') }
            }
            const txHash = await window.ethereum.request({
              method: 'eth_sendTransaction',
              params: [{ from: accounts[0], to: info.reputation_address, data: info.call_data, gas: info.gas ?? '0x30D40' }],
            })
            await agentApi.notifyFeedback(agentId, { tx_hash: txHash, stars }).catch(() => {})
            setDone(true)
          } catch (e) { setError(e.message) }
          finally { setLoading(false) }
        }} disabled={loading}
          className="text-xs px-2 py-0.5 rounded-full bg-am-indigo text-white disabled:opacity-50 ml-1">
          {loading ? '...' : 'Envoyer'}
        </button>
      )}
      {error && <span className="text-xs text-rose-500">{error}</span>}
    </div>
  )
}

// ── Reusable accordion row ────────────────────────────────────────────────────
function AccordionRow({ icon, title, right, defaultOpen = false, children, highlight = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`rounded-xl border overflow-hidden transition-all ${highlight ? 'border-am-indigo/30' : 'border-am-border'} bg-white`}>
      <button
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${open ? 'bg-am-surface/60' : 'hover:bg-am-surface/40'}`}
      >
        {icon}
        <span className="font-medium text-sm text-am-text flex-1 min-w-0 truncate">{title}</span>
        {right}
        <span className={`text-am-muted transition-transform duration-200 shrink-0 ${open ? 'rotate-180' : ''}`}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"/></svg>
        </span>
      </button>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.18 }}
          className="border-t border-am-border"
        >
          <div className="p-4">
            {children}
          </div>
        </motion.div>
      )}
    </div>
  )
}

// ── Validation accordion for one agent ───────────────────────────────────────
function ValidationAgentRow({ agentId, result, isValidating }) {
  const score    = result.aggregated_score ?? null
  const verdict  = result.consensus_verdict || result.status || '—'
  const judges   = result.judges || []
  const isValid  = verdict === 'VALID' || verdict === 'APPROVED'
  const isPending = isValidating && score === null

  return (
    <AccordionRow
      defaultOpen={false}
      icon={
        isPending
          ? <Loader2 size={13} className="animate-spin text-am-indigo shrink-0" />
          : isValid
          ? <CheckCircle size={13} className="text-emerald-500 shrink-0" />
          : <XCircle size={13} className="text-rose-400 shrink-0" />
      }
      title={<span className="font-mono text-xs">{agentId}</span>}
      right={
        <div className="flex items-center gap-2 shrink-0">
          {score !== null && (
            <span className="text-sm font-bold text-am-text tabular-nums">{score}<span className="text-xs font-normal text-am-muted">/100</span></span>
          )}
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${validationBadgeClass(result)}`}>
            {isPending ? 'pending…' : verdict}
          </span>
        </div>
      }
    >
      {/* Buyer view: score summary per judge — no justification (internal audit) */}
      {judges.length === 0
        ? <p className="text-xs text-am-muted italic">No judge data yet.</p>
        : (
          <div className="space-y-1.5">
            {judges.map(j => {
              const jValid = j.verdict === 'VALID' || j.verdict === 'APPROVED'
              return (
                <div key={j.judge_id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-am-surface border border-am-border">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${jValid ? 'bg-emerald-400' : 'bg-rose-400'}`} />
                  <span className="text-xs text-am-muted flex-1">Judge {judges.indexOf(j) + 1}</span>
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${jValid ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-600'}`}>
                    {j.verdict || '—'}
                  </span>
                  <span className="text-xs font-bold text-am-indigo tabular-nums">{j.score ?? '—'}<span className="font-normal text-am-muted">/100</span></span>
                </div>
              )
            })}
          </div>
        )
      }
      {!isValidating && <div className="mt-3"><AgentFeedbackInline agentId={agentId} /></div>}
    </AccordionRow>
  )
}

function PackLiveTestTab({ agents, subtasks = [], steps, finalOutput, valTaskId, isExecuting, isValidating, isDone, isFailed, taskReady, onStartExecution, onRunAgain, apiKeys, setApiKeys, requiredKeys, validationResults = {} }) {
  const succeededSteps = steps.filter(s => s.status === 'success').length
  const hasValidation  = isValidating || Object.keys(validationResults).length > 0

  return (
    <div className="space-y-4">

      {/* ── Run button ── */}
      {taskReady && !isExecuting && !isDone && !isFailed && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card p-5">
          <h3 className="font-semibold text-am-text mb-1 flex items-center gap-2">
            <Play size={15} className="text-am-indigo" /> Live Test
          </h3>
          <p className="text-sm text-am-text-2 mb-4">Access granted. Start the pipeline to see real-time execution.</p>
          {requiredKeys.length > 0 && (
            <div className="space-y-4 mb-6">
              <div className="text-xs font-semibold text-am-muted uppercase tracking-wider">Required Agent API Keys</div>
              {requiredKeys.map(k => {
                const assoc = agents.filter(a => (a.env_var_keys || []).includes(k)).map(a => a.agent_name || a.agent_id)
                return (
                  <div key={k} className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-mono font-bold text-amber-600 uppercase tracking-wider">{k}</label>
                      <span className="text-[10px] text-am-muted italic">Needed by: {assoc.join(', ')}</span>
                    </div>
                    <input type="password" value={apiKeys[k] || ''}
                      onChange={e => setApiKeys(prev => ({ ...prev, [k]: e.target.value }))}
                      placeholder={`Enter your ${k}`}
                      className="w-full text-xs px-3 py-2.5 rounded-lg border border-am-border bg-white text-am-text outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/20 font-mono transition-all shadow-sm"
                    />
                  </div>
                )
              })}
            </div>
          )}
          <button onClick={onStartExecution} className="btn-primary w-full py-3 flex items-center justify-center gap-2 text-sm font-semibold">
            <Zap size={16} /> Start Pipeline
          </button>
        </motion.div>
      )}

      {/* ── Status bar ── */}
      {(isExecuting || isValidating || isDone || isFailed) && (
        <div className="flex items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            {isExecuting  && <><Loader2 size={13} className="animate-spin text-amber-500" /><span className="text-amber-600">Executing…</span></>}
            {isValidating && <><Loader2 size={13} className="animate-spin text-am-indigo" /><span className="text-am-indigo">Validating with AI judges…</span></>}
            {isDone       && <><CheckCircle size={13} className="text-am-emerald" /><span className="text-am-emerald font-semibold">Completed</span></>}
            {isFailed     && <><XCircle size={13} className="text-am-rose" /><span className="text-am-rose">Failed</span></>}
          </div>
          {steps.length > 0 && (
            <span className="text-xs text-am-muted">{succeededSteps}/{steps.length} agents succeeded</span>
          )}
          {(isDone || isFailed) && onRunAgain && (
            <button onClick={onRunAgain} className="flex items-center gap-1.5 text-xs font-medium text-am-indigo border border-am-indigo/30 hover:border-am-indigo/60 px-3 py-1.5 rounded-lg transition-all">
              <RotateCcw size={12} /> Run Again
            </button>
          )}
        </div>
      )}

      {/* ── Agent steps (accordions) ── */}
      {steps.length > 0 && (
        <div className="space-y-2">
          {steps.map((step, i) => {
            const subtask  = subtasks.find(st => st.id === step.subtask_id)
            const ok       = step.status === 'success'
            const fail     = isFailedStepStatus(step.status)
            const running  = !ok && !fail
            const ds       = domainStyle(subtask?.domain)
            const hasOut   = ok && step.output && step.output.trim().length > 0
            const writerOut = parseWriterOutput(step.output)

            return (
              <AccordionRow
                key={step.subtask_id || i}
                defaultOpen={false}
                icon={
                  running ? <Loader2 size={13} className="animate-spin text-am-indigo shrink-0" />
                  : ok    ? <CheckCircle size={13} className="text-emerald-500 shrink-0" />
                          : <XCircle size={13} className="text-rose-400 shrink-0" />
                }
                title={
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="text-xs text-am-muted font-bold shrink-0">#{i + 1}</span>
                    {subtask?.domain && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border shrink-0"
                        style={{ background: ds.bg, color: ds.color, borderColor: ds.border }}>
                        {subtask.domain}
                      </span>
                    )}
                    <span className="truncate text-sm font-medium text-am-text">
                      {step.agent_name || step.agent_id || '?'}
                    </span>
                  </span>
                }
                right={
                  step.duration_sec != null && (
                    <span className="flex items-center gap-1 text-xs text-am-muted font-mono shrink-0">
                      <Clock size={10} />{step.duration_sec.toFixed(1)}s
                    </span>
                  )
                }
              >
                {/* Subtask description */}
                {subtask?.description && (
                  <p className="text-xs text-am-muted mb-3 italic">{subtask.description}</p>
                )}

                {/* Output */}
                {hasOut && (
                  <div className="space-y-2">
                    {writerOut ? <WriterOutputBlock output={writerOut} /> : <SmartOutput raw={step.output} />}
                  </div>
                )}

                {/* Error */}
                {fail && step.error && (
                  <div className="flex items-start gap-1.5 text-xs text-rose-500 bg-rose-50 rounded-lg px-3 py-2">
                    <XCircle size={11} className="shrink-0 mt-0.5" />
                    {step.error}
                  </div>
                )}

                {/* Star rating */}
                {isDone && ok && <StepRating agentId={step.agent_id} />}
              </AccordionRow>
            )
          })}
        </div>
      )}

      {/* ── Final output (accordion) ── */}
      {finalOutput && (
        <AccordionRow
          defaultOpen={true}
          highlight
          icon={<CheckCircle size={13} className="text-emerald-500 shrink-0" />}
          title={<span className="font-semibold text-am-text">Final Output</span>}
          right={
            valTaskId && (
              <span className="text-[10px] text-am-muted font-mono bg-am-surface px-2 py-0.5 rounded-full border border-am-border shrink-0">
                val: {valTaskId.slice(0, 12)}…
              </span>
            )
          }
        >
          <FinalOutputBody output={finalOutput} />
        </AccordionRow>
      )}

      {/* ── Validation (accordion per agent) ── */}
      {hasValidation && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 px-1">
            {isValidating
              ? <Loader2 size={12} className="animate-spin text-am-indigo" />
              : <CheckCircle size={12} className="text-am-emerald" />
            }
            <span className="text-xs font-semibold text-am-muted uppercase tracking-wider">
              {isValidating ? 'AI Judges — validation in progress' : 'Validation Results'}
            </span>
          </div>
          {Object.entries(validationResults).map(([agentId, result]) => (
            <ValidationAgentRow key={agentId} agentId={agentId} result={result} isValidating={isValidating} />
          ))}
          {isValidating && Object.keys(validationResults).length === 0 && (
            <div className="flex items-center gap-2 py-4 pl-4 text-sm text-am-muted">
              <Loader2 size={14} className="animate-spin text-am-indigo" />
              Waiting for judge responses…
            </div>
          )}
        </div>
      )}

      {/* ── Loading placeholder ── */}
      {isExecuting && steps.length === 0 && (
        <div className="flex flex-col items-center py-12 gap-3">
          <Loader2 size={24} className="animate-spin text-am-indigo" />
          <p className="text-sm text-am-muted">Agents are processing your task…</p>
        </div>
      )}

      {!taskReady && !isExecuting && !isDone && (
        <div className="flex flex-col items-center py-12 gap-3 text-am-muted">
          <Lock size={24} />
          <p className="text-sm">Get access first to start the pipeline.</p>
        </div>
      )}
    </div>
  )
}

function PackIntegrateTab({ pack, agents }) {
  const [lang, setLang] = useState('python')
  const [copied, setCopied] = useState(false)
  const [platformUrl, setPlatformUrl] = useState(null)

  useEffect(() => {
    const agentId = (agents || []).find(a => a.agent_id)?.agent_id
                 || (pack?.agents || []).find(a => a.agent_id)?.agent_id
    if (!agentId) return
    agentApi.endpoint(agentId).then(data => {
      if (data?.platform_endpoint) {
        const base = data.platform_endpoint.replace(/\/api\/v1\/agents\/.+$/, '')
        if (base) setPlatformUrl(base)
      }
    }).catch(() => {})
  }, [agents, pack])

  const baseUrl = platformUrl || window.location.origin.replace(':5173', ':8000')

  const snippets = {
    python: `import requests, time

BASE = "${baseUrl}/api/v1"

# Launch the pipeline (platform picks mode + agents automatically)
resp = requests.post(f"{BASE}/tasks/run", json={
    "prompt":       "<your task prompt>",
    "agent_params": {
        "GROQ_API_KEY":   "YOUR_KEY",
        "TAVILY_API_KEY": "YOUR_KEY",  # optional
    },
})
data    = resp.json()
task_id = data["task_id"]
print(f"mode={data.get('mode')}  agents={[a.get('agent_id') for a in data.get('agents', [])]}")

# Poll for result (every 10 s — validation takes ~60-90 s after execution)
while True:
    r = requests.get(f"{BASE}/tasks/{task_id}/status").json()
    status = r.get("status")
    print(f"  [{status}]")
    if status == "done":
        print(r.get("final_output", "(empty)"))
        break
    if status == "failed":
        print("Pipeline failed:", r.get("steps"))
        break
    time.sleep(10)`,

    curl: `# Launch pipeline
curl -X POST "${baseUrl}/api/v1/tasks/run" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompt": "Your task here",
    "agent_params": {
      "GROQ_API_KEY": "YOUR_KEY"
    }
  }'

# Poll status (replace <task_id> with value from above)
curl "${baseUrl}/api/v1/tasks/<task_id>/status"`,

    javascript: `const BASE = "${baseUrl}/api/v1";

// Launch pipeline — platform selects mode + agents automatically
const { task_id, mode, agents } = await fetch(\`\${BASE}/tasks/run\`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    prompt: "Your task here",
    agent_params: { GROQ_API_KEY: "YOUR_KEY" },
  }),
}).then(r => r.json());

console.log("mode:", mode, "agents:", agents.map(a => a.agent_id));

// Poll every 10 s until done or failed
const poll = async () => {
  const r = await fetch(\`\${BASE}/tasks/\${task_id}/status\`).then(r => r.json());
  if (r.status === "done")   return r.final_output;
  if (r.status === "failed") throw new Error("Pipeline failed");
  await new Promise(res => setTimeout(res, 10_000));
  return poll();
};
console.log(await poll());`,
  }

  const statusExample = [
    '{',
    '  "task_id":      "...",',
    '  "status":       "done | failed | executing | validating",',
    '  "final_output": "...",',
    '  "steps": [',
    '    { "subtask_id": "...", "agent_id": "...", "status": "success", "duration_sec": 1.2 }',
    '  ],',
    '  "val_task_id": "..."',
    '}',
  ].join('\n')

  function copy() {
    navigator.clipboard.writeText(snippets[lang] || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-5">
      <div className="card shadow-card-md p-5">
        <h3 className="font-semibold text-am-text mb-1">Integrate · {pack.name}</h3>
        <p className="text-sm text-am-text-2 mb-3">Call this pipeline programmatically.</p>
        <div className="flex items-center gap-2 text-xs font-mono text-am-muted bg-am-surface border border-am-border rounded-lg px-3 py-2">
          <Globe size={12} />
          <span className="truncate">{baseUrl}/api/v1/tasks/run</span>
        </div>
      </div>

      <div className="card shadow-card-md overflow-hidden">
        <div className="flex border-b border-am-border px-1 pt-1 bg-am-surface">
          {['python', 'javascript', 'curl'].map(l => (
            <button key={l} onClick={() => setLang(l)}
              className={`px-4 py-2 text-xs font-mono font-medium rounded-t-lg transition-colors ${l === lang
                  ? 'text-am-indigo bg-white border-t border-l border-r border-am-border -mb-px'
                  : 'text-am-muted hover:text-am-text'
                }`}>
              {l}
            </button>
          ))}
          <div className="flex-1" />
          <button onClick={copy} className="flex items-center gap-1.5 px-3 py-2 text-xs text-am-muted hover:text-am-text transition-colors">
            {copied ? <><Check size={12} className="text-am-emerald" /> Copied</> : <><Copy size={12} /> Copy</>}
          </button>
        </div>
        <pre className="p-5 text-xs font-mono text-slate-200 overflow-x-auto leading-relaxed bg-slate-900 max-h-96">
          <code>{snippets[lang]}</code>
        </pre>
      </div>

      <div className="card shadow-card-md p-5">
        <h4 className="text-sm font-semibold text-am-text mb-3 flex items-center gap-2">
          <Terminal size={14} className="text-am-indigo" /> Status Response
        </h4>
        <pre className="text-xs font-mono text-slate-200 leading-relaxed overflow-x-auto bg-slate-900 p-4 rounded-xl">
          {statusExample}
        </pre>
      </div>
    </div>
  )
}

// ── Writer output detection ───────────────────────────────────────────────────

function parseWriterOutput(raw) {
  if (!raw) return null
  try {
    const p = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!p || typeof p !== 'object') return null
    // New format: sections is a dict {heading: prose}
    if (typeof p.title === 'string' && p.sections && typeof p.sections === 'object' && !Array.isArray(p.sections))
      return { ...p, _format: 'dict' }
    // Old format: title + content string
    if (typeof p.title === 'string' && typeof p.content === 'string')
      return { ...p, _format: 'legacy' }
  } catch { /* ignore */ }
  return null
}

// Remove artifacts injected by the writer agent into the content string:
// - Leading repeated quoted title: `"Title", "`
// - Trailing JSON fragments: `.", "Section1", "Section2", 246, "report"`
function _cleanWriterContent(content, title = '') {
  if (!content) return ''
  let c = content.trim()

  // Strip leading: `"<title>", "` or `"<title>", `
  if (title) {
    const esc = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    c = c.replace(new RegExp(`^["""]\\s*${esc}\\s*["""][,.]?\\s*["""]?`), '').trim()
  }

  // Strip trailing: everything after the last sentence-ending punctuation
  // if what follows looks like JSON metadata (quotes, commas, numbers)
  const lastPunct = Math.max(c.lastIndexOf('.'), c.lastIndexOf('!'), c.lastIndexOf('?'))
  if (lastPunct > 0) {
    const after = c.slice(lastPunct + 1).trim()
    if (after.length > 0 && /^[\s"",\d\w]+$/.test(after) && after.includes('"')) {
      c = c.slice(0, lastPunct + 1).trim()
    }
  }

  return c
}

// Split content into sections using the section names as headers when they
// appear as a standalone line or immediately precede a newline.
function _splitBySections(content, sections) {
  if (!sections || sections.length === 0) return null
  const escaped = sections.map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'g')
  const parts = content.split(pattern).filter(Boolean)
  if (parts.length <= 1) return null

  const result = []
  let i = 0
  // If first part doesn't match a section header, treat as intro
  if (!sections.includes(parts[0])) {
    result.push({ heading: null, body: parts[0].trim() })
    i = 1
  }
  while (i < parts.length) {
    const heading = parts[i]
    const body    = (parts[i + 1] || '').trim()
    if (sections.includes(heading) && body) result.push({ heading, body })
    i += 2
  }
  return result.length > 1 ? result : null
}

function WriterOutputBlock({ output }) {
  const sectionColor = '#6366f1'
  const headerBg     = '#eef2ff'
  const headerBorder = '#c7d2fe'

  // Build sections array from new dict format or legacy content string
  let sectionEntries = []
  if (output._format === 'dict' && output.sections) {
    sectionEntries = Object.entries(output.sections)
  } else if (output.content) {
    // Legacy: show as single section
    const cleaned = _cleanWriterContent(output.content, output.title)
    sectionEntries = [['', cleaned]]
  }

  return (
    <div className="space-y-3">
      {/* Title header */}
      <div className="rounded-xl px-4 py-3" style={{ background: headerBg, border: `1px solid ${headerBorder}` }}>
        <span className="text-[10px] font-semibold uppercase tracking-wider block mb-0.5" style={{ color: sectionColor }}>
          Report
        </span>
        <h3 className="font-bold text-am-text text-base leading-snug">{output.title}</h3>
      </div>

      {/* Sections */}
      <div className="space-y-4">
        {sectionEntries.map(([heading, body], i) => (
          <div key={i}>
            {heading && (
              <div className="text-[11px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: sectionColor }}>
                {heading}
              </div>
            )}
            <p className="text-sm text-slate-700 leading-relaxed">{body}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Smart output renderer ─────────────────────────────────────────────────────

// snake_case / camelCase → Title Case label
function _toLabel(key) {
  return key.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/\b\w/g, c => c.toUpperCase())
}

// Extract a readable string from a list item (object or primitive)
// Priority: semantic content keys > longest non-URL string > URL > raw JSON
const _ITEM_CONTENT_KEYS = ['point', 'text', 'description', 'title', 'insight', 'finding',
                             'label', 'name', 'content', 'summary', 'value', 'detail']
function _itemText(item) {
  if (typeof item === 'string') return item
  if (typeof item === 'object' && item !== null) {
    for (const k of _ITEM_CONTENT_KEYS) {
      if (typeof item[k] === 'string' && item[k].length > 0) return item[k]
    }
    const nonUrl = Object.values(item).filter(v => typeof v === 'string' && !v.startsWith('http'))
    if (nonUrl.length > 0) return nonUrl.sort((a, b) => b.length - a.length)[0]
    const all = Object.values(item).filter(v => typeof v === 'string')
    return all.sort((a, b) => b.length - a.length)[0] || JSON.stringify(item)
  }
  return String(item)
}

// Badge colour based on semantic value
function _badgeClass(v) {
  const s = String(v).toLowerCase()
  const POS = new Set(['positive','yes','pass','success','true','good','approved','high','strong'])
  const NEG = new Set(['negative','no','fail','failure','false','bad','rejected','low','weak'])
  if (POS.has(s)) return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
  if (NEG.has(s)) return 'bg-red-500/20 text-red-300 border-red-500/40'
  if (typeof v === 'number') return 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40'
  return 'bg-slate-700/60 text-slate-300 border-slate-600/40'
}

// Generic structured renderer — works for any JSON object regardless of field names
function StructuredJSON({ obj, depth = 0 }) {
  const [showRaw, setShowRaw] = useState(false)

  const badges = []  // short strings (≤ 60 chars), numbers, booleans
  const prose  = []  // long strings
  const lists  = []  // arrays
  const nested = []  // plain objects

  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined) continue
    if (typeof v === 'boolean' || typeof v === 'number') {
      badges.push([k, v])
    } else if (typeof v === 'string') {
      if (v.length <= 60) badges.push([k, v])
      else prose.push([k, v])
    } else if (Array.isArray(v) && v.length > 0) {
      lists.push([k, v])
    } else if (typeof v === 'object' && !Array.isArray(v)) {
      nested.push([k, v])
    }
  }

  const hasContent = badges.length || prose.length || lists.length || nested.length
  if (!hasContent) {
    return (
      <pre className="text-xs font-mono text-slate-300 bg-slate-950 p-3 rounded-xl overflow-x-auto leading-relaxed">
        {JSON.stringify(obj, null, 2)}
      </pre>
    )
  }

  return (
    <div className="space-y-3">

      {/* ── Badges / short values ── */}
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {badges.map(([k, v]) => (
            <span key={k}
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${_badgeClass(v)}`}>
              <span className="opacity-55 text-[10px] uppercase tracking-wide">{_toLabel(k)}</span>
              <span className="font-semibold">
                {typeof v === 'boolean' ? (v ? 'Yes' : 'No')
                 : typeof v === 'number' ? (v > 1 && v <= 100 ? `${v}%` : String(v))
                 : String(v)}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* ── Prose paragraphs ── */}
      {prose.map(([k, v]) => (
        <div key={k}>
          <div className="text-[11px] font-semibold text-am-indigo uppercase tracking-wider mb-1">
            {_toLabel(k)}
          </div>
          <div className="text-sm text-am-text leading-relaxed whitespace-pre-wrap">{v}</div>
        </div>
      ))}

      {/* ── Bullet lists ── */}
      {lists.map(([k, v]) => (
        <div key={k}>
          <div className="text-[11px] font-semibold text-am-indigo uppercase tracking-wider mb-1">
            {_toLabel(k)}
          </div>
          <ul className="space-y-1 pl-1">
            {v.map((item, i) => (
              <li key={i} className="flex gap-2 text-sm text-am-text leading-relaxed">
                <span className="text-am-indigo mt-0.5 shrink-0 select-none">•</span>
                <span>{_itemText(item)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {/* ── Nested objects (recursive) ── */}
      {nested.map(([k, v]) => (
        <div key={k} className="pl-3 border-l border-slate-700/60">
          <div className="text-[11px] font-semibold text-am-indigo uppercase tracking-wider mb-2">
            {_toLabel(k)}
          </div>
          <StructuredJSON obj={v} depth={depth + 1} />
        </div>
      ))}

      {/* ── Raw JSON toggle (top level only) ── */}
      {depth === 0 && (
        <div className="pt-1">
          <button onClick={() => setShowRaw(s => !s)}
            className="text-xs text-am-muted hover:text-am-text transition-colors">
            {showRaw ? 'Hide raw ↑' : '{} raw JSON'}
          </button>
          {showRaw && (
            <pre className="mt-2 text-xs font-mono text-slate-300 bg-slate-950 p-3 rounded-xl overflow-x-auto leading-relaxed">
              {JSON.stringify(obj, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function SmartOutput({ raw, maxChars = 700 }) {
  const [expanded, setExpanded] = useState(false)

  if (!raw) return null

  // Try to parse JSON
  let parsed = null
  try {
    const s = typeof raw === 'string' ? raw.trim() : null
    if (s && (s.startsWith('{') || s.startsWith('['))) parsed = JSON.parse(s)
  } catch { /* not JSON */ }

  // JSON object → generic structured renderer
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    return <StructuredJSON obj={parsed} />
  }

  // JSON array → pretty code block
  if (parsed && Array.isArray(parsed)) {
    return (
      <pre className="text-xs font-mono text-slate-300 bg-slate-950 p-3 rounded-xl overflow-x-auto leading-relaxed">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    )
  }

  // Plain text with truncation
  const text   = typeof raw === 'string' ? raw : String(raw)
  const isLong = text.length > maxChars
  return (
    <div>
      <div className="text-sm text-am-text leading-relaxed whitespace-pre-wrap">
        {expanded || !isLong ? text : text.slice(0, maxChars) + '…'}
      </div>
      {isLong && (
        <button onClick={() => setExpanded(v => !v)}
          className="mt-1.5 text-xs text-am-indigo hover:underline">
          {expanded ? 'Show less ↑' : 'Show more ↓'}
        </button>
      )}
    </div>
  )
}

// ── Star rating extracted as standalone component ─────────────────────────────
function StepRating({ agentId }) {
  const [stars,      setStars]      = useState(0)
  const [hover,      setHover]      = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [rated,      setRated]      = useState(false)
  const [rateErr,    setRateErr]    = useState('')

  async function submitRating() {
    if (!stars || submitting || rated) return
    setSubmitting(true); setRateErr('')
    try {
      if (!window.ethereum) throw new Error('MetaMask non détecté')
      const info = await agentApi.getFeedbackInfo(agentId, stars)
      if (!info.reputation_address || info.call_data === '0x')
        throw new Error('ReputationRegistry non configuré')
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      const chainHex = await window.ethereum.request({ method: 'eth_chainId' })
      if (parseInt(chainHex, 16) !== 84532) {
        try { await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14A34' }] }) }
        catch { throw new Error('Veuillez passer sur Base Sepolia dans MetaMask') }
      }
      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{ from: accounts[0], to: info.reputation_address, data: info.call_data, gas: info.gas ?? '0x30D40' }],
      })
      await agentApi.notifyFeedback(agentId, { tx_hash: txHash, stars }).catch(() => {})
      setRated(true)
    } catch (e) {
      setRateErr(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="border-t border-amber-100 pt-2.5 mt-3 flex items-center gap-2 flex-wrap">
      <span className="text-xs text-am-muted">Was this output useful?</span>
      {rated ? (
        <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium ml-auto">
          <CheckCircle size={11} /> Rated {stars}★
        </span>
      ) : (
        <div className="flex items-center gap-1 ml-auto">
          {[1,2,3,4,5].map(s => (
            <button key={s} onClick={() => setStars(s)}
              onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(0)}
              className="text-lg leading-none transition-transform hover:scale-110 select-none">
              <span style={{ color: s <= (hover || stars) ? '#f59e0b' : '#d1d5db' }}>★</span>
            </button>
          ))}
          <button onClick={submitRating} disabled={!stars || submitting}
            className="ml-2 text-xs px-3 py-1 rounded-lg bg-am-indigo text-white disabled:opacity-40 hover:bg-indigo-700 transition-colors flex items-center gap-1">
            {submitting ? <Loader2 size={10} className="animate-spin" /> : 'Submit'}
          </button>
        </div>
      )}
      {rateErr && <span className="text-xs text-rose-500 w-full">{rateErr}</span>}
    </div>
  )
}

// ── Final output body (content only, used inside AccordionRow) ────────────────
function FinalOutputBody({ output }) {
  const [copied, setCopied] = useState(false)
  const writerData = parseWriterOutput(output)
  function copy() {
    navigator.clipboard.writeText(output)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }
  return (
    <div className="space-y-3">
      {writerData ? <WriterOutputBlock output={writerData} /> : <SmartOutput raw={output} maxChars={1200} />}
      <div className="flex justify-end">
        <button onClick={copy} className="flex items-center gap-1 text-xs text-am-muted hover:text-am-text transition-colors">
          {copied ? <><Check size={11} className="text-emerald-500" /> Copied</> : <><Copy size={11} /> Copy</>}
        </button>
      </div>
    </div>
  )
}

// ── Final output card (kept for legacy use) ───────────────────────────────────

function FinalOutputCard({ output, valTaskId }) {
  const [copied, setCopied] = useState(false)

  const writerData = parseWriterOutput(output)

  function copyOutput() {
    navigator.clipboard.writeText(output)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-emerald-200 overflow-hidden shadow-sm"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-emerald-200"
        style={{ background: 'linear-gradient(90deg, #ecfdf5, #f0fdf4)' }}>
        <CheckCircle size={15} className="text-emerald-600 shrink-0" />
        <span className="font-semibold text-emerald-800 text-sm flex-1">Final Output</span>
        {valTaskId && (
          <span className="text-[10px] text-emerald-600/70 font-mono bg-emerald-100 px-2 py-0.5 rounded-full">
            val: {valTaskId.slice(0, 14)}…
          </span>
        )}
        <button onClick={copyOutput}
          className="flex items-center gap-1 text-xs text-emerald-700 hover:text-emerald-900 bg-emerald-100 hover:bg-emerald-200 px-2.5 py-1 rounded-lg transition-colors ml-1">
          {copied ? <><Check size={11} /> Copié</> : <><Copy size={11} /> Copier</>}
        </button>
      </div>

      {/* Content */}
      <div className="px-4 pt-3 pb-3 bg-white">
        {writerData
          ? <WriterOutputBlock output={writerData} />
          : <SmartOutput raw={output} maxChars={1200} />
        }
      </div>
    </motion.div>
  )
}

// ── Step result card — output + inline star rating ────────────────────────────

function StepResultCard({ step, isDone, index, subtask }) {
  const [copied,     setCopied]     = useState(false)
  const [stars,      setStars]      = useState(0)
  const [hover,      setHover]      = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [rated,      setRated]      = useState(false)
  const [rateErr,    setRateErr]    = useState('')

  const ok       = step.status === 'success'
  const fail     = isFailedStepStatus(step.status)
  const pending  = !ok && !fail
  const ds       = domainStyle(subtask?.domain)
  const agentLabel = step.agent_name || step.agent_id || '?'
  const hasOutput = ok && step.output && step.output.trim().length > 0

  function copyOutput() {
    navigator.clipboard.writeText(step.output || '')
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  async function submitRating() {
    if (!stars || submitting || rated) return
    setSubmitting(true); setRateErr('')
    try {
      if (!window.ethereum) throw new Error('MetaMask non détecté')

      // Encode giveFeedback(tag1="starred") via backend, signe via MetaMask
      const info = await agentApi.getFeedbackInfo(step.agent_id, stars)
      if (!info.reputation_address || info.call_data === '0x')
        throw new Error('ReputationRegistry non configuré')

      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      const chainHex = await window.ethereum.request({ method: 'eth_chainId' })
      if (parseInt(chainHex, 16) !== 84532) {
        try { await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14A34' }] }) }
        catch { throw new Error('Veuillez passer sur Base Sepolia dans MetaMask') }
      }
      const txHash = await window.ethereum.request({
        method: 'eth_sendTransaction',
        params: [{ from: accounts[0], to: info.reputation_address, data: info.call_data, gas: info.gas ?? '0x30D40' }],
      })

      // Notifie le backend pour déclencher le recalcul EigenTrust
      await agentApi.notifyFeedback(step.agent_id, { tx_hash: txHash, stars }).catch(() => {})

      setRated(true)
    } catch (e) {
      setRateErr(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="card p-4 flex flex-col gap-3"
    >
      {/* ── Header row ── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
          <span className="text-xs font-bold text-am-muted shrink-0">#{index + 1}</span>
          {subtask?.domain && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0"
              style={{ background: ds.bg, color: ds.color, borderColor: ds.border }}>
              {subtask.domain}
            </span>
          )}
          <span className="text-xs font-semibold text-am-text-2 truncate">{agentLabel}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {step.duration_sec != null && (
            <span className="flex items-center gap-1 text-xs text-am-muted font-mono">
              <Clock size={10} />{step.duration_sec.toFixed(1)}s
            </span>
          )}
          {ok      && <CheckCircle size={14} style={{ color: '#10b981' }} />}
          {fail    && <XCircle     size={14} style={{ color: '#ef4444' }} />}
          {pending && <Loader2     size={14} className="animate-spin text-am-indigo" />}
        </div>
      </div>

      {/* ── Subtask description ── */}
      {subtask?.description && (
        <p className="text-sm text-am-text leading-relaxed line-clamp-2">
          {subtask.description}
        </p>
      )}

      {/* ── Output ── */}
      {hasOutput && (
        <div className="border-t border-am-border pt-3 space-y-2">
          {parseWriterOutput(step.output)
            ? <WriterOutputBlock output={parseWriterOutput(step.output)} />
            : <SmartOutput raw={step.output} />
          }
          <div className="flex justify-end">
            <button onClick={copyOutput}
              className="flex items-center gap-1 text-xs text-am-muted hover:text-am-text transition-colors">
              {copied ? <><Check size={11} className="text-emerald-500" /> Copié</> : <><Copy size={11} /> Copier</>}
            </button>
          </div>
        </div>
      )}

      {/* ── Failed reason ── */}
      {fail && step.error && (
        <div className="border-t border-rose-100 pt-2 text-xs text-rose-500 flex items-start gap-1.5">
          <XCircle size={11} className="shrink-0 mt-0.5" />
          {step.error}
        </div>
      )}

      {/* ── Star rating (only when done + success) ── */}
      {isDone && ok && (
        <div className="border-t border-amber-100 pt-2.5 flex items-center gap-2 flex-wrap">
          <span className="text-xs text-am-muted">Cet output était-il utile ?</span>
          {rated ? (
            <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium ml-auto">
              <CheckCircle size={11} /> Noté {stars}★
            </span>
          ) : (
            <div className="flex items-center gap-1 ml-auto">
              {[1,2,3,4,5].map(s => (
                <button key={s} onClick={() => setStars(s)}
                  onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(0)}
                  className="text-lg leading-none transition-transform hover:scale-110 focus:outline-none select-none">
                  <span style={{ color: s <= (hover || stars) ? '#f59e0b' : '#d1d5db' }}>★</span>
                </button>
              ))}
              <button onClick={submitRating} disabled={!stars || submitting}
                className="ml-2 text-xs px-3 py-1 rounded-lg bg-am-indigo text-white disabled:opacity-40 hover:bg-indigo-700 transition-colors flex items-center gap-1">
                {submitting ? <Loader2 size={10} className="animate-spin" /> : 'Valider'}
              </button>
            </div>
          )}
          {rateErr && <span className="text-xs text-rose-500 w-full">{rateErr}</span>}
        </div>
      )}
    </motion.div>
  )
}

function PackDetailPanel({
  pack, onBack, onGetAccess, onStartExecution, onRunAgain,
  hasAccess, isGettingAccess,
  steps, finalOutput, valTaskId,
  subtasks, agents, apiKeys, setApiKeys, requiredKeys,
  isExecuting, isValidating, isDone, isFailed, taskReady,
  validationResults,
}) {
  const [tab, setTab] = useState('overview')

  // Lock private tabs when no access
  useEffect(() => {
    if (!hasAccess && tab !== 'overview') setTab('overview')
  }, [hasAccess, tab])

  // Auto-switch to live-test once access is granted
  useEffect(() => {
    if (hasAccess && tab === 'overview') setTab('live-test')
  }, [hasAccess]) // eslint-disable-line

  const canGoBack = !isExecuting && !isValidating

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">

      {/* Back button */}
      {canGoBack && (
        <button onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-am-muted hover:text-am-text transition-colors">
          <ArrowLeft size={14} /> Back to packs
        </button>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 p-1 rounded-xl bg-am-surface border border-am-border">
        {PACK_DETAIL_TABS.map(({ id, label, icon: Icon }) => {
          const isPrivate = id !== 'overview'
          const locked = isPrivate && !hasAccess
          return (
            <button
              key={id}
              onClick={() => !locked && setTab(id)}
              disabled={locked}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                tab === id
                  ? 'bg-white shadow-sm text-am-indigo border border-am-border'
                  : locked
                  ? 'text-am-muted/40 cursor-not-allowed'
                  : 'text-am-muted hover:text-am-text'
              }`}
            >
              {locked ? <Lock size={13} /> : <Icon size={14} />}
              <span className="hidden sm:inline">{label}</span>
            </button>
          )
        })}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {tab === 'overview' && (
            <PackOverviewTab
              pack={pack}
              agents={agents}
              subtasks={subtasks}
              apiKeys={apiKeys}
              setApiKeys={setApiKeys}
              requiredKeys={requiredKeys}
              onGetAccess={onGetAccess}
              isGettingAccess={isGettingAccess}
              hasAccess={hasAccess}
            />
          )}
          {tab === 'live-test' && hasAccess && (
            <PackLiveTestTab
              steps={steps}
              finalOutput={finalOutput}
              valTaskId={valTaskId}
              isExecuting={isExecuting}
              isValidating={isValidating}
              isDone={isDone}
              isFailed={isFailed}
              taskReady={taskReady}
              onStartExecution={onStartExecution}
              onRunAgain={onRunAgain}
              apiKeys={apiKeys}
              setApiKeys={setApiKeys}
              requiredKeys={requiredKeys}
              agents={agents.length > 0 ? agents : (pack?.agents || [])}
              subtasks={subtasks.length > 0 ? subtasks : (pack?.subtasks || [])}
              validationResults={validationResults}
            />
          )}
          {tab === 'integrate' && hasAccess && (
            <PackIntegrateTab pack={pack} agents={agents.length > 0 ? agents : pack.agents} />
          )}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function TaskOrchestrator() {
  const { walletAddress, connectWallet } = useAuth()

  const [prompt, setPrompt] = useState('')
  const [pageState, setPageState] = useState(PAGE_STATES.idle)
  const [error, setError] = useState('')

  // Pack selection
  const [packs, setPacks] = useState([])
  const [packPrompt, setPackPrompt] = useState('')
  const [packReasoning, setPackReasoning] = useState('')
  const [selectedPack, setSelectedPack] = useState(null)

  // Access flow (payment → hasPackAccess)
  const [hasPackAccess, setHasPackAccess] = useState(false)
  const [isGettingAccess, setIsGettingAccess] = useState(false)
  const [packPurchaseInfo, setPackPurchaseInfo] = useState(null)
  const [showPayModal, setShowPayModal] = useState(false)
  const [purchasing, setPurchasing] = useState(false)
  const [purchaseErr, setPurchaseErr] = useState('')

  // Plan data
  const [taskId, setTaskId] = useState(null)
  const [mode, setMode] = useState('solo')
  const [reasoning, setReasoning] = useState('')
  const [subtasks, setSubtasks] = useState([])
  const [agents, setAgents] = useState([])

  // Execution data
  const [steps, setSteps] = useState([])
  const [finalOutput, setFinalOutput] = useState('')
  const [valTaskId, setValTaskId] = useState(null)
  const [validationResults, setValidationResults] = useState({})

  // API keys
  const [apiKeys, setApiKeys] = useState({})

  // Active packs (paid, non-expired) loaded from backend on wallet connect
  const [activePacks, setActivePacks] = useState([])

  // Legacy agent selector
  const [selectorOpen, setSelectorOpen] = useState(false)
  const [selectorSubtask, setSelectorSubtask] = useState(null)

  const pollingRef = useRef(null)
  const textareaRef = useRef(null)

  // ── Agent helpers ──────────────────────────────────────────────────────────

  function agentForSubtask(subtask_id) {
    return agents.find(a => a.subtask_id === subtask_id) || null
  }

  function replaceAgent(subtask_id, newAgentData) {
    setAgents(prev => prev.map(a =>
      a.subtask_id === subtask_id ? { ...a, ...newAgentData, subtask_id } : a
    ))
  }

  // ── Polling ────────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollingRef.current) { clearTimeout(pollingRef.current); pollingRef.current = null }
  }, [])

  const startPolling = useCallback((tid) => {
    stopPolling()
    let consecutiveIdle = 0
    const tick = async () => {
      try {
        const data = await taskApi.getStatus(tid)
        setSteps(data.steps || [])
        setFinalOutput(data.final_output || '')
        setValTaskId(data.val_task_id || null)
        setValidationResults(data.validation_results || {})
        if (data.status === 'done') {
          setPageState(PAGE_STATES.done)
          stopPolling(); return
        } else if (data.status === 'validating') {
          setPageState(PAGE_STATES.validating)
          consecutiveIdle = 0
        } else if (data.status === 'failed') {
          setPageState(PAGE_STATES.failed)
          setError('Execution failed — check backend logs')
          stopPolling(); return
        } else if (data.status === 'running') {
          consecutiveIdle = 0
        } else {
          consecutiveIdle++
        }
      } catch { /* ignore transient */ }
      // Adaptive: 3s while running/validating, 8s after 5+ idle ticks
      const delay = consecutiveIdle >= 5 ? 8000 : 3000
      pollingRef.current = setTimeout(tick, delay)
    }
    pollingRef.current = setTimeout(tick, 1000)
  }, [stopPolling])

  useEffect(() => () => stopPolling(), [stopPolling])

  // ── Receipt helper (MetaMask) ──────────────────────────────────────────────

  async function waitForReceipt(txHash, maxRetries = 30) {
    for (let i = 0; i < maxRetries; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const receipt = await window.ethereum.request({ method: 'eth_getTransactionReceipt', params: [txHash] })
      if (receipt && receipt.status === '0x1') return receipt
      if (receipt && receipt.status === '0x0') throw new Error('Transaction reverted')
    }
    throw new Error('Transaction not confirmed after 60s')
  }

  function parseStoredList(value) {
    if (Array.isArray(value)) return value
    if (!value) return []
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  function buildPackFromTask(task, restoredSubtasks, restoredAgents) {
    const totalEth = restoredAgents.reduce((sum, agent) => sum + (agent.price_per_task || 0), 0)
    const qualityScore = restoredAgents.length
      ? restoredAgents.reduce((sum, agent) => sum + (agent.final_score || 0), 0) / restoredAgents.length
      : 0

    return {
      pack_id: task.pack_id || task.id || task.task_id,
      name: task.pack_name || task.pack_id || 'Active Pack',
      description: task.task_prompt || 'Previously unlocked agent pack',
      agents: restoredAgents,
      subtasks: restoredSubtasks,
      total_eth: totalEth,
      quality_score: qualityScore,
      estimated_duration_min: Math.max(1, restoredAgents.length) * 1.5,
      mode: task.mode || 'pipeline',
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function handlePlan() {
    if (!prompt.trim() || pageState === PAGE_STATES.planning) return
    setError('')
    setPageState(PAGE_STATES.planning)
    setPacks([])
    setSelectedPack(null)
    setHasPackAccess(false)
    setPackPurchaseInfo(null)
    setSubtasks([])
    setAgents([])
    setSteps([])
    setFinalOutput('')
    setValTaskId(null)
    setTaskId(null)

    try {
      const data = await taskApi.packProposals(prompt.trim(), walletAddress || '')
      setPacks(data.packs || [])
      setPackPrompt(prompt.trim())
      setPackReasoning(data.reasoning || '')
      setPageState(PAGE_STATES.pack_selecting)
    } catch (err) {
      setError(err.message)
      setPageState(PAGE_STATES.failed)
    }
  }

  // Load active (paid, non-expired) packs for this wallet — cached 30s in sessionStorage
  const loadActivePacks = useCallback(async (wallet, force = false) => {
    setActivePacks([])                          // clear immediately — never show stale wallet data
    if (!wallet) return
    const cacheKey = `activePacks_${wallet}`
    if (!force) {
      try {
        const cached = sessionStorage.getItem(cacheKey)
        if (cached) {
          const { ts, packs } = JSON.parse(cached)
          if (Date.now() - ts < 30_000) { setActivePacks(packs); return }
        }
      } catch { /* ignore */ }
    }
    try {
      const data = await taskApi.list(wallet, 50)
      const tasks = data.tasks || data || []
      const now = new Date()
      const active = tasks.filter(t => {
        if (!t.access_expires_at) return false
        try { return new Date(t.access_expires_at) > now } catch { return false }
      })
      setActivePacks(active)
      try { sessionStorage.setItem(cacheKey, JSON.stringify({ ts: Date.now(), packs: active })) } catch { /* ignore */ }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    loadActivePacks(walletAddress)
    if (!walletAddress) handleReset()          // disconnect → reset any open pack session
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walletAddress])

  // Navigate to pack detail view (no API call yet)
  // If the wallet already has access to this pack_id → restore session
  async function handlePackDetailSelect(pack) {
    setSelectedPack(pack)

    // Check if wallet already has access to a task with this pack_id
    if (walletAddress) {
      const existing = activePacks.find(t =>
        t.pack_id === pack.pack_id ||
        (t.pack_name && t.pack_name === pack.name)
      )
      if (existing) {
        await _restorePackSession(existing)
        return
      }
    }
    setPageState(PAGE_STATES.pack_detail)
  }

  // Restore a previously-paid pack session (user returning after payment)
  async function _restorePackSession(task) {
    try {
      const access = await taskApi.checkPackAccess(task.id, walletAddress)
      if (!access.has_access) { setPageState(PAGE_STATES.pack_detail); return }

      const restoredTask = { ...task, ...access }
      const restoredSubtasks = parseStoredList(restoredTask.plan_json)
      const restoredAgents = parseStoredList(restoredTask.selected_agents_json)
      const restoredPack = buildPackFromTask(restoredTask, restoredSubtasks, restoredAgents)

      setSelectedPack(restoredPack)
      setTaskId(restoredTask.id || restoredTask.task_id)
      setMode(restoredTask.mode || 'pipeline')
      setPackPrompt(restoredTask.task_prompt || '')
      setPackReasoning('')
      setSubtasks(restoredSubtasks)
      setAgents(restoredAgents)

      // Restore execution results if any
      setFinalOutput(restoredTask.final_output || '')
      setValTaskId(restoredTask.val_task_id || null)
      setSteps(parseStoredList(restoredTask.steps_json))
      setValidationResults(restoredTask.validation_results || {})

      setHasPackAccess(true)
      const restoredStatus = restoredTask.status
      setPageState(
        restoredStatus === 'done' ? PAGE_STATES.done
        : restoredStatus === 'executing' ? PAGE_STATES.executing
        : restoredStatus === 'validating' ? PAGE_STATES.validating
        : PAGE_STATES.pack_detail
      )
      if (restoredStatus === 'executing' || restoredStatus === 'validating')
        startPolling(restoredTask.id || restoredTask.task_id)
    } catch { setPageState(PAGE_STATES.pack_detail) }
  }

  // Step 1: "Get Access" — selectPack + show payment modal
  async function handleGetAccess() {
    if (!selectedPack) return
    let wallet = walletAddress
    if (!wallet && connectWallet) {
      wallet = await connectWallet()
      if (!wallet) return
    }
    setError('')
    setPurchaseErr('')
    setIsGettingAccess(true)
    try {
      const data = await taskApi.selectPack({
        packId: selectedPack.pack_id,
        prompt: packPrompt,
        mode: selectedPack.mode,
        reasoning: packReasoning,
        subtasks: selectedPack.subtasks,
        agents: selectedPack.agents,
        buyerWallet: wallet || '',
        packName: selectedPack.name || '',
      })
      setTaskId(data.task_id)
      setMode(selectedPack.mode)
      setReasoning(packReasoning)
      setSubtasks(selectedPack.subtasks)
      setAgents(selectedPack.agents)
      setPackPurchaseInfo(data.purchase_info || null)
      setShowPayModal(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsGettingAccess(false)
    }
  }

  // Step 2: Confirm payment in modal
  async function confirmPackPurchase() {
    const info = packPurchaseInfo
    const isFree = !info?.total_eth || info.total_eth === 0
    setPurchasing(true)
    setPurchaseErr('')
    try {
      let txHash = ''
      if (!isFree && info?.contract_address && window.ethereum) {
        const priceWei = BigInt(info.total_eth_wei || '0')
        let gasPrice = '0x1'
        try {
          gasPrice = await window.ethereum.request({ method: 'eth_gasPrice' })
        } catch { /* fallback */ }

        if (!info.call_data) throw new Error('call_data manquant — rechargez la page')

        txHash = await window.ethereum.request({
          method: 'eth_sendTransaction',
          params: [{
            from: walletAddress,
            to: info.contract_address,
            value: '0x' + priceWei.toString(16),
            data: info.call_data,
            gas: '0x493E0',   // 300 000 — pipeline contract uses more gas
            gasPrice,
          }],
        })
        await waitForReceipt(txHash)
      }
      // Record access in DB (30-day grant) — works for both free and paid
      if (taskId) {
        await taskApi.confirmPackAccess(taskId, { buyer_wallet: walletAddress || '', tx_hash: txHash })
        await loadActivePacks(walletAddress)
      }
      setHasPackAccess(true)
      setShowPayModal(false)
    } catch (err) {
      if (err.code !== 4001) setPurchaseErr(err.message || 'Transaction failed')
    } finally {
      setPurchasing(false)
    }
  }

  // Step 3: "Start Pipeline" in Live Test tab
  async function handleStartExecution() {
    if (!taskId || !selectedPack || pageState === PAGE_STATES.executing) return
    setError('')
    setPageState(PAGE_STATES.executing)
    setSteps([])
    setFinalOutput('')
    try {
      await taskApi.execute(taskId, {
        prompt: packPrompt,
        mode: selectedPack.mode,
        subtasks: selectedPack.subtasks,
        agents: selectedPack.agents,
        buyer_wallet: walletAddress || '',
        agent_params: apiKeys,
      })
      startPolling(taskId)
    } catch (err) {
      setError(err.message)
      setPageState(PAGE_STATES.pack_detail)
    }
  }

  // Legacy pack select → plan_ready (kept for backwards compat)
  async function handlePackSelect(pack) {
    setError('')
    setPageState(PAGE_STATES.planning)
    try {
      const data = await taskApi.selectPack({
        packId: pack.pack_id,
        prompt: packPrompt,
        mode: pack.mode,
        reasoning: packReasoning,
        subtasks: pack.subtasks,
        agents: pack.agents,
        buyerWallet: walletAddress || '',
      })
      setTaskId(data.task_id)
      setMode(pack.mode)
      setReasoning(packReasoning)
      setSubtasks(pack.subtasks)
      setAgents(pack.agents)
      setPageState(PAGE_STATES.plan_ready)
    } catch (err) {
      setError(err.message)
      setPageState(PAGE_STATES.pack_selecting)
    }
  }

  async function handleExecute() {
    if (!taskId || pageState === PAGE_STATES.executing) return
    setError('')
    setPageState(PAGE_STATES.executing)
    setSteps([])
    setFinalOutput('')
    try {
      await taskApi.execute(taskId, {
        prompt: packPrompt, mode, subtasks, agents,
        buyer_wallet: walletAddress || '', agent_params: apiKeys,
      })
      startPolling(taskId)
    } catch (err) {
      setError(err.message)
      setPageState(PAGE_STATES.failed)
    }
  }

  function handleRunAgain() {
    stopPolling()
    setSteps([])
    setFinalOutput('')
    setValTaskId(null)
    setValidationResults({})
    setPageState(PAGE_STATES.pack_detail)
  }

  function handleReset() {
    stopPolling()
    setPageState(PAGE_STATES.idle)
    setPrompt('')
    setTaskId(null)
    setMode('solo')
    setReasoning('')
    setPacks([])
    setPackPrompt('')
    setPackReasoning('')
    setSelectedPack(null)
    setHasPackAccess(false)
    setPackPurchaseInfo(null)
    setShowPayModal(false)
    setPurchaseErr('')
    setSubtasks([])
    setAgents([])
    setSteps([])
    setFinalOutput('')
    setValTaskId(null)
    setError('')
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handlePlan()
  }

  function stepStatusFor(subtask_id) {
    if (pageState === PAGE_STATES.plan_ready) return 'pending'
    const step = steps.find(s => s.subtask_id === subtask_id)
    if (!step) return pageState === PAGE_STATES.executing ? 'running' : 'pending'
    return step.status === 'success' ? 'done' : isFailedStepStatus(step.status) ? 'failed' : 'running'
  }

  // ── Derived state ──────────────────────────────────────────────────────────

  const isPlanning = pageState === PAGE_STATES.planning
  const isPackSelecting = pageState === PAGE_STATES.pack_selecting
  const isPackDetail = pageState === PAGE_STATES.pack_detail
  const isPlanReady = pageState === PAGE_STATES.plan_ready
  const isExecuting = pageState === PAGE_STATES.executing
  const isValidating = pageState === PAGE_STATES.validating
  const isDone = pageState === PAGE_STATES.done
  const isFailed = pageState === PAGE_STATES.failed
  const hasPlan = subtasks.length > 0

  const showPackDetail = selectedPack && (
    isPackDetail || isExecuting || isValidating || isDone || (isFailed && selectedPack) ||
    (isPlanning && selectedPack)
  )

  const activeAgents = agents.length > 0 ? agents : (selectedPack?.agents || [])
  const requiredKeys = [...new Set(
    activeAgents.flatMap(a => (a.env_var_keys || []).filter(isBuyerProvidedEnvKey))
  )]
  const totalEth = agents.reduce((s, a) => s + (a.price_per_task || 0), 0)
  const excludedIds = agents.map(a => a.agent_id)

  // taskReady: task_id exists and access is granted but execution hasn't started yet
  const taskReady = hasPackAccess && !!taskId && !isExecuting && !isValidating && !isDone && !isFailed

  return (
    <div className="min-h-screen bg-am-bg py-10 px-4 sm:px-6">
      <div className="max-w-4xl mx-auto">

        {/* ── Header + Prompt Box — hidden once a pack session is active ── */}
        {!showPackDetail && (
          <>
            <div className="text-center mb-10">
              <motion.div
                initial={{ opacity: 0, y: -16 }}
                animate={{ opacity: 1, y: 0 }}
                className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-am-indigo/10 border border-am-indigo/20 text-am-indigo text-sm font-medium mb-4"
              >
                <Sparkles size={14} />
                <span>AI Orchestration Studio</span>
              </motion.div>
              <h1 className="text-3xl sm:text-4xl font-extrabold text-am-text mb-3">
                Build your{' '}
                <span className="text-gradient-indigo">Agentic Workflow</span>
              </h1>
              <p className="text-am-muted max-w-2xl mx-auto text-sm sm:text-base">
                Describe your task. Our protocol decomposes it into a{' '}
                <strong>SubTask DAG</strong>, matches the best agents using{' '}
                <strong>BAAI/bge-m3 + EigenTrust</strong>, and executes it on-chain.
              </p>
            </div>

            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="card p-3 shadow-card-lg border-am-indigo/20 mb-8"
            >
              <textarea
                ref={textareaRef}
                rows={3}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isPlanning || isExecuting}
                placeholder="Ex: Research the top 5 AI startups of 2025, summarize their products, and write a detailed investment report…"
                className="w-full bg-transparent text-sm text-am-text placeholder-am-muted resize-none outline-none px-2 py-1 leading-relaxed"
              />
              <div className="flex items-center justify-between mt-2 pt-2 border-t border-am-border">
                <span className="text-xs text-am-muted">Ctrl+Enter to plan</span>
                <div className="flex items-center gap-2">
                  {(isPackDetail || isPlanReady) && packs.length > 0 && (
                    <button
                      onClick={() => { setSelectedPack(null); setHasPackAccess(false); setPageState(PAGE_STATES.pack_selecting) }}
                      className="btn-ghost text-xs flex items-center gap-1 text-am-indigo"
                    >
                      <Package size={12} /> View other packs
                    </button>
                  )}
                  {(hasPlan || isPackSelecting || isPackDetail || isFailed) && (
                    <button onClick={handleReset} className="btn-ghost text-xs flex items-center gap-1">
                      <RotateCcw size={12} /> Reset
                    </button>
                  )}
                  <button
                    onClick={handlePlan}
                    disabled={!prompt.trim() || isPlanning || isExecuting}
                    className="btn-primary text-sm flex items-center gap-2 disabled:opacity-50"
                  >
                    {isPlanning && !selectedPack
                      ? <><Loader2 size={14} className="animate-spin" /> Building packs…</>
                      : <><Send size={14} /> Plan Task</>
                    }
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        )}

        {/* ── Payment Modal ── */}
        <AnimatePresence>
          {showPayModal && selectedPack && (
            <PackPayModal
              pack={selectedPack}
              purchaseInfo={packPurchaseInfo}
              walletAddress={walletAddress}
              purchasing={purchasing}
              error={purchaseErr}
              onConfirm={confirmPackPurchase}
              onClose={() => { setShowPayModal(false); setPurchaseErr('') }}
            />
          )}
        </AnimatePresence>

        {/* ── Error banner ── */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-start gap-3 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 mb-6 text-sm text-rose-700"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Pack Selection ── */}
        <AnimatePresence>
          {isPackSelecting && !selectedPack && packs.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="space-y-4"
            >
              <div className="flex items-center gap-3 mb-1">
                <Package size={16} className="text-am-indigo" />
                <span className="font-semibold text-am-text text-sm">Choose your agent pack</span>
                {packReasoning && (
                  <span className="text-xs text-am-muted italic flex-1 truncate">— {packReasoning}</span>
                )}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {packs.map((pack, i) => (
                  <motion.div key={pack.pack_id} transition={{ delay: i * 0.08 }}>
                    <PackCard pack={pack} index={i} onSelect={handlePackDetailSelect} />
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Pack Detail Panel ── */}
        <AnimatePresence>
          {showPackDetail && selectedPack && (
            <PackDetailPanel
              pack={selectedPack}
              onBack={() => { setSelectedPack(null); setHasPackAccess(false); setPageState(PAGE_STATES.pack_selecting) }}
              onGetAccess={handleGetAccess}
              onStartExecution={handleStartExecution}
              hasAccess={hasPackAccess}
              isGettingAccess={isGettingAccess}
              steps={steps}
              finalOutput={finalOutput}
              valTaskId={valTaskId}
              subtasks={subtasks}
              agents={agents}
              apiKeys={apiKeys}
              setApiKeys={setApiKeys}
              requiredKeys={requiredKeys}
              isExecuting={isExecuting}
              isValidating={isValidating}
              isDone={isDone}
              isFailed={isFailed}
              taskReady={taskReady}
              validationResults={validationResults}
              onRunAgain={handleRunAgain}
            />
          )}
        </AnimatePresence>

        {/* ── Legacy Plan Result (plan_ready, no selectedPack) ── */}
        <AnimatePresence>
          {hasPlan && !showPackDetail && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">

              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <ModeBadge mode={mode} />
                  <span className="text-sm text-am-text-2">{subtasks.length} subtask{subtasks.length > 1 ? 's' : ''}</span>
                  <TotalPrice agents={agents} />
                </div>
                <div className="flex items-center gap-2">
                  {isPlanReady && <button onClick={handleExecute} className="btn-primary text-sm flex items-center gap-2"><Play size={14} /> Execute</button>}
                  {isExecuting && <div className="flex items-center gap-2 text-sm text-amber-600 font-medium"><Loader2 size={14} className="animate-spin" /> Executing…</div>}
                  {isDone && <div className="flex items-center gap-2 text-sm text-am-emerald font-medium"><CheckCircle size={14} /> Done</div>}
                  {isFailed && <div className="flex items-center gap-2 text-sm text-am-rose font-medium"><XCircle size={14} /> Failed</div>}
                </div>
              </div>

              {reasoning && (
                <div className="text-sm text-am-muted bg-am-surface rounded-xl px-4 py-2.5 border border-am-border italic">{reasoning}</div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {subtasks.map((st, i) => (
                  <SubTaskCard
                    key={st.id} subtask={st} agent={agentForSubtask(st.id)}
                    index={i} stepStatus={stepStatusFor(st.id)}
                    onChangeAgent={isPlanReady ? () => { setSelectorSubtask(st); setSelectorOpen(true) } : null}
                  />
                ))}
              </div>

              {isPlanReady && mode === 'pipeline' && totalEth > 0 && (
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className="card p-4 border-am-indigo/30 bg-indigo-50/40">
                  <div className="flex items-center justify-between flex-wrap gap-3">
                    <div>
                      <div className="text-sm font-semibold text-am-text mb-1">Pipeline Escrow</div>
                      <div className="text-xs text-am-muted">Total: <strong>{totalEth.toFixed(4)} ETH</strong> to {agents.length} agents</div>
                    </div>
                    <button onClick={handleExecute} className="btn-primary text-sm flex items-center gap-2"><Zap size={14} /> Execute Now</button>
                  </div>
                </motion.div>
              )}

              <AnimatePresence>
                {(isDone || isExecuting) && finalOutput && (
                  <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="card p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <CheckCircle size={15} className="text-am-emerald" />
                      <span className="font-semibold text-am-text text-sm">Final Output</span>
                      {valTaskId && <span className="ml-auto text-xs text-am-muted font-mono">val: {valTaskId.slice(0, 12)}…</span>}
                    </div>
                    <pre className="text-xs text-am-text-2 bg-am-surface rounded-xl p-4 overflow-auto max-h-80 whitespace-pre-wrap font-mono leading-relaxed">{finalOutput}</pre>
                  </motion.div>
                )}
              </AnimatePresence>

              {steps.length > 0 && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-am-muted uppercase tracking-wide mb-2">Execution Steps</div>
                  {steps.map((step, i) => {
                    const ok = step.status === 'success'; const fail = isFailedStepStatus(step.status)
                    return (
                      <motion.div key={step.subtask_id || i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                        className="flex items-center gap-3 p-3 rounded-xl border border-am-border bg-white text-sm">
                        {ok ? <CheckCircle size={14} className="text-am-emerald shrink-0" /> : fail ? <XCircle size={14} className="text-am-rose shrink-0" /> : <Loader2 size={14} className="animate-spin text-am-indigo shrink-0" />}
                        <span className="font-mono text-xs text-am-muted w-12 shrink-0">{step.subtask_id}</span>
                        <span className="text-am-text-2 flex-1 truncate">{step.agent_id}</span>
                        {step.duration_sec != null && <span className="flex items-center gap-1 text-xs text-am-muted shrink-0"><Clock size={11} />{step.duration_sec.toFixed(1)}s</span>}
                      </motion.div>
                    )
                  })}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Active Packs (paid, non-expired) ── */}
        {pageState === PAGE_STATES.idle && activePacks.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle size={15} className="text-am-emerald" />
              <span className="font-semibold text-am-text text-sm">Your Active Packs</span>
              <span className="text-xs text-am-muted">— access still valid</span>
            </div>
            <div className="space-y-2">
              {activePacks.map(task => {
                const expires = new Date(task.access_expires_at)
                const daysLeft = Math.ceil((expires - new Date()) / 86_400_000)
                return (
                  <motion.button
                    key={task.id}
                    whileHover={{ x: 2 }}
                    onClick={() => _restorePackSession(task)}
                    className="w-full text-left flex items-center gap-3 p-3 rounded-xl border border-am-border bg-white hover:border-am-indigo/40 hover:shadow-sm transition-all text-sm"
                  >
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-indigo-50 text-am-indigo shrink-0">
                      <Package size={14} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-am-text truncate">{task.pack_name || task.id.slice(0, 16)}</div>
                      <div className="text-xs text-am-muted truncate">{task.task_prompt?.slice(0, 60)}…</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className={`text-xs font-medium ${task.status === 'done' ? 'text-am-emerald' : 'text-amber-500'}`}>
                        {task.status === 'done' ? 'Completed' : task.status}
                      </div>
                      <div className="text-xs text-am-muted">{daysLeft}d left</div>
                    </div>
                  </motion.button>
                )
              })}
            </div>
          </motion.div>
        )}

        {/* ── Idle placeholder ── */}
        {pageState === PAGE_STATES.idle && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }} className="text-center py-16">
            <div className="flex justify-center gap-4 mb-6">
              {[
                { icon: GitBranch, label: 'DAG Planning', color: '#6366f1' },
                { icon: Zap, label: 'EigenTrust', color: '#8b5cf6' },
                { icon: Play, label: 'On-Chain Exec', color: '#10b981' },
              ].map(({ icon: Icon, label, color }, i) => (
                <motion.div key={label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 + i * 0.1 }} className="flex flex-col items-center gap-2">
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center" style={{ background: `${color}18`, border: `1px solid ${color}30` }}>
                    <Icon size={20} style={{ color }} />
                  </div>
                  <span className="text-xs text-am-muted font-medium">{label}</span>
                </motion.div>
              ))}
            </div>
            <p className="text-sm text-am-muted">Enter a complex task above to generate your agentic workflow</p>
          </motion.div>
        )}

      </div>

      {/* ── Agent Selector Modal (legacy) ── */}
      {selectorOpen && selectorSubtask && (
        <AgentSelector
          subtask={selectorSubtask}
          currentAgentId={agentForSubtask(selectorSubtask.id)?.agent_id}
          excludedAgentIds={excludedIds.filter(id => id !== agentForSubtask(selectorSubtask.id)?.agent_id)}
          onSelect={newAgent => replaceAgent(selectorSubtask.id, newAgent)}
          onClose={() => { setSelectorOpen(false); setSelectorSubtask(null) }}
        />
      )}
    </div>
  )
}
