import xml.etree.ElementTree as ET

# ── Données du diagramme ─────────────────────────────────────────────────────

CONTRACTS = [
    {
        "id": "IdentityRegistry", "stereotype": "contract",
        "x": 20, "y": 20,
        "attrs": [
            "+agentRegistry : string",
            "-_nextTokenId : uint256",
            "-_metadata : Map<uint256, Map<string, bytes>>",
        ],
        "methods": [
            "+register(agentId, agentType, agentURI, version, pricePerTask) : uint256",
            "+mintNewVersion(agentId, newURI, newVersion) : uint256",
            "+setAgentStatus(agentId, newStatus : AgentStatus)",
            "+setAgentWallet(agentId, newWallet, deadline, signature)",
            "+setPricePerTask(agentId, newPrice)",
            "+setMetadata(tokenId, key, value)",
            "+getAgent(agentId) : AgentIdentity",
            "+isActive(agentId) : bool",
            "+agentIdExists(agentId) : bool",
        ],
    },
    {
        "id": "ReputationRegistry", "stereotype": "contract",
        "x": 500, "y": 20,
        "attrs": [
            "+authorizedCallers : Map<address, bool>",
            "-_lastIndex : Map<uint256, Map<address, uint64>>",
            "-_clients : Map<uint256, address[]>",
        ],
        "methods": [
            "+initialize(identityRegistry_ : address)",
            "+setAuthorizedCaller(caller : address, authorized : bool)",
            "+giveFeedback(agentId, value, valueDecimals, tag1, tag2, ...)",
            "+recordFromValidation(agentId, taskId, score : uint8)",
            "+recordReputation(agentId, delta, isIncrease, reason)",
            "+revokeFeedback(agentId, feedbackIndex)",
            "+getSummary(agentId, clientAddresses[], ...) : (count, value, decimals)",
            "+readFeedback(agentId, clientAddress, feedbackIndex) : FeedbackData",
        ],
    },
    {
        "id": "EscrowManager", "stereotype": "contract",
        "x": 980, "y": 20,
        "attrs": [
            "+validationRegistry : address",
            "+identityRegistry : address",
            "+judgeFeePercentage : uint256",
            "+taskFunds : Map<string, uint256>",
            "+taskClients : Map<string, address>",
            "+taskAgent : Map<string, string>",
            "+isPipelineTask : Map<string, bool>",
            "-_pipelineWallets : Map<string, address[]>",
            "-_pipelineShares : Map<string, uint256[]>",
        ],
        "methods": [
            "+depositPayment(taskId, agentId) <<payable>>",
            "+depositPaymentPipeline(taskId, agentIds[], wallets[], shares_bps[]) <<payable>>",
            "+releaseFunds(taskId, provider, consensusJudges[])",
            "+releaseFundsPipeline(taskId, consensusJudges[])",
            "+refundClient(taskId)",
        ],
    },
    {
        "id": "StakingContract", "stereotype": "contract",
        "x": 500, "y": 820,
        "attrs": [
            "+validationRegistry : address",
            "+platformWallet : address",
        ],
        "methods": [
            "+stake() <<payable>>",
            "+withdraw()",
            "+lockStake(agent, duration)",
            "+unlockStake(agent)",
            "+slashProvider(agent) : uint256",
            "+slashJudge(agent) : uint256",
            "+isEligibleProvider(agent) : bool",
            "+isEligibleJudge(agent) : bool",
            "+isLocked(agent) : bool",
        ],
    },
    {
        "id": "ValidationRegistry", "stereotype": "contract",
        "x": 1460, "y": 20,
        "attrs": [
            "+_agentTotalScore : Map<string, uint256>",
            "+_agentScoreCount : Map<string, uint256>",
            "+judgeAgreements : Map<address, uint256>",
            "+judgeTotalVotes : Map<address, uint256>",
            "+judgeOnboarded : Map<string, bool>",
            "+judgeFlagged : Map<string, bool>",
            "+judgeHoneypotFails : Map<string, uint256>",
            "-_agentValidations : Map<uint256, bytes32[]>",
            "-_validatorRequests : Map<address, bytes32[]>",
        ],
        "methods": [
            "+validationRequest(taskId, providerAgentId, requestURI, requestHash, traceHash, mode)",
            "+assignJudges(taskId, candidates[])",
            "+commitVote(taskId, judgeId, commitHash)",
            "+revealVote(taskId, judgeId, vote, salt, taskCompletion, outputQuality, noFabrication, toolUsage)",
            "+finaliseValidation(taskId, justificationURI)",
            "+expireTask(taskId)",
            "+recordHoneypotResult(judgeId, passed, resultCID)",
            "+setJudgeOnboarded(judgeId)",
            "+isJudgeAuthorized(judgeId) : bool",
            "+getTask(taskId) : ValidationTask",
            "+getAgentScore(agentId) : (avgScore, totalTasks)",
            "+getValidationStatus(requestHash) : ValidationRecord",
        ],
    },
]

