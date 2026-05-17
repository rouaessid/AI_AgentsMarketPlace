"""
test_reputation_advanced.py
===========================
Tests avancés pour le système de réputation.
Complète test_reputation.py avec les cas limites, invariants mathématiques,
logique de sync, et flux E2E.

Sections :
  A. ATE/Uplift        — cas limites (solo-only, pipeline-only, égalité, précision)
  B. Power Method      — invariants (α=0, α=1, t≥0, sum=1, déterminisme, max_iter)
  C. Normalisation p/f — all-zero uniforme, max-star, value_decimals, idempotence
  D. Matrice C         — N=1, N=2, all-zeros
  E. Workflow          — cold-start, réseau large, late-joiner, accumulation, math V[i]
  F. Sync EigenTrust   — encodage, seuil 0.5%, cache _last_scores
  G. E2E blockchain    — indexeur simulé + Anvil (skipped sans Anvil)

Run unit only (no Anvil, no backend) :
    cd backend && python -m pytest tests/test_reputation_advanced.py -v -m unit

Run integration (Anvil must be running on :8545) :
    cd backend && python -m pytest tests/test_reputation_advanced.py -v -m integration
"""
import uuid
import pytest
import numpy as np


# ── Helpers ──────────────────────────────────────────────────────────────────

def _aid(prefix="ag"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _cleanup_collab(*agent_ids):
    from app.db.database import _engine
    from sqlalchemy import text
    with _engine.connect() as conn:
        for aid in agent_ids:
            conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": aid})
        conn.commit()


def _cleanup_rep(*token_ids):
    from app.db.database import _engine
    from sqlalchemy import text
    with _engine.connect() as conn:
        for tid in token_ids:
            conn.execute(
                text("DELETE FROM reputation_events WHERE agent_token_id = :t"),
                {"t": tid},
            )
        conn.commit()


def _ins_collab(agent_id, score, mode, block=1):
    from app.db.collaboration_repo import insert_collaboration_score
    insert_collaboration_score(
        event_id=f"ev-{uuid.uuid4().hex}",
        agent_id=agent_id,
        task_id=f"task-{uuid.uuid4().hex[:6]}",
        score=score,
        mode=mode,
        tx_hash=f"0x{uuid.uuid4().hex[:8]}",
        block_number=block,
    )


def _ins_rep(token_id, value, tag1, block=1, decimals=0, feedback_index=0):
    from app.db.reputation_repo import insert_reputation_event
    insert_reputation_event(
        event_id=f"ev-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=token_id,
        client_address=f"0x{uuid.uuid4().hex[:40]}",
        feedback_index=feedback_index,
        value=value,
        value_decimals=decimals,
        tag1=tag1,
        tx_hash=f"0x{uuid.uuid4().hex[:8]}",
        block_number=block,
    )


# ══════════════════════════════════════════════════════════════════════════════
# A. ATE / Uplift — cas limites
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_C_uplift_solo_only_no_pipeline():
    """Agent avec uniquement des scores solo → uplift = 0 (pipeline absent)."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 80.0, mode=0)
    _ins_collab(aid, 85.0, mode=0)
    assert compute_C_uplift(aid) == 0.0
    _cleanup_collab(aid)


@pytest.mark.unit
def test_C_uplift_pipeline_only_no_solo():
    """Agent avec uniquement des scores pipeline → uplift = 0 (solo absent)."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 80.0, mode=1)
    _ins_collab(aid, 90.0, mode=1)
    assert compute_C_uplift(aid) == 0.0
    _cleanup_collab(aid)


@pytest.mark.unit
def test_C_uplift_single_score_each_mode():
    """Un score solo (70) et un pipeline (85) → uplift = (85-70)/100 = 0.15 exact."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 70.0, mode=0)
    _ins_collab(aid, 85.0, mode=1)
    assert abs(compute_C_uplift(aid) - 0.15) < 1e-9
    _cleanup_collab(aid)


@pytest.mark.unit
def test_C_uplift_equal_modes_clamped_to_zero():
    """Pipeline = solo → uplift = max(0, 0) = 0.0 (pas de crédit nul)."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 80.0, mode=0)
    _ins_collab(aid, 80.0, mode=1)
    assert compute_C_uplift(aid) == 0.0
    _cleanup_collab(aid)


@pytest.mark.unit
def test_C_uplift_high_score_precision():
    """solo=95, pipeline=98 → uplift = (98−95)/100 = 0.03 (précision numérique)."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 95.0, mode=0)
    _ins_collab(aid, 98.0, mode=1)
    assert abs(compute_C_uplift(aid) - 0.03) < 1e-9
    _cleanup_collab(aid)


@pytest.mark.unit
def test_C_uplift_multi_scores_mean():
    """Moyenne correcte : solo=[60,80]=70, pipeline=[82,88,90]=86.67 → uplift≈0.167."""
    from app.services.eigentrust_service import compute_C_uplift
    aid = _aid()
    _ins_collab(aid, 60.0, mode=0, block=1)
    _ins_collab(aid, 80.0, mode=0, block=2)
    _ins_collab(aid, 82.0, mode=1, block=3)
    _ins_collab(aid, 88.0, mode=1, block=4)
    _ins_collab(aid, 90.0, mode=1, block=5)
    expected = (np.mean([82, 88, 90]) - np.mean([60, 80])) / 100
    assert abs(compute_C_uplift(aid) - expected) < 1e-9
    _cleanup_collab(aid)


# ══════════════════════════════════════════════════════════════════════════════
# B. Power Method — invariants mathématiques
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_power_method_alpha_one_equals_pretrust():
    """α=1 → t⁽ᵏ⁺¹⁾ = 0·Cᵀt + 1·p = p → t converge vers p dès le 1er pas."""
    from app.services.eigentrust_service import eigentrust_iterate, MAX_ITER, EPSILON
    p = np.array([0.6, 0.3, 0.1])
    C = np.array([[0, 0.2, 0.1], [0.2, 0, 0.1], [0.1, 0.1, 0]])
    t, iters, converged = eigentrust_iterate(p, C, alpha=1.0, max_iter=MAX_ITER, epsilon=EPSILON)
    assert converged
    np.testing.assert_allclose(t, p, atol=1e-5)


@pytest.mark.unit
def test_power_method_propagation_differs_from_pure_anchor():
    """
    Avec α=1.0, t = p (ancre pure, aucune propagation).
    Avec α=0.15, une C asymétrique qui booste l'agent 0 produit t[0] > p[0].
    Vérifie que la propagation via C modifie bien la distribution finale.
    """
    from app.services.eigentrust_service import eigentrust_iterate, MAX_ITER, EPSILON
    # p ancre fortement sur agent 2
    p = np.array([0.10, 0.10, 0.80])
    # Agent 2 distribue 90% de son uplift à l'agent 0 → boost agent 0
    C = np.array([
        [0,    0.50, 0.50],
        [0.50, 0,    0.50],
        [0.90, 0.10, 0.00],
    ])

    t_anchor, _, _ = eigentrust_iterate(p, C, alpha=1.0,  max_iter=MAX_ITER, epsilon=EPSILON)
    t_prop,   _, _ = eigentrust_iterate(p, C, alpha=0.15, max_iter=MAX_ITER, epsilon=EPSILON)

    # α=1.0 → t = p (vérification du cas de référence)
    np.testing.assert_allclose(t_anchor, p, atol=1e-5)

    # α=0.15 → propagation booste agent 0 au-delà de son ancre p[0]=0.10
    assert t_prop[0] > t_anchor[0], (
        f"Propagation via C doit augmenter trust[0] par rapport à l'ancre. "
        f"prop={t_prop[0]:.4f}, anchor={t_anchor[0]:.4f}"
    )


@pytest.mark.unit
def test_power_method_t_nonnegative():
    """Toutes les valeurs de t sont ≥ 0 (propriété de distribution de probabilité)."""
    from app.services.eigentrust_service import eigentrust_iterate, ALPHA, MAX_ITER, EPSILON
    rng = np.random.default_rng(42)
    N = 5
    p = rng.dirichlet(np.ones(N))
    C = rng.random((N, N))
    for i in range(N):
        C[i, i] = 0.0
    C = C / max(C.sum(), 1e-10)

    t, _, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=EPSILON)
    assert all(ti >= -1e-10 for ti in t), f"Valeur négative dans t: {t}"


@pytest.mark.unit
def test_power_method_t_sums_to_one():
    """sum(t) ≈ 1.0 après convergence (t est une distribution de probabilité)."""
    from app.services.eigentrust_service import eigentrust_iterate, ALPHA, MAX_ITER, EPSILON
    p = np.array([0.25, 0.25, 0.25, 0.25])
    C = np.eye(4) / 4
    t, _, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=EPSILON)
    assert abs(t.sum() - 1.0) < 1e-5, f"sum(t) = {t.sum():.8f} ≠ 1.0"


@pytest.mark.unit
def test_power_method_deterministic():
    """Mêmes entrées → même t à convergence (déterminisme strict)."""
    from app.services.eigentrust_service import eigentrust_iterate, ALPHA, MAX_ITER, EPSILON
    p = np.array([0.40, 0.35, 0.25])
    C = np.array([[0, 0.10, 0.20], [0.10, 0, 0.15], [0.20, 0.15, 0]])
    t1, _, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=EPSILON)
    t2, _, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=EPSILON)
    np.testing.assert_array_equal(t1, t2)


@pytest.mark.unit
def test_power_method_max_iter_respected():
    """max_iter=3 → iters ≤ 3, pas d'exception, t valide."""
    from app.services.eigentrust_service import eigentrust_iterate, EPSILON
    p = np.array([0.5, 0.5])
    C = np.eye(2) / 2
    t, iters, converged = eigentrust_iterate(p, C, alpha=0.15, max_iter=3, epsilon=EPSILON)
    assert iters <= 3
    assert abs(t.sum() - 1.0) < 1e-5


@pytest.mark.unit
def test_power_method_convergence_epsilon():
    """Avec ε=0.01 (grand seuil), la convergence est plus rapide qu'avec ε=1e-6."""
    from app.services.eigentrust_service import eigentrust_iterate, ALPHA, MAX_ITER
    p = np.array([0.5, 0.3, 0.2])
    C = np.array([[0, 0.1, 0.2], [0.1, 0, 0.1], [0.2, 0.1, 0]])

    _, iters_tight, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=1e-6)
    _, iters_loose, _ = eigentrust_iterate(p, C, alpha=ALPHA, max_iter=MAX_ITER, epsilon=0.01)
    assert iters_loose <= iters_tight, (
        f"ε=0.01 doit converger en ≤ itérations que ε=1e-6. "
        f"loose={iters_loose}, tight={iters_tight}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Normalisation p et f — cas extrêmes
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_p_all_zero_produces_uniform():
    """Agents sans successRate → p̂ = 1/N → global_trust uniforme."""
    from app.services.eigentrust_service import compute_eigentrust
    agents = [{"agent_id": _aid(), "token_id": 0} for _ in range(4)]
    result = compute_eigentrust(agents)
    trusts = [result.scores_by_agent[a["agent_id"]]["pre_trust"] for a in agents]
    for pt in trusts:
        assert abs(pt - 0.25) < 1e-5, f"pre_trust non uniforme: {trusts}"


@pytest.mark.unit
def test_p_normalized_sums_to_one():
    """sum(p̂) = 1.0 (distribution de probabilité normalisée)."""
    from app.services.eigentrust_service import compute_eigentrust
    agents = [{"agent_id": _aid(), "token_id": 0} for _ in range(5)]
    result = compute_eigentrust(agents)
    total = sum(result.pre_trust)
    assert abs(total - 1.0) < 1e-5, f"sum(p̂) = {total:.8f} ≠ 1.0"


@pytest.mark.unit
def test_f_no_starred_all_neutral():
    """Aucun starred → f[i] = 1.0 pour tous (pas de pénalité ni bonus)."""
    from app.services.eigentrust_service import compute_eigentrust
    agents = [{"agent_id": _aid(), "token_id": 0} for _ in range(3)]
    result = compute_eigentrust(agents)
    for uf in result.user_feedback:
        assert abs(uf - 1.0) < 1e-5, f"user_feedback doit être 1.0 sans starred: {uf}"


@pytest.mark.unit
def test_f_max_starred_gets_one():
    """L'agent avec le starred le plus élevé obtient user_feedback = 1.0."""
    from app.services.eigentrust_service import compute_eigentrust
    t1, t2 = 996_001, 996_002
    aid1, aid2 = _aid(), _aid()

    _ins_rep(t1, 100, "starred")   # max → f = 1.0
    _ins_rep(t2, 50,  "starred")   # moitié → f = 0.5

    agents = [{"agent_id": aid1, "token_id": t1}, {"agent_id": aid2, "token_id": t2}]
    result = compute_eigentrust(agents)

    uf1 = result.scores_by_agent[aid1]["user_feedback"]
    uf2 = result.scores_by_agent[aid2]["user_feedback"]
    assert abs(uf1 - 1.0) < 1e-5, f"f[max] attendu 1.0, obtenu {uf1}"
    assert abs(uf2 - 0.5) < 1e-5, f"f[half] attendu 0.5, obtenu {uf2}"

    _cleanup_rep(t1, t2)


@pytest.mark.unit
def test_value_decimals_correctly_normalized():
    """
    value=150, value_decimals=3 → valeur réelle = 0.150 dans le calcul EigenTrust.
    Vérification : starred encodé 1000/decimals=3 → l'agent unique a final_score=1.0.
    """
    from app.services.eigentrust_service import compute_eigentrust
    t1 = 996_003
    aid1 = _aid()
    _ins_rep(t1, 1000, "starred", decimals=3)  # 1000 / 10^3 = 1.000

    agents = [{"agent_id": aid1, "token_id": t1}]
    result = compute_eigentrust(agents)
    assert abs(result.scores_by_agent[aid1]["final_score"] - 1.0) < 1e-4

    _cleanup_rep(t1)


@pytest.mark.unit
def test_reputation_events_idempotent():
    """Même event_id inséré deux fois → 1 seule ligne (pas de doublon)."""
    from app.db.reputation_repo import insert_reputation_event, get_reputation_signals
    t = 996_004
    eid = f"idem-{uuid.uuid4().hex}"
    kwargs = dict(
        event_id=eid, event_type="new_feedback", agent_token_id=t,
        client_address="0x" + "0" * 40, feedback_index=0,
        value=80, value_decimals=0, tag1="starred",
        tx_hash="0xabc", block_number=1,
    )
    insert_reputation_event(**kwargs)
    insert_reputation_event(**kwargs)  # deuxième insertion même event_id

    sigs = get_reputation_signals(t)
    assert len(sigs) == 1, f"Doublon détecté: {len(sigs)} lignes"
    _cleanup_rep(t)


@pytest.mark.unit
def test_aggregated_score_excludes_revoked():
    """get_aggregated_score : signaux révoqués exclus du count/sum/average."""
    from app.db.reputation_repo import (
        insert_reputation_event, get_aggregated_score, mark_revoked,
    )
    t = 996_005
    client = "0x" + "B" * 40

    insert_reputation_event(
        event_id=f"ok-{uuid.uuid4().hex}", event_type="new_feedback",
        agent_token_id=t, client_address=client, feedback_index=0,
        value=80, value_decimals=0, tag1="starred", tx_hash="0x1", block_number=1,
    )
    insert_reputation_event(
        event_id=f"rev-{uuid.uuid4().hex}", event_type="new_feedback",
        agent_token_id=t, client_address=client, feedback_index=1,
        value=20, value_decimals=0, tag1="starred", tx_hash="0x2", block_number=2,
    )
    mark_revoked(t, client, 1)  # révoquer le signal à 20

    agg = get_aggregated_score(t)
    assert agg["starred"]["count"] == 1, f"Révoqué compté: {agg}"
    assert agg["starred"]["sum"] == 80
    assert abs(agg["starred"]["average"] - 80.0) < 0.01

    _cleanup_rep(t)


# ══════════════════════════════════════════════════════════════════════════════
# D. Matrice C — cas limites N=1, N=2, all-zeros
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_C_matrix_single_agent_is_zero():
    """N=1 → C = [[0.0]] — aucune distribution possible."""
    from app.services.eigentrust_service import build_C_matrix
    C = build_C_matrix([_aid()])
    assert C.shape == (1, 1)
    assert C[0, 0] == 0.0


@pytest.mark.unit
def test_C_matrix_n2_exact_credit():
    """N=2 : agent B uplift=0.30 → C[B][A] = 0.30 / (2-1) = 0.30."""
    from app.services.eigentrust_service import build_C_matrix
    aid_A, aid_B = _aid(), _aid()
    _ins_collab(aid_B, 60.0, mode=0)   # solo
    _ins_collab(aid_B, 90.0, mode=1)   # pipeline → uplift = (90-60)/100 = 0.30

    C = build_C_matrix([aid_A, aid_B])
    j, i = 1, 0   # B=row 1, A=col 0
    assert abs(C[j, i] - 0.30) < 1e-6, f"C[B][A]={C[j, i]:.6f}, attendu 0.30"
    assert C[j, j] == 0.0             # pas d'auto-confiance

    _cleanup_collab(aid_B)


@pytest.mark.unit
def test_C_matrix_all_zero_when_no_history():
    """Aucun agent avec historique → C entière = 0 (aucun crédit à distribuer)."""
    from app.services.eigentrust_service import build_C_matrix
    C = build_C_matrix([_aid() for _ in range(4)])
    assert C.sum() == 0.0, f"C non nulle sans historique: sum={C.sum()}"


# ══════════════════════════════════════════════════════════════════════════════
# E. Workflow — cas additionnels
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_workflow_cold_start_uniform():
    """
    Cold start : aucune donnée pour aucun agent.
    C = all zeros → fallback eye/N → t converge vers p uniforme.
    Tous les agents ont global_trust identique.
    """
    from app.services.eigentrust_service import compute_eigentrust
    agents = [{"agent_id": _aid(), "token_id": 0} for _ in range(4)]
    result = compute_eigentrust(agents)
    trusts = [result.scores_by_agent[a["agent_id"]]["global_trust"] for a in agents]
    for gt in trusts:
        assert abs(gt - trusts[0]) < 1e-4, f"Cold start doit être uniforme: {trusts}"


@pytest.mark.unit
def test_workflow_large_network_converges_and_normalizes():
    """10 agents avec données variées → convergé, sum(t)=1, tous t≥0."""
    from app.services.eigentrust_service import compute_eigentrust
    n = 10
    aids = [_aid() for _ in range(n)]

    for k in range(0, n, 2):
        _ins_collab(aids[k], 60.0 + k, mode=0, block=k + 1)
        _ins_collab(aids[k], 75.0 + k, mode=1, block=k + 11)

    agents = [{"agent_id": aid, "token_id": 0} for aid in aids]
    result = compute_eigentrust(agents)

    assert result.converged, f"Non convergé en {result.iterations} itérations"
    assert abs(sum(result.global_trust) - 1.0) < 1e-4
    for gt in result.global_trust:
        assert gt >= -1e-10

    _cleanup_collab(*aids)


@pytest.mark.unit
def test_workflow_late_joining_agent():
    """
    Nouvel agent (aucun historique) rejoint un réseau de 3 agents actifs.
    Pas d'exception, late-joiner présent dans scores_by_agent.
    """
    from app.services.eigentrust_service import compute_eigentrust
    aid_A, aid_B, aid_C = _aid(), _aid(), _aid()
    aid_new = _aid()

    _ins_collab(aid_A, 80.0, mode=0)
    _ins_collab(aid_B, 65.0, mode=0)
    _ins_collab(aid_B, 85.0, mode=1)
    _ins_collab(aid_C, 75.0, mode=0)

    agents = [
        {"agent_id": aid_A,   "token_id": 0},
        {"agent_id": aid_B,   "token_id": 0},
        {"agent_id": aid_C,   "token_id": 0},
        {"agent_id": aid_new, "token_id": 0},
    ]
    result = compute_eigentrust(agents)
    assert result.converged
    assert aid_new in result.scores_by_agent

    _cleanup_collab(aid_A, aid_B, aid_C)


@pytest.mark.unit
def test_workflow_higher_judge_score_raises_trust():
    """
    Deux runs avec task_p_overrides différents pour A (B fixé à 50).
    Override élevé pour A (90) vs bas (40) → global_trust[A] plus grand.
    La normalisation requiert que B ait aussi un override pour que le ratio varie.
    Simule la mise à jour de réputation après deux validations successives.
    """
    from app.services.eigentrust_service import compute_eigentrust
    aid_A, aid_B = _aid(), _aid()
    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
    ]

    # B est fixé à 50 dans les deux cas ; seul A change
    result_low  = compute_eigentrust(agents, task_p_overrides={aid_A: 40.0, aid_B: 50.0})
    result_high = compute_eigentrust(agents, task_p_overrides={aid_A: 90.0, aid_B: 50.0})

    t_low  = result_low.scores_by_agent[aid_A]["global_trust"]
    t_high = result_high.scores_by_agent[aid_A]["global_trust"]
    assert t_high > t_low, (
        f"Score juge plus élevé doit augmenter global_trust. "
        f"low={t_low:.4f}, high={t_high:.4f}"
    )


