const BASE = '/api/v1/agents'

function _getToken() {
  try {
    const saved = localStorage.getItem('agentmarket_auth')
    return saved ? JSON.parse(saved).token : null
  } catch { return null }
}

const SENSITIVE_ENV_KEY_PARTS = [
  'PRIVATE_KEY',
  'SECRET_KEY',
  'WALLET_KEY',
  'MNEMONIC',
  'SEED_PHRASE',
]

function publicEnvKeys(keys = []) {
  return (keys || []).filter((key) =>
    !SENSITIVE_ENV_KEY_PARTS.some((part) => String(key).toUpperCase().includes(part))
  )
}

async function fetchJSON(url, opts = {}) {
  const token = _getToken()
  const res = await fetch(url, {
    ...opts,
    headers: {
      ...(opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...opts.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const agentApi = {
  list:     (page = 1, size = 50) => fetchJSON(`${BASE}?page=${page}&size=${size}`),
  get:      (id)   => fetchJSON(`${BASE}/${id}`),
  readme:   (id)   => fetchJSON(`${BASE}/${id}/readme`),
  versions: (id)   => fetchJSON(`${BASE}/${id}/versions`),
  endpoint: (id)   => fetchJSON(`${BASE}/${id}/endpoint`),
  byOwner:  (addr) => fetchJSON(`${BASE}/owner/${addr}`),

  register: (data) =>
    fetchJSON(`${BASE}/register`, { method: 'POST', body: JSON.stringify(data) }),

  confirm: (body) =>
    fetchJSON(`${BASE}/confirm`, { method: 'POST', body: JSON.stringify(body) }),

  status: (agentId) => fetchJSON(`${BASE}/${agentId}/status`),

  // Editorial changes (description, readme, price) — no blockchain tx
  editAgent: (agentId, body) =>
    fetchJSON(`${BASE}/${agentId}`, { method: 'PATCH', body: JSON.stringify(body) }),

  // New code version — triggers mintNewVersion() on-chain
  newVersion: (agentId, body) =>
    fetchJSON(`${BASE}/${agentId}/version`, { method: 'POST', body: JSON.stringify(body) }),

  run: (agentId, body, buyerWallet = null, runId = null) => {
    let url = `${BASE}/${agentId}/run`
    if (runId) url += `?run_id=${runId}`
    return fetchJSON(url, {
      method: 'POST',
      body: JSON.stringify({ ...body, buyer_wallet: buyerWallet }),
    })
  },

  liveLogs: (agentId, runId) =>
    fetchJSON(`${BASE}/${agentId}/run/${runId}/live-logs`),

  sandbox: (agentId, prompt) =>
    fetchJSON(`${BASE}/${agentId}/sandbox?task_prompt=${encodeURIComponent(prompt)}`, { method: 'POST' }),

  // ── Buyer / Validation ────────────────────────────────────────────────────
  getPurchaseInfo: (agentId) =>
    fetchJSON(`${BASE}/${agentId}/purchase-info`),

  purchase: (agentId, body) =>
    fetchJSON(`${BASE}/${agentId}/grant-access`, { method: 'POST', body: JSON.stringify(body) }),

  checkAccess: (agentId, buyerWallet) =>
    fetchJSON(`${BASE}/${agentId}/access?buyer_wallet=${encodeURIComponent(buyerWallet)}`),

  getValidation: (agentId) =>
    fetchJSON(`${BASE}/${agentId}/validation`),

  triggerValidation: (agentId) =>
    fetchJSON(`${BASE}/${agentId}/validate`, { method: 'POST' }),

  // ── Reputation ────────────────────────────────────────────────────────────
  getReputation: (agentId) =>
    fetch(`/api/v1/reputation/${agentId}`)
      .then(r => r.ok ? r.json() : null)
      .catch(() => null),

  getFeedbackInfo: (agentId, score) =>
    fetchJSON(`/api/v1/agents/${agentId}/feedback-info?score=${score}`),

  // DEAD — remplacé par getFeedbackInfo + eth_sendTransaction (MetaMask direct)
  // submitFeedback: (agentId, score, comment) => ...

  // Notifie le backend après un tx MetaMask confirmé → déclenche recalcul EigenTrust
  notifyFeedback: (agentId, body) =>
    fetchJSON(`/api/v1/reputation/${agentId}/feedback-notify`, {
      method: 'POST',
      body: JSON.stringify(body),
    }).catch(() => {}),

  simulateValidation: (agentId, score = 80) =>
    fetchJSON('/api/v1/reputation/debug/simulate-validation', {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId, score }),
    }),

  // ── Judge-specific ────────────────────────────────────────────────────────
  judgeStats:   (agentId) => fetchJSON(`${BASE}/${agentId}/judge-stats`),
  judgeHistory: (agentId, limit = 50, offset = 0) =>
    fetchJSON(`${BASE}/${agentId}/judge-history?limit=${limit}&offset=${offset}`),
}

const TASKS_BASE = '/api/v1/tasks'

export const taskApi = {
  planOnly: (prompt, buyerWallet = '') =>
    fetchJSON(`${TASKS_BASE}/plan-only`, {
      method: 'POST',
      body: JSON.stringify({ prompt, buyer_wallet: buyerWallet }),
    }),

  getAlternatives: (subtaskDescription, excludedAgentIds = [], limit = 5) =>
    fetchJSON(`${TASKS_BASE}/alternatives`, {
      method: 'POST',
      body: JSON.stringify({
        subtask_description: subtaskDescription,
        excluded_agent_ids: excludedAgentIds,
        limit,
      }),
    }),

  pipelinePurchaseInfo: (taskId) =>
    fetchJSON(`${TASKS_BASE}/pipeline-purchase-info`, {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId }),
    }),

  execute: (taskId, planData = {}) =>
    fetchJSON(`${TASKS_BASE}/execute`, {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, ...planData }),
    }),

  packProposals: (prompt, buyerWallet = '') =>
    fetchJSON(`${TASKS_BASE}/pack-proposals`, {
      method: 'POST',
      body: JSON.stringify({ prompt, buyer_wallet: buyerWallet }),
    }),

  selectPack: ({ packId, prompt, mode, reasoning = '', subtasks, agents, buyerWallet = '', packName = '' }) =>
    fetchJSON(`${TASKS_BASE}/select-pack`, {
      method: 'POST',
      body: JSON.stringify({
        pack_id: packId, prompt, mode, reasoning,
        subtasks, agents, buyer_wallet: buyerWallet, pack_name: packName,
      }),
    }),

  run: (prompt, buyerWallet = '') =>
    fetchJSON(`${TASKS_BASE}/run`, {
      method: 'POST',
      body: JSON.stringify({ prompt, buyer_wallet: buyerWallet }),
    }),

  getStatus: (taskId) =>
    fetchJSON(`${TASKS_BASE}/${taskId}/status`),

  list: (buyerWallet = '', limit = 20) =>
    fetchJSON(`${TASKS_BASE}/?buyer_wallet=${encodeURIComponent(buyerWallet)}&limit=${limit}`),

  // Pack access — mirrors agentApi.checkAccess / agentApi.purchase for solo agents
  confirmPackAccess: (taskId, body) =>
    fetchJSON(`${TASKS_BASE}/${taskId}/confirm-access`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  checkPackAccess: (taskId, buyerWallet) =>
    fetchJSON(`${TASKS_BASE}/${taskId}/access?buyer_wallet=${encodeURIComponent(buyerWallet)}`),
}

