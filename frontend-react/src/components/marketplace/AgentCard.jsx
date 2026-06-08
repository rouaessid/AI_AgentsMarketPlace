import PropTypes from 'prop-types'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { Shield, Zap, Star, CheckCircle, TrendingUp, Clock, ArrowUpRight, Cpu } from 'lucide-react'
import ReputationRing from '../common/ReputationRing'
import clsx from 'clsx'

const BADGE_STYLES = {
  'Top Rated':   'badge-amber',
  'Verified':    'badge-emerald',
  'Fast':        'badge-sky',
  'High Volume': 'badge-violet',
  'Top Judge':   'badge-amber',
  'Reliable':    'badge-emerald',
  'Trending':    'badge-indigo',
  'Specialist':  'badge-slate',
  'Creative':    'badge-violet',
}

const BADGE_ICONS = {
  'Top Rated': Star, 'Verified': Shield, 'Fast': Zap,
  'High Volume': TrendingUp, 'Top Judge': Star, 'Reliable': CheckCircle,
  'Trending': TrendingUp, 'Specialist': Cpu, 'Creative': Star,
}

const RANK_RING = ['', 'ring-2 ring-amber-400/40', 'ring-2 ring-slate-300/40', 'ring-2 ring-amber-600/30']

export default function AgentCard({ agent, index = 0 }) {
  const m = agent.metrics || {}
  const isJudge = agent.agent_type === 'judge'
  const accentColor = isJudge ? '#7c3aed' : '#6366f1'

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.06 }}
      whileHover={{ y: -3 }}
      className="group card-hover flex flex-col"
    >
      {/* Top accent stripe */}
      <div className="h-1 w-full rounded-t-2xl"
        style={{ background: isJudge
          ? 'linear-gradient(90deg,#8b5cf6,#6366f1)'
          : 'linear-gradient(90deg,#6366f1,#0ea5e9)'
        }} />

      <div className="p-5 flex flex-col flex-1">
        {/* Header */}
        <div className="flex items-start gap-4 mb-4">
          {/* Avatar */}
          <div className={clsx(
            'flex-shrink-0 w-12 h-12 rounded-2xl flex items-center justify-center text-xl font-bold text-white',
            m.rank <= 3 ? RANK_RING[m.rank] || '' : ''
          )}
            style={{ background: isJudge
              ? 'linear-gradient(135deg,#8b5cf6,#6366f1)'
              : 'linear-gradient(135deg,#6366f1,#0ea5e9)'
            }}>
            {agent.name?.charAt(0) || '?'}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-am-text group-hover:text-am-indigo transition-colors truncate text-sm">
                {agent.name}
              </h3>
              <span className={clsx('badge text-xs', isJudge ? 'badge-violet' : 'badge-indigo')}>
                {isJudge ? 'Judge' : 'Provider'}
              </span>
            </div>
            <p className="text-xs text-am-muted mt-0.5 font-mono">v{agent.version}</p>
          </div>

          <div className="flex flex-col items-end gap-1">
            {!(m.tasks_performed > 0) ? (
              <span className="text-xs text-am-muted italic">New</span>
            ) : (
              <ReputationRing score={m.reputation_score ?? 0} size={46} stroke={4} />
            )}
            {m.rank <= 3 && (
              <span className="text-xs font-bold" style={{
                color: m.rank === 1 ? '#d97706' : m.rank === 2 ? '#64748b' : '#92400e'
              }}>
                #{m.rank} {m.rank === 1 ? '🥇' : m.rank === 2 ? '🥈' : '🥉'}
              </span>
            )}
          </div>
        </div>

        {/* Description */}
        <p className="text-sm text-am-text-2 leading-relaxed line-clamp-2 mb-4">{agent.description}</p>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          <StatBox
            value={(agent.agent_type === 'judge' || agent.agent_type === 1) && !(m.tasks_performed > 0) ? '—' : `${m.success_rate ?? 0}%`}
            label="Success"
            color={(m.success_rate ?? 0) >= 95 ? '#10b981' : (m.success_rate ?? 0) >= 80 ? '#f59e0b' : '#f43f5e'}
          />
          <StatBox value={
            (m.tasks_performed ?? 0) >= 1000
              ? `${((m.tasks_performed ?? 0)/1000).toFixed(1)}k`
              : String(m.tasks_performed ?? 0)
          } label="Tasks" color={accentColor} />
          <StatBox value={`${m.avg_response_time ?? 0}s`} label="Avg Time" color="#8b5cf6" />
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          {(agent.categories || []).slice(0, 3).map(c => (
            <span key={c} className="text-xs px-2.5 py-1 rounded-full bg-am-surface text-am-text-2 border border-am-border">
              {c}
            </span>
          ))}
          {(agent.badges || []).slice(0, 2).map(b => {
            const cls  = BADGE_STYLES[b] || 'badge-slate'
            const Icon = BADGE_ICONS[b]  || Star
            return (
              <span key={b} className={clsx('badge', cls)}>
                <Icon size={9} /> {b}
              </span>
            )
          })}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-3 border-t border-am-border mt-auto">
          <div>
            <span className="text-lg font-bold text-am-text">{agent.price_per_task ?? 0} ETH</span>
            <span className="text-xs text-am-muted ml-1">/ task</span>
          </div>
          <Link
            to={`/marketplace/${agent.agent_id}`}
            className={clsx(
              'flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-xl transition-all duration-200',
              isJudge
                ? 'bg-violet-50 text-am-violet-d border border-violet-200 hover:bg-violet-100'
                : 'bg-indigo-50 text-am-indigo-d border border-indigo-200 hover:bg-indigo-100'
            )}
          >
            View <ArrowUpRight size={14} />
          </Link>
        </div>
      </div>
    </motion.div>
  )
}

function StatBox({ value, label, color }) {
  return (
    <div className="rounded-xl px-2.5 py-2.5 text-center bg-am-surface border border-am-border">
      <div className="text-sm font-bold" style={{ color }}>{value}</div>
      <div className="text-xs text-am-muted mt-0.5">{label}</div>
    </div>
  )
}

AgentCard.propTypes = {
  agent: PropTypes.object.isRequired,
  index: PropTypes.number,
}

StatBox.propTypes = {
  value: PropTypes.string.isRequired,
  label: PropTypes.string.isRequired,
  color: PropTypes.string.isRequired,
}