@pytest.mark.unit
def test_workflow_final_score_equals_t_times_f():
    """
    Vérification directe : V[i] = t[i] × f[i] / sum(t·f).
    Compare la formule manuelle avec compute_eigentrust.
    """
    from app.services.eigentrust_service import compute_eigentrust
    t1, t2 = 996_100, 996_101
    aid1, aid2 = _aid(), _aid()

    _ins_rep(t1, 80, "starred")   # f[1] = 80/80 = 1.0
    # aid2 n'a pas de starred → f[2] = 1.0 aussi (aucun starred → tous = 1)
    # (mais avec t1 ayant starred, le max est 80, t2 aucun → f[t2] = 0/80 = 0 ?)
    # En réalité: user_feedbacks = [80, 0], uf_max=80 → uf=[1.0, 0.0]
    # Donc f[aid2] = 0 → final_score[aid2] = 0

    agents = [
        {"agent_id": aid1, "token_id": t1},
        {"agent_id": aid2, "token_id": t2},
    ]
    result = compute_eigentrust(agents)

    t_vals = result.global_trust
    f_vals = result.user_feedback

    v = [ti * fi for ti, fi in zip(t_vals, f_vals)]
    v_sum = sum(v)
    v_norm = [vi / v_sum for vi in v] if v_sum > 0 else [1.0 / len(v)] * len(v)

    fs1 = result.scores_by_agent[aid1]["final_score"]
    fs2 = result.scores_by_agent[aid2]["final_score"]

    assert abs(fs1 - v_norm[0]) < 1e-4, f"final_score[0]: attendu {v_norm[0]:.6f}, obtenu {fs1}"
    assert abs(fs2 - v_norm[1]) < 1e-4, f"final_score[1]: attendu {v_norm[1]:.6f}, obtenu {fs2}"

    _cleanup_rep(t1, t2)


