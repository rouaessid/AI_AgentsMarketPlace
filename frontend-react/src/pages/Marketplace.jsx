import { useState, useMemo, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Search, SlidersHorizontal, ChevronDown, Cpu, Shield, X, RefreshCw, AlertCircle } from 'lucide-react'
import AgentCard from '../components/marketplace/AgentCard'
import { agentApi, normalizeAgent } from '../api/agentApi'

const SORTS = [
  { id: 'rank', label: 'Top Ranked' },
  { id: 'reputation', label: 'Reputation' },
  { id: 'success', label: 'Success Rate' },
  { id: 'tasks', label: 'Most Used' },
  { id: 'price_asc', label: 'Price ↑' },
  { id: 'price_desc', label: 'Price ↓' },
]

const TYPE_FILTERS = [
  { id: 'all', label: 'All Types' },
  { id: 'provider', label: 'Providers' },
]

export default function Marketplace() {
  const [agents, setAgents] = useState([])
  const [categories, setCategories] = useState([{ id: 'all', label: 'All Agents', count: 0 }])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [cat, setCat] = useState('all')
  const [type, setType] = useState('all')
  const [sort, setSort] = useState('rank')
  const [showFilters, setShowFilters] = useState(false)

  const fetchAgents = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await agentApi.list(1, 50)
      const normalized = (data.agents || [])
        .map(normalizeAgent)
        .filter((a) => a.agent_type !== 'judge')
      setAgents(normalized)

      const catMap = {}
      normalized.forEach((agent) => {
        ;(agent.categories || []).forEach((category) => {
          if (category) catMap[category] = (catMap[category] || 0) + 1
        })
      })

      setCategories([
        { id: 'all', label: 'All Agents', count: normalized.length },
        ...Object.entries(catMap).map(([id, count]) => ({
          id,
          label: id.charAt(0).toUpperCase() + id.slice(1),
          count,
        })),
      ])
    } catch (e) {
      setAgents([])
      setCategories([{ id: 'all', label: 'All Agents', count: 0 }])
      setError(e.message || 'Failed to load agents')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAgents() }, [fetchAgents])

  const filtered = useMemo(() => {
    let list = [...agents]
    if (query.trim()) {
      const q = query.toLowerCase()
      list = list.filter((a) =>
        a.name?.toLowerCase().includes(q) ||
        a.description?.toLowerCase().includes(q) ||
        (a.categories || []).some((c) => c.toLowerCase().includes(q)) ||
        (a.supported_tasks || []).some((t) => t.toLowerCase().includes(q))
      )
    }
    if (cat !== 'all') list = list.filter((a) => (a.categories || []).includes(cat))
    if (type !== 'all') list = list.filter((a) => a.agent_type === type)

    list.sort((a, b) => {
      const ma = a.metrics || {}
      const mb = b.metrics || {}
      switch (sort) {
        case 'rank': return (ma.rank ?? Number.MAX_SAFE_INTEGER) - (mb.rank ?? Number.MAX_SAFE_INTEGER)
        case 'reputation': return (mb.reputation_score ?? -1) - (ma.reputation_score ?? -1)
        case 'success': return (mb.success_rate ?? -1) - (ma.success_rate ?? -1)
        case 'tasks': return (mb.tasks_performed ?? -1) - (ma.tasks_performed ?? -1)
        case 'price_asc': return (a.price_per_task ?? 0) - (b.price_per_task ?? 0)
        case 'price_desc': return (b.price_per_task ?? 0) - (a.price_per_task ?? 0)
        default: return 0
      }
    })
    return list
  }, [agents, query, cat, type, sort])

  const featured = filtered.filter((a) => (a.metrics?.rank ?? Number.MAX_SAFE_INTEGER) <= 3)
  const regular = filtered.filter((a) => (a.metrics?.rank ?? Number.MAX_SAFE_INTEGER) > 3)

  return (
    <div className="min-h-screen bg-am-bg">
      <div className="bg-white border-b border-am-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="section-label">Marketplace</p>
              <h1 className="text-2xl sm:text-3xl font-bold text-am-text">AI Agent Registry</h1>
              <p className="text-am-text-2 mt-1 text-sm">
                {loading ? 'Loading…' : `${agents.length} agents loaded from the registry`}
              </p>
            </div>
            <button onClick={fetchAgents} disabled={loading} className="btn-ghost flex items-center gap-2 text-sm mt-1">
              <RefreshCw size={14} className={loading ? 'animate-spin-slow' : ''} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col sm:flex-row gap-3 mb-6">
          <div className="relative flex-1">
            <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-am-muted" />
            <input
              type="text"
              placeholder="Search agents, tasks, capabilities…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="input pl-10 pr-4"
            />
            {query && (
              <button onClick={() => setQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-am-muted hover:text-am-text">
                <X size={14} />
              </button>
            )}
          </div>

          <div className="relative">
            <select value={sort} onChange={(e) => setSort(e.target.value)} className="input appearance-none pr-8 pl-4 cursor-pointer min-w-[160px]">
              {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-am-muted pointer-events-none" />
          </div>

          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border-2 text-sm font-semibold transition-all ${
              showFilters
                ? 'border-am-indigo/40 text-am-indigo bg-indigo-50'
                : 'border-am-border text-am-text-2 hover:text-am-text hover:border-am-indigo/20'
            }`}
          >
            <SlidersHorizontal size={14} /> Filters
          </button>
        </div>

        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="card p-5 mb-6 grid sm:grid-cols-2 gap-6"
          >
            <div>
              <div className="text-xs font-semibold text-am-muted uppercase tracking-wider mb-3">Category</div>
              <div className="flex flex-wrap gap-2">
                {categories.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setCat(c.id)}
                    className={`text-xs px-3 py-1.5 rounded-full border-2 font-medium transition-all ${
                      cat === c.id
                        ? 'border-am-indigo/40 text-am-indigo bg-indigo-50'
                        : 'border-am-border text-am-text-2 hover:border-am-indigo/20 hover:text-am-text'
                    }`}
                  >
                    {c.label} <span className="opacity-50">({c.count})</span>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-am-muted uppercase tracking-wider mb-3">Agent Type</div>
              <div className="flex gap-2">
                {TYPE_FILTERS.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setType(t.id)}
                    className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border-2 font-medium transition-all ${
                      type === t.id
                        ? 'border-am-violet/40 text-am-violet-d bg-violet-50'
                        : 'border-am-border text-am-text-2 hover:border-am-violet/20 hover:text-am-text'
                    }`}
                  >
                    {t.id === 'provider' && <Cpu size={10} />}
                    {t.id === 'judge' && <Shield size={10} />}
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {error && (
          <div className="flex items-center gap-3 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 mb-6 text-sm text-am-rose">
            <AlertCircle size={16} />
            {error}
          </div>
        )}

        <div className="text-sm text-am-muted mb-6">
          Showing <span className="text-am-text font-semibold">{filtered.length}</span> agents
          {query && <span> matching "<span className="text-am-indigo font-medium">{query}</span>"</span>}
        </div>

        {loading && (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="card h-64 animate-pulse">
                <div className="h-1 w-full rounded-t-2xl bg-am-surface" />
                <div className="p-5 space-y-3">
                  <div className="flex gap-3">
                    <div className="w-12 h-12 rounded-2xl bg-am-surface" />
                    <div className="flex-1 space-y-2">
                      <div className="h-4 w-2/3 rounded bg-am-surface" />
                      <div className="h-3 w-1/3 rounded bg-am-surface" />
                    </div>
                  </div>
                  <div className="h-3 w-full rounded bg-am-surface" />
                  <div className="h-3 w-5/6 rounded bg-am-surface" />
                  <div className="grid grid-cols-3 gap-2 pt-2">
                    {[...Array(3)].map((__, j) => (
                      <div key={j} className="h-14 rounded-xl bg-am-surface" />
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {filtered.length === 0 && !loading && (
          <div className="text-center py-24">
            <div className="w-14 h-14 rounded-2xl bg-am-surface border border-am-border flex items-center justify-center mx-auto mb-4">
              <Cpu size={24} className="text-am-muted" />
            </div>
            <p className="font-semibold text-am-text mb-1">No agents found</p>
            <p className="text-sm text-am-muted">The list is now driven only by live backend data.</p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <>
            {featured.length > 0 && !query && (
              <div className="mb-10">
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-xs font-bold text-am-amber uppercase tracking-widest">Top Ranked</span>
                  <div className="flex-1 h-px bg-am-border" />
                </div>
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                  {featured.map((agent, i) => (
                    <AgentCard key={agent.id || agent.agent_id} agent={agent} index={i} />
                  ))}
                </div>
              </div>
            )}

            {(regular.length > 0 || query) && (
              <div>
                {featured.length > 0 && !query && (
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-xs font-semibold text-am-muted uppercase tracking-wider">All Agents</span>
                    <div className="flex-1 h-px bg-am-border" />
                  </div>
                )}
                <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
                  {(query ? filtered : regular).map((agent, i) => (
                    <AgentCard key={agent.id || agent.agent_id} agent={agent} index={i} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