INTERFACES = [
    {
        "id": "IIdentityRegistry", "stereotype": "interface",
        "x": 500, "y": 480,
        "methods": [
            "+isActive(agentId : string) : bool",
            "+agentIdExists(agentId : string) : bool",
            "+getAgentWallet(agentId : string) : address",
            "+getAgentType(agentId : string) : uint8",
            "+getCurrentTokenId(agentId : string) : uint256",
            "+getPricePerTask(agentId : string) : uint256",
            "+ownerOf(tokenId : uint256) : address",
        ],
    },
    {
        "id": "IStakingContract", "stereotype": "interface",
        "x": 980, "y": 480,
        "methods": [
            "+isEligibleProvider(agent : address) : bool",
            "+isEligibleJudge(agent : address) : bool",
            "+isLocked(agent : address) : bool",
            "+lockStake(agent : address, duration : uint256)",
            "+unlockStake(agent : address)",
            "+slashProvider(agent : address) : uint256",
            "+slashJudge(agent : address) : uint256",
        ],
    },
    {
        "id": "IReputationRegistry", "stereotype": "interface",
        "x": 20, "y": 480,
        "methods": [
            "+recordFromValidation(agentId : string, taskId : string, score : uint8)",
            "+recordReputation(agentId : string, delta : uint256, isIncrease : bool, reason : string)",
        ],
    },
    {
        "id": "IEscrowManager", "stereotype": "interface",
        "x": 1460, "y": 480,
        "methods": [
            "+releaseFunds(taskId : string, provider : address, judges : address[])",
            "+releaseFundsPipeline(taskId : string, judges : address[])",
            "+refundClient(taskId : string)",
        ],
    },
]

STRUCTS = [
    {
        "id": "AgentIdentity", "stereotype": "struct",
        "x": 20, "y": 600,
        "attrs": [
            "+agentId : string",
            "+owner : address",
            "+agentWallet : address",
            "+createdAt : uint256",
            "+currentTokenId : uint256",
            "+tokenHistory : uint256[]",
            "+pricePerTask : uint256",
        ],
    },
    {
        "id": "AgentVersion", "stereotype": "struct",
        "x": 20, "y": 970,
        "attrs": [
            "+tokenId : uint256",
            "+agentURI : string",
            "+version : string",
            "+mintedAt : uint256",
            "+isCurrent : bool",
        ],
    },
    {
        "id": "FeedbackData", "stereotype": "struct",
        "x": 280, "y": 700,
        "attrs": [
            "+value : int128",
            "+valueDecimals : uint8",
            "+tag1 : string",
            "+tag2 : string",
            "+isRevoked : bool",
        ],
    },
    {
        "id": "StakeInfo", "stereotype": "struct",
        "x": 760, "y": 820,
        "attrs": [
            "+amount : uint256",
            "+lockedUntil : uint256",
            "+exists : bool",
        ],
    },
    {
        "id": "JudgeCommit", "stereotype": "struct",
        "x": 1460, "y": 700,
        "attrs": [
            "+commitHash : bytes32",
            "+taskCompletion : uint8",
            "+outputQuality : uint8",
            "+noFabrication : uint8",
            "+toolUsage : uint8",
            "+committed : bool",
            "+revealed : bool",
        ],
    },
    {
        "id": "ValidationTask", "stereotype": "struct",
        "x": 1700, "y": 700,
        "attrs": [
            "+taskId : string",
            "+providerAgentId : string",
            "+providerWallet : address",
            "+requestHash : bytes32",
            "+traceHash : bytes32",
            "+erc8004AgentId : uint256",
            "+createdAt : uint256",
            "+commitDeadline : uint256",
            "+revealDeadline : uint256",
            "+judgeIds : string[3]",
            "+judgeWallets : address[3]",
            "+finalResponse : uint8",
            "+finalTag : string",
            "+score : uint256",
            "+mode : uint8",
        ],
    },
    {
        "id": "ValidationRecord", "stereotype": "struct",
        "x": 1940, "y": 700,
        "attrs": [
            "+validatorAddress : address",
            "+agentId : uint256",
            "+response : uint8",
            "+responseHash : bytes32",
            "+tag : string",
            "+responseURI : string",
            "+lastUpdate : uint256",
        ],
    },
]