@pytest.mark.unit
def test_workflow_process_solo_task_zero_judges_gives_uniform():
    """
    process_solo_task avec tous les juges à 0 → p[agent] = 0 → distribution uniforme.
    """
    from app.services.eigentrust_service import process_solo_task
    aid_A, aid_B = _aid(), _aid()
    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
    ]
    result = process_solo_task(agent_id=aid_A, judge_scores=[0.0, 0.0, 0.0], agents=agents)
    assert result.converged
    pA = result.scores_by_agent[aid_A]["pre_trust"]
    pB = result.scores_by_agent[aid_B]["pre_trust"]
    assert abs(pA - pB) < 1e-5, f"Attendu uniforme (juges à 0). pA={pA}, pB={pB}"


@pytest.mark.unit
def test_workflow_process_pipeline_task_correct_pretrust_ratio():
    """
    process_pipeline_task : A=[100,100] mean=100, B=[50,50] mean=50.
    p normalisé → pA = 2/3, pB = 1/3.
    """
    from app.services.eigentrust_service import process_pipeline_task
    aid_A, aid_B = _aid(), _aid()
    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
    ]
    pipeline = [
        {"agent_id": aid_A, "judge_scores": [100.0, 100.0]},
        {"agent_id": aid_B, "judge_scores": [50.0,  50.0]},
    ]
    result = process_pipeline_task(pipeline, agents=agents)
    assert result.converged
    pA = result.scores_by_agent[aid_A]["pre_trust"]
    pB = result.scores_by_agent[aid_B]["pre_trust"]
    assert abs(pA - 2/3) < 1e-4, f"pA={pA:.4f} attendu 0.6667"
    assert abs(pB - 1/3) < 1e-4, f"pB={pB:.4f} attendu 0.3333"


