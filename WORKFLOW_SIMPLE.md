# WORKFLOWS : Tâche Simple vs Tâche Décomposée

---

## 🎯 TÂCHE SIMPLE (1 seul agent)

```
USER REQUEST
    ↓
    "Créer un résumé de ce document"
    ↓
PLANNER
    ↓
    Plan : 1 subtask only
    ├─ id: "st-1"
    ├─ description: "Créer un résumé de ce document"
    └─ domain: "summarization"
    ↓
EIGENTRUST + MATCHING
    ↓
    Load all agents with embeddings
    ├─ Compute EigenTrust (trust_scores pour chaque agent)
    ├─ Embedding task = "Créer un résumé..."
    ├─ For each agent:
    │   score = 0.6 × cosine(task_emb, agent_emb) + 0.4 × trust_score
    ├─ Select TOP 1 agent (best score)
    └─ Result: Agent_Alpha (score=0.87)
    ↓
DATABASE SAVE (pipeline_tasks)
    ├─ task_id: "task-uuid"
    ├─ status: "plan_ready"
    ├─ plan: [{subtask_1}]
    └─ selected_agents: [Agent_Alpha]
    ↓
EXECUTION START
    ├─ Spawn Docker container: Agent_Alpha
    ├─ Pass prompt: "Créer un résumé de ce document"
    ├─ Wait for output (timeout: 60s)
    └─ Result: "Le document parle de..."
    ↓
SAVE STEP
    ├─ steps[0]:
    │   ├─ subtask_id: "st-1"
    │   ├─ agent_id: "alpha"
    │   ├─ output: "Le document parle de..."
    │   └─ duration_sec: 12.5
    └─ final_output: "Le document parle de..."
    ↓
🔴 VALIDATION (SOLO MODE = mode=0)
    ├─ Upload output to IPFS → proxy_cid: "QmXXX..."
    ├─ Select 3 JUDGES (judge-alpha, judge-beta, judge-gamma)
    │   └─ Scoring judges:
    │       score = (task_match×3) + (tools×2) + (domain×1)
    │       ex: (2×3) + (1×2) + (1×1) = 9
    ├─ Run each judge:
    │   ├─ Judge1: "This output is VALID, score=92/100"
    │   ├─ Judge2: "VALID, score=88/100"
    │   └─ Judge3: "VALID, score=95/100"
    ├─ CONSENSUS: 3/3 VALID → APPROVED ✅
    ├─ AGGREGATED SCORE = (92+88+95)/3 = 91.67
    └─ Insert to judge_verdicts table
    ↓
💾 SAVE VALIDATION RESULT
    ├─ validation_sessions:
    │   ├─ agent_id: "alpha"
    │   ├─ status: "validated"
    │   ├─ consensus_verdict: "VALID"
    │   └─ aggregated_score: 91.67
    └─ agent_reputation:
        ├─ agent_id: "alpha"
        ├─ score_sum: 91.67
        └─ validation_count: 1
    ↓
📊 CALCULATE TRUST SCORE (EigenTrust - SOLO)
    ├─ p[alpha] = mean(judge_scores) = 91.67  ← SEED TRUST
    ├─ C matrix = [[0]] (solo = no collaboration)
    ├─ Power Method: t = (1-α)×C^T×t + α×p
    │   ├─ α = 0.15
    │   ├─ iter1: t = [0.15×91.67] = 13.75
    │   ├─ iter2: convergence...
    │   └─ final: t[alpha] = 0.92
    ├─ f[alpha] = user_feedback (if any) = 1.0
    └─ V[alpha] = t × f = 0.92 × 1.0 = 0.92
    ↓
✅ EMIT ON-CHAIN ScoreRecorded(mode=0)
    ├─ Contract: ValidationRegistry.recordSoloScore()
    ├─ Emit: ScoreRecorded(agentId="alpha", score=92, mode=0)
    ├─ Listener: blockchain_indexer
    └─ Insert: collaboration_log
        ├─ agent_id: "alpha"
        ├─ score: 92.0
        ├─ mode: 0 (solo)
        └─ timestamp: now()
    ↓
🔔 EIGENTRUST SYNC (automatic, triggered by indexer)
    ├─ Recalculate EigenTrust using NEW collaboration_log data
    ├─ Update DB: eigentrust_scores[alpha] = 0.92
    └─ Ready for NEXT TASK
    ↓
✨ FINAL RESULT
    ├─ task_id: "task-uuid"
    ├─ status: "done"
    ├─ final_output: "Le document parle de..."
    ├─ validation_verdict: "VALID"
    ├─ aggregated_score: 91.67
    ├─ agent_scores:
    │   └─ alpha: score=91.67 (saved on-chain)
    └─ eigentrust_score: 0.92 (available for next task)
```