export const authApi = {
  nonce:   (wallet) =>
    fetch(`/api/v1/auth/nonce?wallet=${encodeURIComponent(wallet)}`).then(r => r.json()),
  verify:  (wallet, signature) =>
    fetchJSON('/api/v1/auth/verify', { method: 'POST', body: JSON.stringify({ wallet, signature }) }),
  me:      () => fetchJSON('/api/v1/auth/me'),
  refresh: () => fetchJSON('/api/v1/auth/refresh', { method: 'POST' }),
}

export function normalizeAgent(a) {
  const reg = a.registration_file || {}
  const caps = reg.capabilities || {}
  const price = reg.pricing || {}
  const sand = reg.sandbox_config || {}
  const allServices = reg.services || []
  const firstService = allServices[0] || {}

  return {
    ...a,
    description: a.description ?? reg.description ?? '',
    readme: a.readme ?? reg.readme ?? '',
    image_url: a.image_url ?? reg.image ?? null,
    llm_model: a.llm_model ?? caps.llm_model ?? '',
    framework: a.framework ?? caps.framework ?? '',
    language: a.language ?? caps.language ?? '',
    max_tokens: a.max_tokens ?? caps.max_tokens ?? null,
    docker_image: a.docker_image ?? sand.docker_image ?? null,
    env_var_keys: publicEnvKeys(a.env_var_keys ?? sand.env_var_keys ?? caps.env_var_keys ?? reg.env_var_keys ?? []),
    special_caps: a.special_caps ?? caps.special_caps ?? [],
    supported_tasks: a.supported_tasks ?? firstService.skills ?? allServices.flatMap((s) => s.skills || []),
    categories: a.categories ?? caps.categories ?? [],
    badges: a.badges ?? caps.badges ?? [],
    api_endpoint: a.api_endpoint ?? a.platform_endpoint ?? null,
    price_per_task: a.price_per_task ?? price.price_per_task ?? 0,
    access_duration_days: a.access_duration_days ?? price.access_duration_days ?? 30,
    max_calls_per_day: a.max_calls_per_day ?? price.max_calls_per_day ?? 100,
    stake_amount: a.stake_amount ?? reg.stake_amount ?? 0,
    metrics: {
      reputation_score: caps.reputation_score ?? null,
      success_rate: caps.success_rate ?? null,
      tasks_performed: caps.tasks_performed ?? null,
      avg_response_time: caps.avg_response_time ?? null,
      usage_count: caps.usage_count ?? null,
      rank: caps.rank ?? null,
      task_completion_rate: caps.task_completion_rate ?? null,
      uptime: caps.uptime ?? null,
      last_active: caps.last_active ?? null,
      monthly_tasks: caps.monthly_tasks ?? [],
      weekly_success: caps.weekly_success ?? [],
    },
    // Judge-specific fields — stored inside registration_file, not at AgentRecord root
    evaluation_skills:    a.evaluation_skills    ?? reg.evaluation_skills    ?? [],
    validated_task_types: a.validated_task_types ?? reg.validated_task_types ?? [],
    evaluation_domains:   a.evaluation_domains   ?? reg.evaluation_domains   ?? [],
    tools_used:           a.tools_used           ?? reg.tools_used           ?? [],
    evaluation_style:     a.evaluation_style     ?? reg.evaluation_style     ?? '',
  }
}
