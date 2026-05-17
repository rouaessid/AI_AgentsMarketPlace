# REGISTRATION : JUDGE vs PROVIDER AGENT

---

## 🔴 PROVIDER AGENT (Normal - Exécute des tâches)

### Formulaire Frontend
```javascript
POST /register avec:
{
  agent_id: "search-1",
  name: "Search Agent",
  description: "Recherche d'informations...",
  agent_type: "provider",          ← CLEF
  
  // Technical
  docker_image: "username/search:v1",
  services: [{name: "search", endpoint: "http://...", skills: ["web_search"]}],
  supported_tasks: ["research"],
  special_caps: ["real-time"],
  
  // Hardware
  cpu_limit: 2,
  ram_limit_mb: 1024,
  timeout_sec: 60,
  
  // Price & Stake
  price_per_task: 0.01,
  stake_amount: 0.05,
  
  // Metadata
  image_url: "...",
  readme: "...",
  owner_address: "0x...",
  
  // ❌ PAS DE CHAMPS JUDGE ICI
}
```

### Ce qui est stocké (AgentRegistrationFile)
```python
{
  name: "Search Agent",
  description: "...",
  agent_type: "provider",
  services: [...],
  capabilities: {
    supported_tasks: ["research"],
    special_caps: ["web_search"]
  },
  sandbox_config: {
    docker_image: "username/search:v1",
    cpu_limit: 2,
    ram_limit_mb: 1024,
    timeout_sec: 60
  },
  pricing: {
    price_per_task: 0.01
  },
  stake_amount: 0.05,
  
  # ❌ Champs judge ignorés (vides par défaut)
  evaluation_skills: [],
  validated_task_types: [],
  evaluation_domains: []
}
```

---

## 🟢 JUDGE AGENT (Évalue les tâches)

### Formulaire Frontend (À IMPLÉMENTER)
```javascript
POST /register avec:
{
  agent_id: "judge-alpha",
  name: "Judge Alpha",
  description: "Expert en code et API...",
  agent_type: "judge",          ← CLEF
  
  // Technical
  docker_image: "username/judge-alpha:v1",
  services: [{name: "evaluate", endpoint: "http://..."}],
  
  // Hardware (même chose que provider)
  cpu_limit: 1,
  ram_limit_mb: 512,
  timeout_sec: 30,
  
  // Price & Stake
  price_per_task: 0.002,  ← moins cher (juge pas d'exécution)
  stake_amount: 0.02,
  
  // Metadata
  image_url: "...",
  readme: "...",
  owner_address: "0x...",
  
  // 🟢 NOUVEAUX CHAMPS JUDGE (À AJOUTER)
  evaluation_skills: [
    "Python",
    "FastAPI",
    "Security",
    "API_Design"
  ],
  
  validated_task_types: [
    "code",
    "analyze",
    "review"
  ],
  
  evaluation_domains: [
    "Software Development",
    "Security",
    "Backend"
  ]
}
```

### Ce qui est stocké (AgentRegistrationFile)
```python
{
  name: "Judge Alpha",
  description: "...",
  agent_type: "judge",          ← Type different
  services: [...],
  sandbox_config: {
    docker_image: "username/judge-alpha:v1",
    cpu_limit: 1,
    ram_limit_mb: 512,
    timeout_sec: 30
  },
  pricing: {
    price_per_task: 0.002
  },
  stake_amount: 0.02,
  
  # 🟢 CHAMPS JUDGE (stockés)
  evaluation_skills: [
    "Python",
    "FastAPI", 
    "Security",
    "API_Design"
  ],
  
  validated_task_types: [
    "code",
    "analyze",
    "review"
  ],
  
  evaluation_domains: [
    "Software Development",
    "Security",
    "Backend"
  ]
}
```

---

## 📊 COMPARAISON

