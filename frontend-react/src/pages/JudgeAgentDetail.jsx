import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Activity, BookOpen, History, Shield, TrendingUp,
  CheckCircle, XCircle, ChevronDown, ChevronUp, Clock,
  Package, Zap, Target, Users, Star, AlertCircle, Loader2,
} from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ReputationRing from '../components/common/ReputationRing'
import { agentApi, normalizeAgent } from '../api/agentApi'

const ACCENT = '#7c3aed'

const TABS = [
  { id: 'overview', label: 'Overview',           icon: Activity },
  { id: 'history',  label: 'Validation History', icon: History  },
  { id: 'readme',   label: 'README',             icon: BookOpen },
]

function hasValue(v) { return v !== null && v !== undefined && v !== '' && v !== 0 || v === 0 }
function fmt(v, suffix = '') {
  if (v === null || v === undefined || v === '') return '--'
  return `${v}${suffix}`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, icon: Icon, color }) {
  return (
    <div className="card p-4 shadow-card-md flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-am-muted">{label}</span>
        <div className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: `${color}15`, border: `1.5px solid ${color}25` }}>
          <Icon size={13} style={{ color }} />
        </div>
      </div>
      <div className="text-xl font-bold text-am-text">{value}</div>
      {sub && <div className="text-xs text-am-muted">{sub}</div>}
    </div>
  )
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="card shadow-card-md p-5">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-am-text">{title}</h3>
        {subtitle && <p className="text-xs text-am-muted mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

function CapGroup({ title, values, cls }) {
  if (!values?.length) return null
  return (
    <div>
      <div className="text-xs font-medium text-am-muted mb-1.5">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {values.map(v => (
          <span key={v} className={`${cls} text-xs px-2 py-0.5 rounded-full border`}>{v}</span>
        ))}
      </div>
    </div>
  )
}

function VerdictBadge({ verdict }) {
  const ok = verdict === 'VALID'
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border ${
      ok ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
         : 'bg-rose-50 text-rose-700 border-rose-200'
    }`}>
      {ok ? <CheckCircle size={10} /> : <XCircle size={10} />}
      {verdict}
    </span>
  )
}

function ScoreBar({ score }) {
  const color = score >= 65 ? '#10b981' : score >= 40 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="text-xs font-mono font-semibold" style={{ color }}>{score}</span>
    </div>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────

function OverviewTab({ agent, stats }) {
  const hasMonthly = stats?.monthly_data?.some(d => d.validations > 0)
  const hasWeekly  = stats?.weekly_data?.some(d => (d.valid + d.invalid) > 0)

  const capItems = [
    { title: 'Evaluation Skills',    values: agent.evaluation_skills,    cls: 'bg-violet-50 text-violet-700 border-violet-200' },
    { title: 'Validated Task Types', values: agent.validated_task_types, cls: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    { title: 'Evaluation Domains',   values: agent.evaluation_domains,   cls: 'bg-sky-50 text-sky-700 border-sky-200'          },
    { title: 'Tools Used',           values: agent.tools_used,           cls: 'bg-amber-50 text-amber-700 border-amber-200'    },
  ]
  const hasAnyCap = capItems.some(c => c.values?.length > 0) || agent.evaluation_style

  return (
    <div className="space-y-5">
      {/* Charts */}
      <div className="grid lg:grid-cols-2 gap-5">
        <ChartCard
          title="Monthly Validation Volume"
          subtitle={hasMonthly ? 'Validations per month' : 'Will fill as validations happen'}
        >
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={stats?.monthly_data || []}>
              <defs>
                <linearGradient id="jGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ACCENT} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={ACCENT} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} width={30} />
              <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="validations" name="Validations" stroke={ACCENT} fill="url(#jGrad)" strokeWidth={2} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Weekly Verdicts"
          subtitle={hasWeekly ? 'VALID vs INVALID — last 7 days' : 'Will fill over time'}
        >
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={stats?.weekly_data || []}>
              <XAxis dataKey="day" tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} width={30} />
              <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }} />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="valid"   name="VALID"   fill="#10b981" opacity={0.85} radius={[3,3,0,0]} stackId="a" />
              <Bar dataKey="invalid" name="INVALID" fill="#ef4444" opacity={0.75} radius={[3,3,0,0]} stackId="a" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="grid sm:grid-cols-2 gap-5">
        {/* Capabilities */}
        <div className="card shadow-card-md p-5">
          <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
            <Target size={14} style={{ color: ACCENT }} /> Evaluation Capabilities
          </h3>
          {hasAnyCap ? (
            <div className="space-y-4">
              {capItems.map(c => <CapGroup key={c.title} {...c} />)}
              {agent.evaluation_style && (
                <div>
                  <div className="text-xs font-medium text-am-muted mb-1.5">Evaluation Style</div>
                  <span className="text-xs text-am-text bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg">
                    {agent.evaluation_style}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-am-muted italic">No capability fields defined for this judge.</p>
          )}
        </div>

        {/* Accuracy */}
        <div className="card shadow-card-md p-5">
          <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
            <Shield size={14} style={{ color: ACCENT }} /> Accuracy & Reliability
          </h3>
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-am-muted">Agreement Rate</span>
                <span className="text-sm font-bold" style={{ color: ACCENT }}>
                  {stats ? `${stats.agreement_rate}%` : '--'}
                </span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                <div className="h-full rounded-full transition-all"
                  style={{ width: `${stats?.agreement_rate ?? 50}%`, background: ACCENT }} />
              </div>
              <p className="text-xs text-am-muted mt-1">Agreement with peer-judge consensus</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Total Validations', value: stats != null ? String(stats.total_validations) : '--', color: ACCENT    },
                { label: 'Agreements',         value: stats != null ? String(stats.agreement_count)   : '--', color: '#10b981' },
                { label: 'Avg Score Given',    value: stats != null ? `${stats.avg_score}/100`        : '--', color: '#6366f1' },
                { label: 'VALID Rate',         value: stats != null ? `${stats.valid_rate}%`          : '--', color: '#8b5cf6' },
              ].map(({ label, value, color }) => (
                <div key={label} className="rounded-xl p-3 text-center border"
                  style={{ background: `${color}08`, borderColor: `${color}20` }}>
                  <div className="text-base font-bold text-am-text">{value}</div>
                  <div className="text-xs text-am-muted mt-0.5">{label}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-1 border-t border-am-border">
              <div className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-xs text-am-muted">
                Accuracy signal emitted on-chain via ReputationRegistry
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Technical config */}
      <div className="card shadow-card-md p-5">
        <h3 className="text-sm font-semibold text-am-text mb-4 flex items-center gap-2">
          <Package size={14} style={{ color: ACCENT }} /> Agent Config
        </h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { label: 'Docker Image', value: agent.docker_image },
            { label: 'LLM Model',    value: agent.llm_model    },
            { label: 'Framework',    value: agent.framework    },
            { label: 'Language',     value: agent.language     },
            { label: 'Stake',        value: agent.stake_amount ? `${agent.stake_amount} ETH` : null },
            { label: 'Last Active',  value: agent.metrics?.last_active },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between text-sm py-1 border-b border-am-border/50 last:border-0">
              <span className="text-am-muted text-xs">{label}</span>
              <span className="text-am-text font-mono text-xs truncate max-w-[180px]">
                {value || '--'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── History Tab ───────────────────────────────────────────────────────────────

function HistoryTab({ history, total }) {
  const [expanded, setExpanded] = useState(null)

  if (!history.length) {
    return (
      <div className="card p-12 text-center">
        <History size={36} className="mx-auto mb-3 text-am-muted opacity-30" />
        <p className="text-am-muted text-sm font-medium">No validations recorded yet</p>
        <p className="text-xs text-am-muted mt-1">
          History appears here as the judge evaluates provider agents.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Column headers */}
      <div className="hidden sm:grid grid-cols-[1fr_100px_90px_90px_28px] gap-3 px-4 py-2 text-xs font-medium text-am-muted">
        <span>Provider Agent</span>
        <span>Verdict</span>
        <span>Score</span>
        <span>Date</span>
        <span />
      </div>

      {history.map((v, i) => {
        const isOpen    = expanded === i
        const date      = v.created_at ? new Date(v.created_at).toLocaleDateString() : '--'
        const agentShort = v.agent_id?.length > 22
          ? `${v.agent_id.slice(0, 12)}…${v.agent_id.slice(-6)}`
          : v.agent_id

        return (
          <div key={i} className="card overflow-hidden">
            <button
              className="w-full grid grid-cols-[1fr_100px_90px_90px_28px] gap-3 px-4 py-3.5
                         hover:bg-am-surface/60 transition-colors text-left items-center"
              onClick={() => setExpanded(isOpen ? null : i)}
            >
              <span className="font-mono text-xs text-am-text truncate">{agentShort}</span>
              <VerdictBadge verdict={v.verdict} />
              <ScoreBar score={v.score} />
              <span className="text-xs text-am-muted">{date}</span>
              <span className="text-am-muted flex-shrink-0">
                {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </span>
            </button>

            <AnimatePresence>
              {isOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.16 }}
                  className="overflow-hidden"
                >
                  <div className="px-4 pb-4 border-t border-am-border bg-slate-50/50">
                    <p className="text-xs font-semibold text-am-muted mt-3 mb-1.5 uppercase tracking-wide">
                      Justification
                    </p>
                    <p className="text-sm text-am-text leading-relaxed">{v.justification}</p>
                    <p className="text-xs text-am-muted mt-3 font-mono opacity-60">
                      Provider agent ID: {v.agent_id}
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}

      {total > history.length && (
        <p className="text-xs text-am-muted text-center py-3">
          Showing {history.length} of {total} total validations
        </p>
      )}
    </div>
  )
}

// ── Readme Tab ────────────────────────────────────────────────────────────────

function ReadmeTab({ readme, agent }) {
  if (!readme) {
    return (
      <div className="card p-12 text-center">
        <BookOpen size={36} className="mx-auto mb-3 text-am-muted opacity-30" />
        <p className="text-am-muted text-sm font-medium">No README for this judge</p>
      </div>
    )
  }
  return (
    <div className="card shadow-card-md p-6">
      <div className="flex items-center gap-2 mb-4 pb-3 border-b border-am-border">
        <BookOpen size={14} style={{ color: ACCENT }} />
        <span className="font-semibold text-am-text">{agent.name}</span>
        <span className="text-xs text-am-muted">v{agent.version}</span>
      </div>
      <div className="prose prose-sm max-w-none text-am-text">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{readme}</ReactMarkdown>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function JudgeAgentDetail() {
  const { agentId }  = useParams()
  const navigate     = useNavigate()
  const [activeTab,  setActiveTab]  = useState('overview')
  const [agent,      setAgent]      = useState(null)
  const [stats,      setStats]      = useState(null)
  const [history,    setHistory]    = useState([])
  const [histTotal,  setHistTotal]  = useState(0)
  const [readme,     setReadme]     = useState('')
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [raw, s, h, r] = await Promise.all([
        agentApi.get(agentId),
        agentApi.judgeStats(agentId).catch(() => null),
        agentApi.judgeHistory(agentId, 100, 0).catch(() => ({ verdicts: [], total: 0 })),
        agentApi.readme(agentId).catch(() => ({ readme: '' })),
      ])
      setAgent(normalizeAgent(raw))
      setStats(s)
      setHistory(h?.verdicts || [])
      setHistTotal(h?.total || 0)
      setReadme(r?.readme || '')
    } catch (e) {
      setError(e.message || 'Failed to load judge data')
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="min-h-screen bg-am-bg flex items-center justify-center">
        <Loader2 size={28} className="animate-spin text-am-indigo" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="min-h-screen bg-am-bg flex flex-col items-center justify-center gap-4">
        <AlertCircle size={32} className="text-rose-500" />
        <p className="text-am-muted text-sm">{error || 'Agent not found'}</p>
        <button onClick={() => navigate('/seller')} className="btn-primary text-sm">
          Back to My Agents
        </button>
      </div>
    )
  }

  const m        = agent.metrics || {}
  const repScore = stats ? stats.agreement_rate : (m.reputation_score ?? 50)

  const statCards = [
    { label: 'Total Validations', value: stats != null ? String(stats.total_validations) : '--', sub: 'All-time',             icon: Users,       color: ACCENT    },
    { label: 'Agreement Rate',    value: stats != null ? `${stats.agreement_rate}%`       : '--', sub: 'With peer consensus',  icon: TrendingUp,  color: '#10b981' },
    { label: 'Avg Score Given',   value: stats != null ? `${stats.avg_score}/100`         : '--', sub: 'Across all verdicts',  icon: Star,        color: '#6366f1' },
    { label: 'VALID Rate',        value: stats != null ? `${stats.valid_rate}%`           : '--', sub: 'Verdicts issued',      icon: CheckCircle, color: '#8b5cf6' },
    { label: 'This Month',        value: stats != null ? String(stats.this_month)         : '--', sub: 'Validations',          icon: Zap,         color: '#f59e0b' },
    { label: 'Agreements',        value: stats != null ? String(stats.agreement_count)    : '--', sub: 'Matched consensus',    icon: Shield,      color: '#0ea5e9' },
  ]

  return (
    <div className="min-h-screen bg-am-bg">
      {/* ── Header ── */}
      <div className="bg-white border-b border-am-border">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
          <button onClick={() => navigate('/seller')}
            className="flex items-center gap-1.5 text-sm text-am-muted hover:text-am-text mb-5 transition-colors">
            <ArrowLeft size={14} /> Back to My Agents
          </button>

          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-4">
              {/* Avatar */}
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center font-bold text-2xl text-white flex-shrink-0"
                style={{ background: `linear-gradient(135deg, ${ACCENT}, #8b5cf6)` }}>
                {agent.name?.charAt(0) || 'J'}
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h1 className="text-xl font-bold text-am-text">{agent.name}</h1>
                  <span className="text-xs px-2.5 py-0.5 rounded-full font-semibold border"
                    style={{ background: `${ACCENT}10`, color: ACCENT, borderColor: `${ACCENT}25` }}>
                    Judge
                  </span>
                  <span className="text-xs text-am-muted font-mono">v{agent.version}</span>
                  <span className="badge-emerald text-xs">{agent.status || 'active'}</span>
                </div>
                <p className="text-sm text-am-muted mt-1 max-w-2xl">{agent.description}</p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {agent.categories?.map(c => (
                    <span key={c} className="badge badge-slate text-xs">{c}</span>
                  ))}
                  {agent.evaluation_domains?.map(d => (
                    <span key={d} className="text-xs px-2 py-0.5 rounded-full border"
                      style={{ background: `${ACCENT}08`, color: ACCENT, borderColor: `${ACCENT}20` }}>
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="text-right hidden sm:block">
                <div className="text-xs text-am-muted">Agreement Rate</div>
                <div className="text-lg font-bold" style={{ color: ACCENT }}>
                  {stats ? `${stats.agreement_rate}%` : '--'}
                </div>
              </div>
              <ReputationRing score={repScore} size={60} stroke={5} />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* ── Stats row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {statCards.map(s => <StatCard key={s.label} {...s} />)}
        </div>

        {/* ── Tabs ── */}
        <div>
          <div className="border-b border-am-border mb-5">
            <div className="flex gap-0">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button key={id}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-1.5 px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === id
                      ? 'border-current'
                      : 'text-am-muted border-transparent hover:text-am-text'
                  }`}
                  style={activeTab === id ? { color: ACCENT, borderColor: ACCENT } : {}}>
                  <Icon size={13} />
                  {label}
                  {id === 'history' && histTotal > 0 && (
                    <span className="ml-1 text-xs px-1.5 py-0.5 rounded-full font-medium"
                      style={{ background: `${ACCENT}15`, color: ACCENT }}>
                      {histTotal}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          <AnimatePresence mode="wait">
            <motion.div key={activeTab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}>
              {activeTab === 'overview' && <OverviewTab agent={agent} stats={stats} />}
              {activeTab === 'history'  && <HistoryTab  history={history} total={histTotal} />}
              {activeTab === 'readme'   && <ReadmeTab   readme={readme} agent={agent} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