ENUMS = [
    {
        "id": "AgentType", "stereotype": "enumeration",
        "x": 20, "y": 1200,
        "values": ["PROVIDER", "JUDGE"],
    },
    {
        "id": "AgentStatus", "stereotype": "enumeration",
        "x": 220, "y": 1200,
        "values": ["ACTIVE", "SUSPENDED", "REVOKED"],
    },
    {
        "id": "TaskStatus", "stereotype": "enumeration",
        "x": 1700, "y": 1000,
        "values": ["PENDING", "COMMITTING", "REVEALING", "FINALISED", "EXPIRED"],
    },
    {
        "id": "InternalVote", "stereotype": "enumeration",
        "x": 1460, "y": 1000,
        "values": ["NONE", "VALID", "INVALID"],
    },
]

RELATIONS = [
    # Réalisation (implements) — tiret + triangle vide
    {"src": "IdentityRegistry",   "tgt": "IIdentityRegistry",   "type": "realize"},
    {"src": "StakingContract",    "tgt": "IStakingContract",    "type": "realize"},
    {"src": "ReputationRegistry", "tgt": "IReputationRegistry", "type": "realize"},
    {"src": "EscrowManager",      "tgt": "IEscrowManager",      "type": "realize"},
    # Dépendance (uses) — tiret + flèche
    {"src": "ValidationRegistry", "tgt": "IIdentityRegistry",   "type": "use", "label": "uses"},
    {"src": "ValidationRegistry", "tgt": "IStakingContract",    "type": "use", "label": "uses"},
    {"src": "ValidationRegistry", "tgt": "IReputationRegistry", "type": "use", "label": "uses"},
    {"src": "ValidationRegistry", "tgt": "IEscrowManager",      "type": "use", "label": "uses"},
    {"src": "ReputationRegistry", "tgt": "IIdentityRegistry",   "type": "use", "label": "uses"},
    {"src": "EscrowManager",      "tgt": "IIdentityRegistry",   "type": "use", "label": "uses"},
    # Composition — losange plein
    {"src": "IdentityRegistry",   "tgt": "AgentVersion",        "type": "compose", "label": "0..*"},
    {"src": "IdentityRegistry",   "tgt": "AgentIdentity",       "type": "compose", "label": "0..*"},
    {"src": "ReputationRegistry", "tgt": "FeedbackData",        "type": "compose", "label": "0..*"},
    {"src": "StakingContract",    "tgt": "StakeInfo",           "type": "compose", "label": "0..*"},
    {"src": "ValidationRegistry", "tgt": "JudgeCommit",         "type": "compose", "label": "0..*"},
    {"src": "ValidationRegistry", "tgt": "ValidationTask",      "type": "compose", "label": "0..*"},
    {"src": "ValidationRegistry", "tgt": "ValidationRecord",    "type": "compose", "label": "0..*"},
    # Agrégation — losange vide (enums dans structs)
    {"src": "AgentIdentity",  "tgt": "AgentType",    "type": "aggregate", "label": "agentType"},
    {"src": "AgentIdentity",  "tgt": "AgentStatus",  "type": "aggregate", "label": "status"},
    {"src": "JudgeCommit",    "tgt": "InternalVote", "type": "aggregate", "label": "vote"},
    {"src": "ValidationTask", "tgt": "TaskStatus",   "type": "aggregate", "label": "status"},
]

# ── Styles draw.io ───────────────────────────────────────────────────────────

HEADER_COLORS = {
    "contract":    "#dae8fc;strokeColor=#6c8ebf;",   # bleu
    "interface":   "#e1d5e7;strokeColor=#9673a6;",   # violet
    "struct":      "#d5e8d4;strokeColor=#82b366;",   # vert
    "enumeration": "#fff2cc;strokeColor=#d6b656;",   # jaune
}
BODY_COLOR = "fillColor=#ffffff;strokeColor=#d0d0d0;"

STYLE_HEADER   = "swimlane;fontStyle=1;align=center;startSize=40;arcSize=0;"
STYLE_ATTR     = "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=8;spacingRight=4;overflow=hidden;"
STYLE_SEP      = "line;strokeColor=#d0d0d0;fillColor=none;"
STYLE_REALIZE  = "endArrow=block;endFill=0;dashed=1;exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
STYLE_USE      = "endArrow=open;dashed=1;exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
STYLE_COMPOSE  = "endArrow=ERmany;startArrow=ERmandOne;dashed=0;endFill=1;startFill=1;"
STYLE_AGGREGATE= "endArrow=open;startArrow=ERmanyToOne;dashed=0;"

ROW_H   = 22
PAD_TOP = 40
W       = 340

# ── Helpers ──────────────────────────────────────────────────────────────────

uid_counter = [10]
def uid():
    uid_counter[0] += 1
    return str(uid_counter[0])