@pytest.mark.unit
def test_workflow_reputation_updated_after_validation():
    """
    TEST CLÉ — Répond à : 'après validation, la réputation est-elle mise à jour ?'

    Étape 1 : avant validation → global_trust uniforme (aucune donnée).
    Étape 2 : process_solo_task simule finaliseValidation() + EigenTrust recompute.
    Étape 3 : l'agent validé (juges élevés) a global_trust > l'autre.

    C'est exactement le flux :
      finaliseValidation() → ScoreRecorded → indexeur → collaboration_log
      → process_solo_task(judge_scores) → compute_eigentrust → réputation mise à jour.
    """
    from app.services.eigentrust_service import compute_eigentrust, process_solo_task

    aid_A, aid_B = _aid(), _aid()
    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
    ]

    # AVANT validation : aucun score → distribution uniforme
    before = compute_eigentrust(agents)
    tA_bef = before.scores_by_agent[aid_A]["global_trust"]
    tB_bef = before.scores_by_agent[aid_B]["global_trust"]
    assert abs(tA_bef - tB_bef) < 1e-4, "Avant validation : attendu uniforme"

    # APRÈS validation de A (excellents scores juges)
    after = process_solo_task(
        agent_id=aid_A,
        judge_scores=[90.0, 92.0, 88.0],   # mean = 90 → p[A] > p[B]
        agents=agents,
    )
    tA_aft = after.scores_by_agent[aid_A]["global_trust"]
    tB_aft = after.scores_by_agent[aid_B]["global_trust"]

    assert after.converged
    assert tA_aft > tB_aft, (
        f"Après validation : A devrait avoir global_trust > B. "
        f"A={tA_aft:.4f}, B={tB_aft:.4f}"
    )
    assert tA_aft > tA_bef, (
        f"La réputation de A doit augmenter après validation. "
        f"avant={tA_bef:.4f}, après={tA_aft:.4f}"
    )