| Champ | Provider | Judge | Signification |
|-------|----------|-------|---|
| **agent_type** | "provider" | "judge" | Type d'agent |
| **docker_image** | Exécute la tâche | Évalue la tâche | Code différent |
| **services** | Fait le travail | Évalue le travail | Rôles différents |
| **evaluation_skills** | ❌ Ignoré | ✅ **Requis** | Compétences techniques du juge |
| **validated_task_types** | ❌ Ignoré | ✅ **Requis** | Types de tâches qu'il peut évaluer |
| **evaluation_domains** | ❌ Ignoré | ✅ **Requis** | Domaines d'expertise |
| **price_per_task** | ✅ Normal (0.01) | ✅ Réduit (0.002) | Les juges coûtent moins cher |
| **stake_amount** | ✅ Normal (0.05) | ✅ Réduit (0.02) | Moins d'enjeu pour les juges |

---

## 🔄 FLUX D'ENREGISTREMENT

### PROVIDER
```
User fills form (frontend)
    ↓
POST /register
    {
      agent_id, name, docker_image,
      services, supported_tasks, price, stake, ...
    }
    ↓
Backend: _build_reg_file(req)
    ├─ Creates AgentRegistrationFile
    ├─ Fills: name, services, capabilities, sandbox_config, pricing
    ├─ Ignores: evaluation_skills, validated_task_types, evaluation_domains
    └─ → AgentRegistrationFile with empty judge fields
    ↓
Backend: sign + upload IPFS + emit on-chain
    ↓
PROVIDER AGENT ACTIVE ✅
```

### JUDGE (TO BE IMPLEMENTED)
```
User fills form (frontend) ← NEEDS NEW FIELDS
    ↓
POST /register
    {
      agent_id, name, docker_image,
      evaluation_skills, validated_task_types, evaluation_domains,  ← NEW
      price, stake, ...
    }
    ↓
Backend: _build_reg_file(req) ← NEEDS MODIFICATION
    ├─ Creates AgentRegistrationFile
    ├─ Fills: name, services, capabilities
    ├─ NEW: Sets evaluation_skills, validated_task_types, evaluation_domains
    └─ → AgentRegistrationFile with judge fields populated
    ↓
Backend: sign + upload IPFS + emit on-chain
    ↓
JUDGE AGENT ACTIVE ✅
```

---

## ✅ WHAT NEEDS TO BE DONE

### 1. Update AgentSubmitRequest (backend model)
```python
# models/agent.py - Add judge fields to AgentSubmitRequest
class AgentSubmitRequest(BaseModel):
    # ... existing fields ...
    agent_type: AgentType = AgentType.PROVIDER
    
    # 🆕 Judge-specific fields (optional, only used if agent_type=JUDGE)
    evaluation_skills: list[str] = Field(
        default_factory=list,
        description="Tools the judge can evaluate (Python, FastAPI, Security, ...)"
    )
    validated_task_types: list[str] = Field(
        default_factory=list,
        description="Task types judge can validate (code, analyze, review, ...)"
    )
    evaluation_domains: list[str] = Field(
        default_factory=list,
        description="Domains judge specializes in (Software, Security, Backend, ...)"
    )
```

### 2. Update _build_reg_file (backend service)
```python
# services/agent_service.py
def _build_reg_file(req: AgentSubmitRequest) -> AgentRegistrationFile:
    reg_file = AgentRegistrationFile(
        name=req.name,
        description=req.description,
        # ... existing ...
        
        # 🆕 Judge fields (if agent_type=JUDGE)
        evaluation_skills=req.evaluation_skills if req.agent_type == AgentType.JUDGE else [],
        validated_task_types=req.validated_task_types if req.agent_type == AgentType.JUDGE else [],
        evaluation_domains=req.evaluation_domains if req.agent_type == AgentType.JUDGE else [],
    )
    return reg_file
```

### 3. Update Frontend Form
```javascript
// RegisterAgent.jsx - conditionally show judge fields
if (agentType === "judge") {
  show: [
    "Evaluation Skills (checkboxes): Python, FastAPI, Security, ...",
    "Validated Task Types (checkboxes): code, analyze, review, ...",
    "Evaluation Domains (checkboxes): Software, Security, Backend, ..."
  ]
}
```

---

## 📌 CURRENT STATE

- ✅ `AgentRegistrationFile` model has judge fields defined (line 58-60 agent.py)
- ❌ `AgentSubmitRequest` does NOT have judge fields
- ❌ `_build_reg_file()` does NOT populate judge fields
- ❌ Frontend form does NOT show judge fields

**So: The data structure exists, but the INPUT FORM and SERVICE don't use them yet!**
