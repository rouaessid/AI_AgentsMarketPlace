import { motion } from 'framer-motion'
import { RefreshCw, ArrowRight, CheckCircle, Loader2, XCircle, Clock } from 'lucide-react'

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

function ScoreBar({ label, value, color = '#6366f1' }) {
  const pct = Math.round((value || 0) * 100)
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-am-muted shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-am-surface rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="w-7 text-right font-mono text-am-text-2">{pct}%</span>
    </div>
  )
}

const STATUS_CONFIG = {
  pending:   { icon: Clock,       color: '#94a3b8', spin: false },
  running:   { icon: Loader2,     color: '#6366f1', spin: true  },
  done:      { icon: CheckCircle, color: '#10b981', spin: false },
  failed:    { icon: XCircle,     color: '#ef4444', spin: false },
}

export default function SubTaskCard({ subtask, agent, index, stepStatus, onChangeAgent }) {
  const ds = domainStyle(subtask?.domain)
  const sc = STATUS_CONFIG[stepStatus] || STATUS_CONFIG.pending
  const StatusIcon = sc.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className="card p-4 flex flex-col gap-3"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-xs font-bold text-am-muted shrink-0">#{index + 1}</span>
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0"
            style={{ background: ds.bg, color: ds.color, borderColor: ds.border }}
          >
            {subtask?.domain || 'unknown'}
          </span>
          <StatusIcon
            size={14}
            style={{ color: sc.color }}
            className={sc.spin ? 'animate-spin' : ''}
          />
        </div>
        {onChangeAgent && (
          <button
            onClick={onChangeAgent}
            className="flex items-center gap-1 text-xs text-am-indigo hover:text-am-indigo-d font-medium transition-colors shrink-0"
          >
            <RefreshCw size={12} /> Change
          </button>
        )}
      </div>

      {/* Description */}
      <p className="text-sm text-am-text leading-relaxed line-clamp-2">
        {subtask?.description}
      </p>

      {/* Depends on */}
      {subtask?.depends_on?.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          <ArrowRight size={11} className="text-am-muted" />
          {subtask.depends_on.map(dep => (
            <span key={dep} className="text-xs px-1.5 py-0.5 bg-am-surface rounded text-am-muted font-mono">
              {dep}
            </span>
          ))}
        </div>
      )}

      {/* Agent info */}
      {agent && (
        <div className="border-t border-am-border pt-3 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-am-text">{agent.agent_name}</div>
              {agent.description && (
                <div className="text-xs text-am-muted mt-0.5 line-clamp-1">{agent.description}</div>
              )}
            </div>
            {agent.price_per_task > 0 && (
              <div className="text-right shrink-0 ml-2">
                <div className="text-xs font-bold text-am-text">{agent.price_per_task.toFixed(4)} ETH</div>
                <div className="text-xs text-am-muted">per task</div>
              </div>
            )}
          </div>
          <ScoreBar label="Match"  value={agent.cosine_score} color="#6366f1" />
          <ScoreBar label="Trust"  value={agent.trust_score}  color="#10b981" />
          <ScoreBar label="Score"  value={agent.final_score}  color="#8b5cf6" />
        </div>
      )}
    </motion.div>
  )
}