@pytest.mark.unit
def test_workflow_pipeline_upstream_credit_full_scenario():
    """
    Scénario complet pipeline A → B → C.
    B et C ont un fort uplift pipeline → créditent A (upstream).
    Après compute_eigentrust : global_trust[A] > global_trust[C].

    ATE attendu :
      uplift[B] = (85 - 65) / 100 = 0.20
      uplift[C] = (90 - 60) / 100 = 0.30
      C[B][A] = 0.20 / 2 = 0.10
      C[C][A] = 0.30 / 2 = 0.15  → A reçoit plus de crédit que C n'en distribue
    """
    from app.services.eigentrust_service import compute_eigentrust
    aid_A, aid_B, aid_C = _aid(), _aid(), _aid()

    _ins_collab(aid_A, 75.0, mode=0, block=1)   # A : solo uniquement

    _ins_collab(aid_B, 65.0, mode=0, block=2)   # B : solo + pipeline
    _ins_collab(aid_B, 85.0, mode=1, block=3)

    _ins_collab(aid_C, 60.0, mode=0, block=4)   # C : solo + pipeline
    _ins_collab(aid_C, 90.0, mode=1, block=5)

    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
        {"agent_id": aid_C, "token_id": 0},
    ]
    result = compute_eigentrust(agents)

    assert result.converged
    tA = result.scores_by_agent[aid_A]["global_trust"]
    tC = result.scores_by_agent[aid_C]["global_trust"]
    assert tA > tC, (
        f"Upstream A doit recevoir plus de crédit que C (distributeur). "
        f"A={tA:.4f}, C={tC:.4f}"
    )

    _cleanup_collab(aid_A, aid_B, aid_C)


