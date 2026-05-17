import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2, TrendingUp, Star, Check } from 'lucide-react'
import { taskApi } from '../../api/agentApi'

function ScorePill({ value, color }) {
  return (
    <span
      className="text-xs font-mono font-semibold px-1.5 py-0.5 rounded"
      style={{ background: `${color}18`, color }}
    >
      {Math.round((value || 0) * 100)}%
    </span>
  )
}

export default function AgentSelector({ subtask, currentAgentId, excludedAgentIds = [], onSelect, onClose }) {
  const [alternatives, setAlternatives] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    taskApi.getAlternatives(subtask.description, excludedAgentIds, 8)
      .then(data => {
        if (!cancelled) setAlternatives(data.alternatives || [])
      })
      .catch(err => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [subtask.description])

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

        {/* Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 16 }}
          transition={{ duration: 0.2 }}
          className="relative bg-white rounded-2xl border border-am-border shadow-card-lg w-full max-w-lg max-h-[80vh] flex flex-col"
        >
          {/* Header */}
          <div className="px-5 py-4 border-b border-am-border flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold text-am-text text-sm">Select Agent</div>
              <div className="text-xs text-am-muted mt-0.5 line-clamp-2">{subtask.description}</div>
            </div>
            <button onClick={onClose} className="text-am-muted hover:text-am-text transition-colors shrink-0 mt-0.5">
              <X size={18} />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-4">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-10 text-am-muted">
                <Loader2 size={18} className="animate-spin" />
                <span className="text-sm">Finding best agents…</span>
              </div>
            )}
            {error && !loading && (
              <div className="text-center py-8 text-am-rose text-sm">{error}</div>
            )}
            {!loading && !error && alternatives.length === 0 && (
              <div className="text-center py-8 text-am-muted text-sm">No agents available</div>
            )}
            {!loading && !error && alternatives.map((agent, i) => {
              const isSelected = agent.agent_id === currentAgentId
              return (
                <motion.button
                  key={agent.agent_id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.04 }}
                  onClick={() => { onSelect(agent); onClose() }}
                  className={`w-full text-left p-3.5 rounded-xl border mb-2 transition-all hover:shadow-card ${
                    isSelected
                      ? 'border-am-indigo bg-indigo-50'
                      : 'border-am-border hover:border-am-indigo/40 hover:bg-am-surface'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        {i === 0 && !isSelected && (
                          <Star size={11} className="text-amber-400 fill-amber-400 shrink-0" />
                        )}
                        <span className="text-sm font-semibold text-am-text truncate">
                          {agent.agent_name}
                        </span>
                        {isSelected && <Check size={13} className="text-am-indigo shrink-0" />}
                      </div>
                      {agent.description && (
                        <div className="text-xs text-am-muted mt-0.5 line-clamp-1">{agent.description}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <TrendingUp size={11} className="text-am-muted" />
                      <ScorePill value={agent.final_score} color="#6366f1" />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-xs text-am-muted">Match</span>
                    <ScorePill value={agent.cosine_score} color="#6366f1" />
                    <span className="text-xs text-am-muted ml-1">Trust</span>
                    <ScorePill value={agent.trust_score} color="#10b981" />
                    {agent.price_per_task > 0 && (
                      <span className="ml-auto text-xs font-mono text-am-text-2">
                        {agent.price_per_task.toFixed(4)} ETH
                      </span>
                    )}
                  </div>
                </motion.button>
              )
            })}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