---

## 🔄 TÂCHE DÉCOMPOSÉE (3 agents en pipeline)

```
USER REQUEST
    ↓
    "Chercher un article, le résumer, puis traduire en arabe"
    ↓
PLANNER
    ↓
    Plan: 3 subtasks
    ├─ st-1: "Chercher un article"      domain: "research"
    ├─ st-2: "Résumer l'article"        domain: "summarization"
    └─ st-3: "Traduire en arabe"        domain: "translation"
    ↓
EIGENTRUST + MATCHING (for EACH subtask)
    ↓
    For st-1 (research):
    ├─ task_type="RESEARCH", domain="research"
    ├─ Compute embeddings: "Chercher un article"
    ├─ Score agents:
    │   ├─ Agent_Research: score = 0.6×0.92 + 0.4×0.85 = 0.89 ✅ BEST
    │   ├─ Agent_Summarizer: score = 0.6×0.45 + 0.4×0.88 = 0.62
    │   └─ Agent_Translator: score = 0.6×0.30 + 0.4×0.80 = 0.50
    └─ Selected: Agent_Research
    
    For st-2 (summarization):
    ├─ Available agents: [Agent_Summarizer, Agent_Translator] 
    │   (Agent_Research already assigned)
    ├─ Score agents:
    │   ├─ Agent_Summarizer: score = 0.6×0.91 + 0.4×0.88 = 0.90 ✅ BEST
    │   └─ Agent_Translator: score = 0.6×0.50 + 0.4×0.80 = 0.62
    └─ Selected: Agent_Summarizer
    
    For st-3 (translation):
    ├─ Available agents: [Agent_Translator]
    └─ Selected: Agent_Translator
    ↓
    MATCHES = [
      {subtask: st-1, agent: Research,   score: 0.89},
      {subtask: st-2, agent: Summarizer, score: 0.90},
      {subtask: st-3, agent: Translator, score: 0.70}
    ]
    ↓
DATABASE SAVE
    ├─ task_id: "task-uuid"
    ├─ status: "plan_ready"
    ├─ plan: [st-1, st-2, st-3]
    └─ selected_agents: [Research, Summarizer, Translator]
    ↓
EXECUTION START (Level-based DAG)
    ├─ Level 1 (parallel):
    │   ├─ Agent_Research (st-1)
    │   │   ├─ Input: "Chercher un article sur IA"
    │   │   ├─ Output: "L'article parle de..."
    │   │   └─ SAVE to context[st-1] = "L'article parle de..."
    │   └─ Duration: 8.2s
    │
    ├─ Level 2 (AFTER Level 1):
    │   ├─ Agent_Summarizer (st-2)
    │   │   ├─ Input: context[st-1] + "Résumer"
    │   │   │         = "L'article parle de... → Résumer"
    │   │   ├─ Output: "Résumé : ..."
    │   │   └─ SAVE to context[st-2] = "Résumé : ..."
    │   └─ Duration: 5.1s
    │
    ├─ Level 3 (AFTER Level 2):
    │   ├─ Agent_Translator (st-3)
    │   │   ├─ Input: context[st-2] + "Traduire en arabe"
    │   │   │         = "Résumé : ... → Traduire en arabe"
    │   │   ├─ Output: "ملخص: ..."
    │   │   └─ SAVE to context[st-3] = "ملخص: ..."
    │   └─ Duration: 6.3s
    │
    └─ final_output = context[st-3] = "ملخص: ..."
    ↓
SAVE PIPELINE STEPS
    ├─ steps[0]:
    │   ├─ subtask_id: "st-1"
    │   ├─ agent_id: "research"
    │   ├─ output: "L'article parle de..."
    │   └─ duration_sec: 8.2
    ├─ steps[1]:
    │   ├─ subtask_id: "st-2"
    │   ├─ agent_id: "summarizer"
    │   ├─ output: "Résumé : ..."
    │   └─ duration_sec: 5.1
    └─ steps[2]:
        ├─ subtask_id: "st-3"
        ├─ agent_id: "translator"
        ├─ output: "ملخص: ..."
        └─ duration_sec: 6.3
    ↓
🔴 VALIDATION (PIPELINE MODE = mode=1)
    ├─ Upload final_output to IPFS → proxy_cid: "QmYYY..."
    ├─ Judges evaluate ONLY the lead agent (Research = first agent)
    │   └─ Why? Only lead agent is accountable for final output
    ├─ Select 3 JUDGES (same scoring as before)
    ├─ Run each judge:
    │   ├─ Judge1: "Pipeline output is VALID, score=85/100"
    │   ├─ Judge2: "VALID, score=88/100"
    │   └─ Judge3: "INVALID (bad research), score=45/100"
    ├─ CONSENSUS: 2/3 VALID → APPROVED ✅ (need ≥2)
    ├─ AGGREGATED SCORE = (85+88+45)/3 = 72.67
    └─ Insert to judge_verdicts table
    ↓
💾 SAVE VALIDATION RESULT
    ├─ validation_sessions:
    │   ├─ agent_id: "research"    ← LEAD only
    │   ├─ status: "validated"
    │   ├─ consensus_verdict: "VALID"
    │   └─ aggregated_score: 72.67
    └─ BUT: All 3 agents get scored (see next step)
    ↓
📊 CALCULATE TRUST SCORES (EigenTrust - PIPELINE)
    ├─ LEAD (Research) - Direct scoring:
    │   ├─ p[research] = mean(judge_scores) = 72.67  ← from judges
    │   ├─ C matrix = collaboration capacity with other agents
    │   │   ├─ C[summarizer][research] = uplift[summarizer] / 2
    │   │   │   └─ uplift = max(mean(pipeline_scores) - mean(solo_scores), 0)
    │   │   └─ C[translator][research] = uplift[translator] / 2
    │   ├─ Power Method converges
    │   └─ t[research] = 0.73
    │
    ├─ DOWNSTREAM (Summarizer, Translator) - Distributed credit:
    │   ├─ They get CREDIT from Research's collaboration uplift
    │   ├─ If Summarizer improved Research's output:
    │   │   ├─ p[summarizer] = mean(collaboration_log scores)
    │   │   ├─ Receives credit from C[research][summarizer]
    │   │   └─ t[summarizer] = 0.68
    │   └─ Similar for Translator
    │
    ├─ Final scores after Power Method convergence:
    │   ├─ V[research] = t[research] × f[research] = 0.73
    │   ├─ V[summarizer] = t[summarizer] × f[summarizer] = 0.68
    │   └─ V[translator] = t[translator] × f[translator] = 0.65
    └─ All saved to DB: eigentrust_scores
    ↓
✅ EMIT ON-CHAIN ScoreRecorded for ALL 3 agents (mode=1)
    ├─ Contract: ValidationRegistry.recordPipelineScores()
    ├─ Emit for lead (Research):
    │   ├─ ScoreRecorded(agentId="research", score=72, mode=1)
    │   └─ blockchain_indexer → collaboration_log
    │
    ├─ Emit for non-lead (Summarizer, Translator):
    │   ├─ ScoreRecorded(agentId="summarizer", score=72, mode=1)
    │   ├─ ScoreRecorded(agentId="translator", score=72, mode=1)
    │   └─ (all get same aggregated_score at MVP, but should be proportional)
    │
    └─ blockchain_indexer inserts:
        ├─ collaboration_log
        │   ├─ agent_id: "research",   score: 72.0, mode: 1
        │   ├─ agent_id: "summarizer", score: 72.0, mode: 1
        │   └─ agent_id: "translator", score: 72.0, mode: 1
        └─ (mode=1 = pipeline, triggers C matrix calculation)
    ↓
🔔 EIGENTRUST SYNC (automatic)
    ├─ Use collaboration_log entries (mode=0 and mode=1)
    ├─ Recalculate C matrix (Imbens 2021 ATE):
    │   ├─ For each agent pair:
    │   │   └─ C[j][i] = uplift[j] / (N-1) where j≠i
    │   └─ uplift[j] = max(E[pipeline] - E[solo], 0) / 100
    │
    ├─ Power Method iteration:
    │   ├─ t^(k+1) = (1-α)×C^T×t^(k) + α×p̂
    │   ├─ α = 0.15
    │   ├─ Continue until convergence
    │   └─ final: t[research]=0.73, t[summarizer]=0.68, t[translator]=0.65
    │
    └─ Update DB: eigentrust_scores table
        ├─ research: 0.73
        ├─ summarizer: 0.68
        └─ translator: 0.65
    ↓
✨ FINAL RESULT
    ├─ task_id: "task-uuid"
    ├─ status: "done"
    ├─ final_output: "ملخص: ..."
    ├─ validation_verdict: "VALID" (2/3)
    ├─ aggregated_score: 72.67
    ├─ agent_scores:
    │   ├─ research: 72.67 (on-chain)
    │   ├─ summarizer: 72.67 (on-chain, but should be adjusted)
    │   └─ translator: 72.67 (on-chain, but should be adjusted)
    ├─ eigentrust_scores:
    │   ├─ research: 0.73 (for next task)
    │   ├─ summarizer: 0.68
    │   └─ translator: 0.65
    └─ collaboration_log NOW shows agents worked together
        ├─ research + summarizer: uplift tracked
        └─ research + translator: uplift tracked
```