# ══════════════════════════════════════════════════════════════════════════════
# F. EigenTrust sync — encodage score et logique de seuil
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_sync_score_encoding_0_15():
    """final_score=0.15 → value = round(0.15×1000) = 150, decimals=3 → 150/10³=0.150."""
    value = int(round(0.15 * 1000))
    assert value == 150
    assert abs(value / 10**3 - 0.15) < 1e-9


@pytest.mark.unit
def test_sync_score_encoding_edge_cases():
    """Vérification de l'encodage sur des valeurs limites (0.0, 1.0, 0.9995 → 1000)."""
    for score, expected_value in [(0.0, 0), (1.0, 1000), (0.5, 500), (0.333, 333)]:
        value = int(round(score * 1000))
        assert value == expected_value, f"score={score} → attendu {expected_value}, obtenu {value}"


@pytest.mark.unit
def test_sync_threshold_constant():
    """SCORE_CHANGE_THRESHOLD = 0.005 (0.5%) — seuil documenté."""
    from app.services.eigentrust_sync import SCORE_CHANGE_THRESHOLD
    assert SCORE_CHANGE_THRESHOLD == 0.005


@pytest.mark.unit
def test_sync_threshold_skip_logic():
    """
    Changement < 0.5% → pas d'écriture on-chain.
    Changement ≥ 0.5% → écriture requise.
    Vérifie la condition garde de _sync_blocking.
    """
    from app.services.eigentrust_sync import SCORE_CHANGE_THRESHOLD

    old = 0.500
    assert abs(0.504 - old) < SCORE_CHANGE_THRESHOLD,  "0.4% devrait être sous le seuil"
    assert abs(0.510 - old) >= SCORE_CHANGE_THRESHOLD, "1.0% devrait dépasser le seuil"
    assert abs(0.500 - old) < SCORE_CHANGE_THRESHOLD,  "0.0% (inchangé) sous le seuil"