def cell(parent, cid, value, style, vertex=True, x=0, y=0, w=0, h=0,
         source=None, target=None, edge=False):
    c = ET.SubElement(parent, "mxCell",
                      id=cid, value=value, style=style,
                      vertex=("1" if vertex else "0"),
                      edge=("1" if edge else "0"),
                      parent="1")
    if source: c.set("source", source)
    if target: c.set("target", target)
    geo = ET.SubElement(c, "mxGeometry", **{"as": "geometry"})
    if vertex:
        geo.set("x", str(x)); geo.set("y", str(y))
        geo.set("width", str(w)); geo.set("height", str(h))
    if edge:
        geo.set("relative", "1")
    return c

def class_block(root, item, kind):
    """Génère un bloc classe/interface/struct/enum dans draw.io."""
    cid   = item["id"]
    x, y  = item["x"], item["y"]
    color = HEADER_COLORS[kind]

    rows   = item.get("attrs", []) + item.get("methods", []) + item.get("values", [])
    has_sep = bool(item.get("attrs")) and bool(item.get("methods"))
    height = PAD_TOP + len(rows) * ROW_H + (ROW_H if has_sep else 0) + 10

    # Conteneur principal
    style = STYLE_HEADER + f"fillColor={color}fontStyle=1;"
    cell(root, cid, f"«{kind}»\\n{cid}", style, x=x, y=y, w=W, h=height)

    cy = PAD_TOP + 4
    # Attributs
    for a in item.get("attrs", []):
        cell(root, uid(), a, STYLE_ATTR + BODY_COLOR,
             x=x, y=y+cy, w=W, h=ROW_H)
        cy += ROW_H

    # Séparateur
    if has_sep:
        cell(root, uid(), "", STYLE_SEP, x=x, y=y+cy, w=W, h=2)
        cy += ROW_H

    # Méthodes / valeurs enum
    for m in item.get("methods", []) + item.get("values", []):
        cell(root, uid(), m, STYLE_ATTR + BODY_COLOR,
             x=x, y=y+cy, w=W, h=ROW_H)
        cy += ROW_H

    return cid

# ── Construction du XML ───────────────────────────────────────────────────────

model  = ET.Element("mxGraphModel", dx="1422", dy="762", grid="1",
                    gridSize="10", guides="1", tooltips="1",
                    connect="1", arrows="1", fold="1", page="1",
                    pageScale="1", pageWidth="2800", pageHeight="2000",
                    math="0", shadow="0")
root_e = ET.SubElement(model, "root")
ET.SubElement(root_e, "mxCell", id="0")
ET.SubElement(root_e, "mxCell", id="1", parent="0")

ids = {}
for c in CONTRACTS:  ids[c["id"]] = class_block(root_e, c, "contract")
for i in INTERFACES: ids[i["id"]] = class_block(root_e, i, "interface")
for s in STRUCTS:    ids[s["id"]] = class_block(root_e, s, "struct")
for e in ENUMS:      ids[e["id"]] = class_block(root_e, e, "enumeration")

# Relations
REL_STYLES = {
    "realize":   "endArrow=block;endFill=0;dashed=1;edgeStyle=orthogonalEdgeStyle;",
    "use":       "endArrow=open;dashed=1;edgeStyle=orthogonalEdgeStyle;",
    "compose":   "endArrow=ERmany;startArrow=ERmandOne;dashed=0;edgeStyle=orthogonalEdgeStyle;startFill=1;endFill=0;",
    "aggregate": "endArrow=open;startArrow=ERmanyToOne;dashed=0;edgeStyle=orthogonalEdgeStyle;startFill=0;",
}
for r in RELATIONS:
    rid   = uid()
    label = r.get("label", "")
    style = REL_STYLES[r["type"]]
    c = ET.SubElement(root_e, "mxCell",
                      id=rid, value=label, style=style,
                      edge="1", source=r["src"], target=r["tgt"], parent="1")
    ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})

# Note OZ
note_style = "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;fontSize=11;fillColor=#fff9c4;strokeColor=#d6b656;"
cell(root_e, uid(),
     "<b>Héritage OpenZeppelin</b><br/>"
     "IdentityRegistry → ERC721URIStorage, Ownable, EIP712<br/>"
     "ReputationRegistry → Ownable<br/>"
     "EscrowManager → Ownable, ReentrancyGuard<br/>"
     "StakingContract → Ownable, ReentrancyGuard<br/>"
     "ValidationRegistry → Ownable, ReentrancyGuard",
     note_style, x=500, y=1200, w=400, h=120)

# ── Écriture du fichier ──────────────────────────────────────────────────────

tree = ET.ElementTree(model)
ET.indent(tree, space="  ")
out = "c:\\Users\\Roua\\Desktop\\AI_AgentsMarketPlace\\blockchain\\uml\\class-diagram.drawio"
tree.write(out, encoding="utf-8", xml_declaration=True)
print(f"Généré : {out}")