---

## 📌 KEY DIFFERENCES

| Aspect | SOLO (1 agent) | PIPELINE (N agents) |
|--------|---|---|
| **Planner** | 1 subtask | N subtasks |
| **Matching** | Select best for that task | Select best for EACH subtask (no repeats) |
| **Judges** | Evaluate 1 agent output | Evaluate LEAD agent only |
| **Score source** | Judge scores → p | Judge scores → p (lead only) |
| **Collaboration matrix C** | [[0]] (no collab) | Full NxN matrix with uplifts |
| **EigenTrust seed** | p = judge_scores | p = judge_scores (lead); others via C |
| **All agents scored?** | Yes (1 agent) | Yes (all 3 get points from C matrix) |
| **On-chain emit** | 1 agent, mode=0 | 3 agents, mode=1 |
| **Indexer triggers** | Immediate sync | Immediate sync + C recalc |

---

## 🔗 NEXT TASK (AFTER this one completes)

```
TASK N+1 START:
    ↓
    PLANNER
    ↓
    EIGENTRUST + MATCHING (uses UPDATED scores from TASK N)
    │
    ├─ Load from eigentrust_scores DB:
    │   ├─ research: 0.73  ← Updated from TASK N
    │   ├─ summarizer: 0.68
    │   └─ translator: 0.65
    │
    ├─ These become the trust_scores in select_agents()
    ├─ Formula: score = 0.6×cosine + 0.4×trust_score
    └─ Select best agents using NEW trust_scores
    ↓
    EXECUTION (cycle repeats)
```

---

**Résumé simple** :
- 🟢 **Solo** : 1 agent → juges évaluent → score direct → trust score final
- 🔵 **Pipeline** : N agents → juges évaluent lead → score distribué via collaboration matrix → tous les agents améliorent leur trust