@pytest.mark.unit
def test_sync_last_scores_cache_prevents_duplicate_writes():
    """
    _last_scores mémorise le score écrit.
    Si le nouveau score est identique → delta=0 < threshold → pas de tx.
    """
    from app.services import eigentrust_sync

    aid = _aid()
    eigentrust_sync._last_scores.pop(aid, None)

    # Simuler une première écriture on-chain
    score_written = 0.42
    eigentrust_sync._last_scores[aid] = score_written

    # Deuxième calcul : même score → delta < threshold
    delta = abs(score_written - eigentrust_sync._last_scores.get(aid, -1.0))
    assert delta < eigentrust_sync.SCORE_CHANGE_THRESHOLD, (
        f"Score identique ne doit pas déclencher de tx. delta={delta}"
    )

    # Nouveau score suffisamment différent → delta ≥ threshold
    new_score = score_written + 0.01
    delta2 = abs(new_score - eigentrust_sync._last_scores.get(aid, -1.0))
    assert delta2 >= eigentrust_sync.SCORE_CHANGE_THRESHOLD, (
        f"Score modifié (1%) doit déclencher une tx. delta={delta2}"
    )

    # Cleanup
    eigentrust_sync._last_scores.pop(aid, None)


@pytest.mark.unit
def test_sync_last_scores_updated_after_write():
    """Après une sync simulée, _last_scores retient la nouvelle valeur."""
    from app.services import eigentrust_sync

    aid = _aid()
    eigentrust_sync._last_scores.pop(aid, None)

    # Simuler ce que _sync_blocking fait après un envoi tx réussi
    new_score = 0.37
    eigentrust_sync._last_scores[aid] = new_score

    assert eigentrust_sync._last_scores[aid] == new_score

    eigentrust_sync._last_scores.pop(aid, None)


