const BASE = '/api/v1/agents'

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: {
      ...(opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
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
    fetchJSON(`${BASE}/${agentId}/purchase`, { method: 'POST', body: JSON.stringify(body) }),

  checkAccess: (agentId, buyerWallet) =>
    fetchJSON(`${BASE}/${agentId}/access?buyer_wallet=${encodeURIComponent(buyerWallet)}`),

  getValidation: (agentId) =>
    fetchJSON(`${BASE}/${agentId}/validation`),

  triggerValidation: (agentId) =>
    fetchJSON(`${BASE}/${agentId}/validate`, { method: 'POST' }),
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
    env_var_keys: a.env_var_keys ?? sand.env_var_keys ?? caps.env_var_keys ?? [],
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
  }
}