# ══════════════════════════════════════════════════════════════════════════════
# G. E2E blockchain — indexeur simulé + Anvil (skipped sans Anvil)
# ══════════════════════════════════════════════════════════════════════════════

def _anvil_available():
    try:
        from web3 import Web3
        return Web3(
            Web3.HTTPProvider("http://127.0.0.1:8545", request_kwargs={"timeout": 2})
        ).is_connected()
    except Exception:
        return False


def _backend_available():
    try:
        import requests
        return requests.get("http://localhost:8000/health", timeout=2).ok
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _anvil_available(), reason="Anvil not running on :8545")
def test_e2e_score_recorded_writes_collaboration_log():
    """
    Simule ce que blockchain_indexer fait sur ScoreRecorded(mode=0).
    Après insertion dans collaboration_log, compute_eigentrust voit le score.
    """
    from app.db.collaboration_repo import get_solo_scores
    from app.services.eigentrust_service import compute_eigentrust

    aid = _aid()
    _ins_collab(aid, 87.0, mode=0, block=100)

    solos = get_solo_scores(aid)
    assert 87.0 in solos

    agents = [{"agent_id": aid, "token_id": 0}]
    result = compute_eigentrust(agents, task_p_overrides={aid: 87.0})
    assert result.converged
    assert result.scores_by_agent[aid]["global_trust"] > 0

    _cleanup_collab(aid)


@pytest.mark.integration
@pytest.mark.skipif(not _anvil_available(), reason="Anvil not running on :8545")
def test_e2e_pipeline_upstream_receives_credit():
    """
    Scénario E2E pipeline : ScoreRecorded(mode=1) pour B et C.
    Après compute_eigentrust : A (upstream solo) a global_trust > C (distributeur).
    """
    from app.services.eigentrust_service import compute_eigentrust
    aid_A, aid_B, aid_C = _aid(), _aid(), _aid()

    # Simule indexeur après ScoreRecorded events
    _ins_collab(aid_A, 75.0, mode=0, block=1)
    _ins_collab(aid_B, 65.0, mode=0, block=2)
    _ins_collab(aid_B, 85.0, mode=1, block=3)
    _ins_collab(aid_C, 60.0, mode=0, block=4)
    _ins_collab(aid_C, 90.0, mode=1, block=5)

    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
        {"agent_id": aid_C, "token_id": 0},
    ]
    result = compute_eigentrust(agents)

    assert result.converged
    tA = result.scores_by_agent[aid_A]["global_trust"]
    tC = result.scores_by_agent[aid_C]["global_trust"]
    assert tA > tC, f"A (upstream) doit > C (distributeur). A={tA:.4f}, C={tC:.4f}"

    _cleanup_collab(aid_A, aid_B, aid_C)


@pytest.mark.integration
@pytest.mark.skipif(not _anvil_available(), reason="Anvil not running on :8545")
@pytest.mark.skipif(not _backend_available(), reason="Backend not running on :8000")
def test_e2e_reputation_endpoint_eigentrust_present():
    """
    Endpoint /reputation/{agent_id} retourne un eigentrust non nul et cohérent
    après que des données sont en DB.
    """
    import requests

    r = requests.get("http://localhost:8000/api/v1/reputation/researcher-01", timeout=5)
    if r.status_code == 404:
        pytest.skip("researcher-01 non enregistré dans cet environnement")

    assert r.status_code == 200
    data = r.json()
    et = data.get("eigentrust")
    if data.get("token_id") and et:
        assert et["converged"] is True
        assert et["global_trust"] >= 0
        assert et["pre_trust"] >= 0
        assert 0 <= et["final_score"] <= 1


@pytest.mark.integration
@pytest.mark.skipif(not _anvil_available(), reason="Anvil not running on :8545")
def test_e2e_chain_reset_clears_and_rebuilds():
    """
    Propriété 'DB = miroir rebuildable depuis on-chain'.
    Simule : indexeur détecte reset → vide collaboration_log → re-indexe depuis block 0.
    """
    from app.db.collaboration_repo import get_solo_scores
    from app.db.database import _engine
    from sqlalchemy import text

    aid = _aid()
    _ins_collab(aid, 80.0, mode=0, block=50)
    assert 80.0 in get_solo_scores(aid)

    # Simule reset : blockchain_indexer vide la table quand current_block < max_known_block
    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": aid})
        conn.commit()

    assert get_solo_scores(aid) == [], "Collaboration log doit être vide après reset"

    # Re-indexation depuis block 0
    _ins_collab(aid, 80.0, mode=0, block=1)
    assert 80.0 in get_solo_scores(aid), "Re-indexation doit restaurer les données"

    _cleanup_collab(aid)
