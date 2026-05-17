"""
test_reputation.py
==================
Tests for the reputation system: DB schema, repo layer, EigenTrust engine, API.

Run all:
    cd backend && python -m pytest tests/test_reputation.py -v

Run only unit tests (no backend needed):
    cd backend && python -m pytest tests/test_reputation.py -v -m unit

Run only API tests (backend must be running on :8000):
    cd backend && python -m pytest tests/test_reputation.py -v -m api
"""
import sys
import uuid
import time
import pytest
import requests

BASE_URL = "http://localhost:8000"
AGENT_ID = "researcher-01"   # must be registered in the running backend


# ─────────────────────────────────────────────────────────────────────────────
# 1. DB SCHEMA — colonne correctes dans reputation_events
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_reputation_events_schema():
    """reputation_events doit avoir les colonnes du modèle actuel (pas l'ancien)."""
    from app.db.database import _engine
    from sqlalchemy import text

    with _engine.connect() as conn:
        cols = [
            row[1]
            for row in conn.execute(text("PRAGMA table_info(reputation_events)")).fetchall()
        ]

    required = {
        "id", "event_type", "agent_token_id", "agent_id",
        "client_address", "feedback_index", "value", "value_decimals",
        "tag1", "tag2", "is_revoked", "tx_hash", "block_number", "created_at",
    }
    missing = required - set(cols)
    assert not missing, f"Colonnes manquantes dans reputation_events: {missing}"

    old_cols = {"reputation_score", "success_rate"}
    leftover = old_cols & set(cols)
    assert not leftover, f"Ancien schéma encore présent: {leftover}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. REPO LAYER — insert + lecture + agrégation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_insert_and_read_reputation_event():
    """insert_reputation_event puis get_reputation_signals renvoie l'événement."""
    from app.db.reputation_repo import insert_reputation_event, get_reputation_signals
    from app.db.database import _engine
    from sqlalchemy import text

    token_id   = 999_001
    event_id   = f"test-{uuid.uuid4().hex}"
    client     = "0xTESTCLIENT000000000000000000000000000001"

    insert_reputation_event(
        event_id=event_id,
        event_type="new_feedback",
        agent_token_id=token_id,
        client_address=client,
        feedback_index=0,
        value=80,
        value_decimals=0,
        tag1="starred",
        tx_hash="0xabc",
        block_number=1,
    )

    signals = get_reputation_signals(token_id)
    assert len(signals) == 1
    assert signals[0]["tag1"] == "starred"
    assert signals[0]["value"] == 80

    # Cleanup
    with _engine.connect() as conn:
        conn.execute(
            text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
            {"tid": token_id},
        )
        conn.commit()


@pytest.mark.unit
def test_get_aggregated_score():
    """get_aggregated_score calcule count/sum/average par tag."""
    from app.db.reputation_repo import insert_reputation_event, get_aggregated_score
    from app.db.database import _engine
    from sqlalchemy import text

    token_id = 999_002

    for i, val in enumerate([60, 80, 100]):
        insert_reputation_event(
            event_id=f"test-agg-{i}-{uuid.uuid4().hex[:6]}",
            event_type="new_feedback",
            agent_token_id=token_id,
            client_address=f"0xCLIENT{i:040d}",
            feedback_index=i,
            value=val,
            value_decimals=0,
            tag1="starred",
            tx_hash=f"0xtx{i}",
            block_number=i + 1,
        )

    agg = get_aggregated_score(token_id)
    assert "starred" in agg
    assert agg["starred"]["count"] == 3
    assert agg["starred"]["sum"]   == 240
    assert abs(agg["starred"]["average"] - 80.0) < 0.01

    # Cleanup
    with _engine.connect() as conn:
        conn.execute(
            text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
            {"tid": token_id},
        )
        conn.commit()


@pytest.mark.unit
def test_revoked_signal_excluded():
    """Un signal is_revoked=1 ne doit pas apparaître dans get_reputation_signals."""
    from app.db.reputation_repo import (
        insert_reputation_event, get_reputation_signals, mark_revoked,
    )
    from app.db.database import _engine
    from sqlalchemy import text

    token_id = 999_003
    client   = "0xREVOKEDCLIENT00000000000000000000000002"

    insert_reputation_event(
        event_id=f"rev-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=token_id,
        client_address=client,
        feedback_index=0,
        value=20,
        tag1="starred",
        tx_hash="0xrev",
        block_number=1,
    )
    assert len(get_reputation_signals(token_id)) == 1

    mark_revoked(token_id, client, 0)
    assert len(get_reputation_signals(token_id)) == 0

    # Cleanup
    with _engine.connect() as conn:
        conn.execute(
            text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
            {"tid": token_id},
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 3. EIGENTRUST ENGINE — logique mathématique
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_eigentrust_single_agent():
    """Avec 1 seul agent, final_score doit être 1.0 (distribution triviale)."""
    from app.db.reputation_repo import insert_reputation_event
    from app.db.database import _engine
    from sqlalchemy import text
    from app.services.eigentrust_service import compute_eigentrust

    token_id = 999_010

    # Inject a successRate signal so pre-trust > 0
    insert_reputation_event(
        event_id=f"et1-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=token_id,
        client_address="0xJUDGE000000000000000000000000000000001",
        feedback_index=0,
        value=85,
        tag1="successRate",
        tx_hash="0xet1",
        block_number=1,
    )

    agents = [{"agent_id": "agent-et-solo", "token_id": token_id}]
    result = compute_eigentrust(agents)

    assert result.converged
    assert len(result.agent_ids) == 1
    score = result.scores_by_agent["agent-et-solo"]
    assert score["pre_trust"]    == pytest.approx(1.0, abs=1e-4)
    assert score["global_trust"] == pytest.approx(1.0, abs=1e-4)
    assert score["final_score"]  == pytest.approx(1.0, abs=1e-4)

    # Cleanup
    with _engine.connect() as conn:
        conn.execute(
            text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
            {"tid": token_id},
        )
        conn.commit()


@pytest.mark.unit
def test_eigentrust_two_agents_unequal():
    """Agent avec successRate plus élevé doit avoir global_trust > l'autre."""
    from app.db.reputation_repo import insert_reputation_event
    from app.db.database import _engine
    from sqlalchemy import text
    from app.services.eigentrust_service import compute_eigentrust

    t1, t2 = 999_011, 999_012

    # Agent 1 : score 90
    insert_reputation_event(
        event_id=f"et2a-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=t1,
        client_address="0xJ0000000000000000000000000000000000001",
        feedback_index=0,
        value=90,
        tag1="successRate",
        tx_hash="0xet2a",
        block_number=1,
    )
    # Agent 2 : score 30
    insert_reputation_event(
        event_id=f"et2b-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=t2,
        client_address="0xJ0000000000000000000000000000000000002",
        feedback_index=0,
        value=30,
        tag1="successRate",
        tx_hash="0xet2b",
        block_number=1,
    )

    agents = [
        {"agent_id": "agent-high", "token_id": t1},
        {"agent_id": "agent-low",  "token_id": t2},
    ]
    result = compute_eigentrust(agents)

    high = result.scores_by_agent["agent-high"]["global_trust"]
    low  = result.scores_by_agent["agent-low"]["global_trust"]
    assert high > low, f"Expected high ({high:.4f}) > low ({low:.4f})"

    # Cleanup
    with _engine.connect() as conn:
        for tid in (t1, t2):
            conn.execute(
                text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
                {"tid": tid},
            )
        conn.commit()


@pytest.mark.unit
def test_eigentrust_user_feedback_multiplies():
    """starred (user feedback) doit pondérer le final_score vs global_trust."""
    from app.db.reputation_repo import insert_reputation_event
    from app.db.database import _engine
    from sqlalchemy import text
    from app.services.eigentrust_service import compute_eigentrust

    t1, t2 = 999_013, 999_014

    # Même successRate pour les deux
    for tid, client_suffix in [(t1, "01"), (t2, "02")]:
        insert_reputation_event(
            event_id=f"et3sr-{tid}-{uuid.uuid4().hex[:6]}",
            event_type="new_feedback",
            agent_token_id=tid,
            client_address=f"0xJ000000000000000000000000000000000000{client_suffix}",
            feedback_index=0,
            value=80,
            tag1="successRate",
            tx_hash=f"0xet3sr{tid}",
            block_number=1,
        )

    # Seul t1 a un starred élevé (100), t2 pas de starred
    insert_reputation_event(
        event_id=f"et3star-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=t1,
        client_address="0xUSER00000000000000000000000000000000001",
        feedback_index=1,
        value=100,
        tag1="starred",
        tx_hash="0xet3star",
        block_number=2,
    )

    agents = [
        {"agent_id": "agent-starred",    "token_id": t1},
        {"agent_id": "agent-no-starred", "token_id": t2},
    ]
    result = compute_eigentrust(agents)

    s1 = result.scores_by_agent["agent-starred"]
    s2 = result.scores_by_agent["agent-no-starred"]

    # global_trust doit être égal (même successRate)
    assert abs(s1["global_trust"] - s2["global_trust"]) < 0.01
    # final_score de t1 doit être > t2 grâce au starred
    assert s1["final_score"] > s2["final_score"], (
        f"starred agent final ({s1['final_score']:.4f}) should be > no-starred ({s2['final_score']:.4f})"
    )

    # Cleanup
    with _engine.connect() as conn:
        for tid in (t1, t2):
            conn.execute(
                text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
                {"tid": tid},
            )
        conn.commit()


@pytest.mark.unit
def test_eigentrust_no_signals_uniform():
    """Sans aucun signal, EigenTrust doit produire une distribution uniforme."""
    from app.services.eigentrust_service import compute_eigentrust

    agents = [
        {"agent_id": f"empty-agent-{i}", "token_id": 998_000 + i}
        for i in range(3)
    ]
    result = compute_eigentrust(agents)
    scores = [result.scores_by_agent[a["agent_id"]]["global_trust"] for a in agents]

    for s in scores:
        assert abs(s - scores[0]) < 1e-4, f"Scores non uniformes: {scores}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. API — endpoint /reputation/{agent_id} (backend doit tourner)
# ─────────────────────────────────────────────────────────────────────────────

def _backend_available():
    try:
        return requests.get(f"{BASE_URL}/health", timeout=2).ok
    except Exception:
        return False

def _blockchain_available():
    try:
        from web3 import Web3
        return Web3(Web3.HTTPProvider("http://127.0.0.1:8545", request_kwargs={"timeout": 2})).is_connected()
    except Exception:
        return False


@pytest.mark.api
@pytest.mark.skipif(not _backend_available(), reason="Backend not running on :8000")
def test_reputation_endpoint_200():
    """GET /reputation/{agent_id} doit retourner 200 avec les champs attendus."""
    r = requests.get(f"{BASE_URL}/api/v1/reputation/{AGENT_ID}", timeout=5)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()

    assert "agent_id"    in data
    assert "token_id"    in data
    assert "raw_signals" in data
    assert "signals"     in data
    assert data["agent_id"] == AGENT_ID


@pytest.mark.api
@pytest.mark.skipif(not _backend_available(), reason="Backend not running on :8000")
def test_reputation_endpoint_unknown_agent():
    """GET /reputation/agent-inconnu doit retourner 404."""
    r = requests.get(f"{BASE_URL}/api/v1/reputation/agent-qui-nexiste-pas", timeout=5)
    assert r.status_code == 404


@pytest.mark.api
@pytest.mark.skipif(not _backend_available(), reason="Backend not running on :8000")
@pytest.mark.skipif(not _blockchain_available(), reason="Anvil not running on :8545")
def test_feedback_submission_updates_score():
    """
    Soumet un avis via l'API puis vérifie que raw_signals.starred.count a augmenté.
    Nécessite : backend + Anvil actifs, REPUTATION_REGISTRY_ADDRESS configurée.
    L'indexer a jusqu'à 10s pour capter le NewFeedback event.
    """
    # Score avant
    before = requests.get(f"{BASE_URL}/api/v1/reputation/{AGENT_ID}", timeout=5).json()
    count_before = before.get("raw_signals", {}).get("starred", {}).get("count", 0)

    # Soumettre feedback (score 4 étoiles)
    resp = requests.post(
        f"{BASE_URL}/api/v1/reputation/{AGENT_ID}/feedback",
        json={"score": 4, "comment": "test automatique"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Feedback failed: {resp.text}"
    assert resp.json().get("status") == "ok"

    # Attendre l'indexer (poll toutes les 2s)
    deadline = time.time() + 10
    count_after = count_before
    while time.time() < deadline:
        time.sleep(2)
        after = requests.get(f"{BASE_URL}/api/v1/reputation/{AGENT_ID}", timeout=5).json()
        count_after = after.get("raw_signals", {}).get("starred", {}).get("count", 0)
        if count_after > count_before:
            break

    assert count_after > count_before, (
        f"starred.count n'a pas augmenté après feedback: avant={count_before}, après={count_after}. "
        "Vérifier que Anvil tourne et que REPUTATION_REGISTRY_ADDRESS est correct."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. COLLABORATION LOG — schema, insert solo/pipeline, idempotence
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_collaboration_log_schema():
    """collaboration_log doit avoir toutes les colonnes attendues."""
    from app.db.database import _engine
    from sqlalchemy import text

    with _engine.connect() as conn:
        cols = [
            row[1]
            for row in conn.execute(text("PRAGMA table_info(collaboration_log)")).fetchall()
        ]

    required = {"id", "agent_id", "task_id", "score", "mode", "tx_hash", "block_number", "created_at"}
    missing  = required - set(cols)
    assert not missing, f"Colonnes manquantes dans collaboration_log: {missing}"


@pytest.mark.unit
def test_insert_and_read_solo_score():
    """insert mode=0 → get_solo_scores retourne le score, get_pipeline_scores non."""
    from app.db.collaboration_repo import insert_collaboration_score, get_solo_scores, get_pipeline_scores
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"test-solo-{uuid.uuid4().hex[:8]}"

    insert_collaboration_score(
        event_id=f"ev-{uuid.uuid4().hex}",
        agent_id=agent_id,
        task_id="task-solo-001",
        score=85.0,
        mode=0,
        tx_hash="0xsolo",
        block_number=1,
    )

    solos     = get_solo_scores(agent_id)
    pipelines = get_pipeline_scores(agent_id)
    assert 85.0 in solos,     "score absent de get_solo_scores"
    assert 85.0 not in pipelines, "score solo ne doit pas apparaitre dans pipeline"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :aid"), {"aid": agent_id})
        conn.commit()


@pytest.mark.unit
def test_insert_and_read_pipeline_score():
    """insert mode=1 → get_pipeline_scores retourne le score, get_solo_scores non."""
    from app.db.collaboration_repo import insert_collaboration_score, get_solo_scores, get_pipeline_scores
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"test-pipe-{uuid.uuid4().hex[:8]}"

    insert_collaboration_score(
        event_id=f"ev-{uuid.uuid4().hex}",
        agent_id=agent_id,
        task_id="task-pipe-001",
        score=72.0,
        mode=1,
        tx_hash="0xpipe",
        block_number=2,
    )

    pipelines = get_pipeline_scores(agent_id)
    solos     = get_solo_scores(agent_id)
    assert 72.0 in pipelines, "score absent de get_pipeline_scores"
    assert 72.0 not in solos, "score pipeline ne doit pas apparaitre dans solo"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :aid"), {"aid": agent_id})
        conn.commit()


@pytest.mark.unit
def test_collaboration_log_idempotent():
    """Même event_id inséré deux fois → une seule ligne (pas de doublon)."""
    from app.db.collaboration_repo import insert_collaboration_score, get_solo_scores
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"test-idem-{uuid.uuid4().hex[:8]}"
    event_id = f"ev-idem-{uuid.uuid4().hex}"

    insert_collaboration_score(event_id, agent_id, "task-idem", 90.0, 0, "0xtx", 1)
    insert_collaboration_score(event_id, agent_id, "task-idem", 90.0, 0, "0xtx", 1)

    solos = get_solo_scores(agent_id)
    assert solos.count(90.0) == 1, f"Doublon détecté: {solos}"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :aid"), {"aid": agent_id})
        conn.commit()


@pytest.mark.unit
def test_collaboration_log_ordered_by_block():
    """get_solo_scores retourne les scores dans l'ordre des blocks."""
    from app.db.collaboration_repo import insert_collaboration_score, get_solo_scores
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"test-order-{uuid.uuid4().hex[:8]}"

    for block, score in [(3, 60.0), (1, 90.0), (2, 75.0)]:
        insert_collaboration_score(
            event_id=f"ev-ord-{uuid.uuid4().hex}",
            agent_id=agent_id,
            task_id=f"task-{block}",
            score=score,
            mode=0,
            tx_hash=f"0xtx{block}",
            block_number=block,
        )

    solos = get_solo_scores(agent_id)
    assert solos == [90.0, 75.0, 60.0], f"Ordre inattendu: {solos}"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :aid"), {"aid": agent_id})
        conn.commit()


@pytest.mark.api
@pytest.mark.skipif(not _backend_available(), reason="Backend not running on :8000")
def test_eigentrust_in_reputation_response():
    """Si un token_id est enregistré, eigentrust doit être calculé (non null)."""
    r = requests.get(f"{BASE_URL}/api/v1/reputation/{AGENT_ID}", timeout=5)
    assert r.status_code == 200
    data = r.json()

    if data.get("token_id"):
        et = data.get("eigentrust")
        assert et is not None, "eigentrust est null malgré un token_id enregistré"
        assert "global_trust"  in et
        assert "pre_trust"     in et
        assert "final_score"   in et
        assert "converged"     in et
        assert et["global_trust"] >= 0
        assert et["final_score"]  >= 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. EIGENTRUST ENGINE V2 — Formule p, matrice C (ATE), Power Method
# ─────────────────────────────────────────────────────────────────────────────
#
# Formules testées :
#   p[i]    = mean(judge_scores)                         normalisé → somme 1
#   uplift  = max(mean(pipeline) − mean(solo), 0) / 100  ATE Imbens 2021
#   C[j][i] = uplift[j] / (N−1)  pour i≠j, 0 pour i=j
#   t       = (1−α)·Cᵀ·t + α·p  convergence ‖Δt‖₁ < ε
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_compute_p_from_scores():
    """p = mean(judge_scores) — juges uniquement, pas de user_feedback."""
    from app.services.eigentrust_service import compute_p_from_scores
    assert abs(compute_p_from_scores([70.0, 80.0, 90.0]) - 80.0) < 1e-6
    assert abs(compute_p_from_scores([100.0, 100.0, 100.0]) - 100.0) < 1e-6
    assert compute_p_from_scores([]) == 0.0


@pytest.mark.unit
def test_compute_p_user_feedback_does_not_enter_p():
    """
    user_feedback N'entre PAS dans p — il va dans f[i] via reputation_events.
    Vérification : compute_p_from_scores ne prend qu'un seul argument.
    """
    from app.services.eigentrust_service import compute_p_from_scores
    import inspect
    sig = inspect.signature(compute_p_from_scores)
    assert list(sig.parameters.keys()) == ["judge_scores"], (
        f"compute_p_from_scores ne doit accepter que judge_scores. "
        f"Paramètres trouvés : {list(sig.parameters.keys())}"
    )


@pytest.mark.unit
def test_compute_C_uplift_no_history():
    """Aucun historique solo ou pipeline → uplift = 0.0"""
    from app.services.eigentrust_service import compute_C_uplift
    uplift = compute_C_uplift(f"agent-ghost-{uuid.uuid4().hex[:8]}")
    assert uplift == 0.0


@pytest.mark.unit
def test_compute_C_uplift_pipeline_better_than_solo():
    """Pipeline > solo → uplift = (mean_pipe − mean_solo) / 100 > 0."""
    from app.services.eigentrust_service import compute_C_uplift
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"uplift-pos-{uuid.uuid4().hex[:8]}"
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t1", 60.0, 0, "0x1", 1)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t2", 80.0, 0, "0x2", 2)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t3", 90.0, 1, "0x3", 3)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t4", 95.0, 1, "0x4", 4)

    uplift = compute_C_uplift(agent_id)
    # mean(solo) = 70, mean(pipeline) = 92.5 → uplift = 22.5/100 = 0.225
    assert abs(uplift - 0.225) < 1e-6, f"Attendu 0.225, obtenu {uplift}"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": agent_id})
        conn.commit()


@pytest.mark.unit
def test_compute_C_uplift_pipeline_worse_than_solo():
    """Pipeline < solo → uplift clampé à 0.0 (max(..., 0))."""
    from app.services.eigentrust_service import compute_C_uplift
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"uplift-neg-{uuid.uuid4().hex[:8]}"
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t1", 90.0, 0, "0x1", 1)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "t2", 50.0, 1, "0x2", 2)

    uplift = compute_C_uplift(agent_id)
    assert uplift == 0.0, f"Uplift négatif non clampé : {uplift}"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": agent_id})
        conn.commit()


@pytest.mark.unit
def test_build_C_matrix_shape_and_diagonal():
    """C est N×N avec diagonale zéro — pas d'auto-confiance."""
    from app.services.eigentrust_service import build_C_matrix

    agent_ids = [f"ag-{i}" for i in range(4)]
    C = build_C_matrix(agent_ids)
    assert C.shape == (4, 4), f"Forme incorrecte : {C.shape}"
    for i in range(4):
        assert C[i][i] == 0.0, f"C[{i}][{i}] devrait être 0, obtenu {C[i][i]}"


@pytest.mark.unit
def test_build_C_matrix_distributes_uplift_equally():
    """Agent avec uplift distribue crédit / (N-1) à chaque autre agent."""
    from app.services.eigentrust_service import build_C_matrix
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    # Agent B : solo=60, pipeline=90 → uplift = 30/100 = 0.30
    agent_b = f"b-dist-{uuid.uuid4().hex[:8]}"
    agent_a = f"a-dist-{uuid.uuid4().hex[:8]}"
    agent_c = f"c-dist-{uuid.uuid4().hex[:8]}"

    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_b, "t1", 60.0, 0, "0x1", 1)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_b, "t2", 90.0, 1, "0x2", 2)

    agent_ids = [agent_a, agent_b, agent_c]   # N=3, B est à l'index 1
    C = build_C_matrix(agent_ids)

    j = agent_ids.index(agent_b)
    expected_share = 0.30 / (3 - 1)   # 0.15
    for i in range(3):
        if i != j:
            assert abs(C[j][i] - expected_share) < 1e-6, (
                f"C[{j}][{i}] = {C[j][i]:.6f}, attendu {expected_share:.6f}"
            )
    assert C[j][j] == 0.0

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": agent_b})
        conn.commit()


@pytest.mark.unit
def test_eigentrust_iterate_converges():
    """Power Method converge en < MAX_ITER itérations sur un cas simple."""
    import numpy as np
    from app.services.eigentrust_service import eigentrust_iterate, ALPHA

    N = 3
    p = np.array([0.5, 0.3, 0.2])
    C = np.eye(N) / N   # fallback neutre

    t, iters, converged = eigentrust_iterate(p, C, alpha=ALPHA)

    assert converged,          f"Non convergé après {iters} itérations"
    assert abs(t.sum() - 1.0) < 1e-5, f"t non normalisé : sum={t.sum()}"
    assert all(ti >= 0 for ti in t), "t contient des valeurs négatives"


# ─────────────────────────────────────────────────────────────────────────────
# 7. WORKFLOW — Validation → Collaboration Log → EigenTrust mis à jour
# ─────────────────────────────────────────────────────────────────────────────
#
# Ces tests simulent le flux complet :
#   1. blockchain_indexer capte ScoreRecorded → écrit collaboration_log
#   2. eigentrust_service lit collaboration_log → construit C (ATE)
#   3. EigenTrust propage le crédit upstream → réputation mise à jour
#
# Les tests insèrent manuellement dans collaboration_log (comme le ferait
# l'indexeur) et vérifient que compute_eigentrust produit les bons scores.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_workflow_solo_scores_feed_C_uplift():
    """
    Après qu'un agent a des scores solo ET pipeline dans collaboration_log,
    compute_C_uplift retourne la bonne valeur ATE.
    Simule : ScoreRecorded(mode=0) × 2 + ScoreRecorded(mode=1) × 2.
    """
    from app.services.eigentrust_service import compute_C_uplift
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    agent_id = f"wf-solo-{uuid.uuid4().hex[:8]}"

    # Indexeur écrit 2 scores solo (mode=0)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "task-s1", 70.0, 0, "0xa1", 10)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "task-s2", 80.0, 0, "0xa2", 11)
    # Indexeur écrit 2 scores pipeline (mode=1)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "task-p1", 88.0, 1, "0xa3", 12)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", agent_id, "task-p2", 92.0, 1, "0xa4", 13)

    uplift = compute_C_uplift(agent_id)
    # mean(solo) = 75, mean(pipeline) = 90 → uplift = 15/100 = 0.15
    assert abs(uplift - 0.15) < 1e-6, f"Attendu 0.15, obtenu {uplift}"

    with _engine.connect() as conn:
        conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": agent_id})
        conn.commit()


@pytest.mark.unit
def test_workflow_pipeline_credit_propagation():
    """
    Pipeline A → B → C.
    B et C ont des scores pipeline > solo → uplift > 0 → C[B][A] > 0, C[C][A] > 0.
    EigenTrust doit donner à A un global_trust > 1/3 (au-dessus de l'uniforme).

    Setup :
      A : solo=[70], pas de pipeline     → uplift = 0
      B : solo=[65], pipeline=[82]       → uplift = 17/100 = 0.17
      C : solo=[60], pipeline=[88]       → uplift = 28/100 = 0.28

    C matrix (j donne crédit à i ≠ j) :
      C[B][A] = C[B][C] = 0.17 / 2 = 0.085
      C[C][A] = C[C][B] = 0.28 / 2 = 0.140

    A reçoit crédit de B (0.085·t[B]) ET de C (0.14·t[C])
    → global_trust[A] > global_trust[B] > global_trust[C]
    """
    from app.services.eigentrust_service import compute_eigentrust
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    aid_A = f"wf-A-{uuid.uuid4().hex[:8]}"
    aid_B = f"wf-B-{uuid.uuid4().hex[:8]}"
    aid_C = f"wf-C-{uuid.uuid4().hex[:8]}"

    # A : solo uniquement
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_A, "t1", 70.0, 0, "0xA1", 1)

    # B : solo + pipeline
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_B, "t2", 65.0, 0, "0xB1", 2)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_B, "t3", 82.0, 1, "0xB2", 3)

    # C : solo + pipeline
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_C, "t4", 60.0, 0, "0xC1", 4)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_C, "t5", 88.0, 1, "0xC2", 5)

    # Agents sans token réputé → p uniforme (pas de successRate en DB)
    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
        {"agent_id": aid_C, "token_id": 0},
    ]
    result = compute_eigentrust(agents)

    tA = result.scores_by_agent[aid_A]["global_trust"]
    tB = result.scores_by_agent[aid_B]["global_trust"]
    tC = result.scores_by_agent[aid_C]["global_trust"]

    # A doit recevoir plus de crédit que les autres (upstream bénéficiaire)
    assert tA > 1.0 / 3 + 0.01, (
        f"A devrait dépasser l'uniforme (1/3) grâce au crédit pipeline. "
        f"global_trust: A={tA:.4f}, B={tB:.4f}, C={tC:.4f}"
    )
    assert tA > tC, (
        f"A doit avoir global_trust > C. A={tA:.4f}, C={tC:.4f}"
    )

    for aid in (aid_A, aid_B, aid_C):
        with _engine.connect() as conn:
            conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": aid})
            conn.commit()


@pytest.mark.unit
def test_workflow_process_solo_task():
    """
    process_solo_task(agent_id, judge_scores) :
    - Calcule p frais = mean(juges)
    - Retourne EigenTrustResult avec l'agent overridé
    - global_trust de l'agent > autres si son p est le plus élevé.
    """
    from app.services.eigentrust_service import process_solo_task

    aid_high = f"solo-high-{uuid.uuid4().hex[:8]}"
    aid_low  = f"solo-low-{uuid.uuid4().hex[:8]}"

    # Deux agents, pas de token (p uniforme depuis DB), pas de collab history
    agents = [
        {"agent_id": aid_high, "token_id": 0},
        {"agent_id": aid_low,  "token_id": 0},
    ]

    # aid_high vient de scorer 90/100 chez les juges
    result = process_solo_task(
        agent_id=aid_high,
        judge_scores=[85.0, 90.0, 95.0],   # mean = 90
        agents=agents,
    )

    assert result.converged
    # aid_high a p=90, aid_low a p uniforme → global_trust(high) > global_trust(low)
    t_high = result.scores_by_agent[aid_high]["global_trust"]
    t_low  = result.scores_by_agent[aid_low]["global_trust"]
    assert t_high > t_low, (
        f"Agent avec juges élevés devrait avoir global_trust plus haut. "
        f"high={t_high:.4f}, low={t_low:.4f}"
    )


@pytest.mark.unit
def test_workflow_user_feedback_goes_to_f_not_p():
    """
    user_feedback → f[i] (tag1="starred" dans reputation_events), PAS dans p[i].
    Vérification : deux agents avec même scores juges, l'un a un starred signal.
    global_trust identique (p identique) mais final_score différent grâce à f.
    """
    from app.services.eigentrust_service import compute_eigentrust
    from app.db.reputation_repo import insert_reputation_event
    from app.db.database import _engine
    from sqlalchemy import text

    token_with_uf    = 997_010
    token_without_uf = 997_011
    aid_with    = f"uf-with-{uuid.uuid4().hex[:8]}"
    aid_without = f"uf-without-{uuid.uuid4().hex[:8]}"

    # Même successRate pour les deux
    for tid, suffix in [(token_with_uf, "01"), (token_without_uf, "02")]:
        insert_reputation_event(
            event_id=f"uf-sr-{tid}-{uuid.uuid4().hex[:6]}",
            event_type="new_feedback",
            agent_token_id=tid,
            client_address=f"0xJUDGE0000000000000000000000000000000{suffix}",
            feedback_index=0,
            value=80,
            tag1="successRate",
            tx_hash=f"0xsr{tid}",
            block_number=1,
        )

    # Seul aid_with a un starred (user_feedback on-chain)
    insert_reputation_event(
        event_id=f"uf-star-{uuid.uuid4().hex}",
        event_type="new_feedback",
        agent_token_id=token_with_uf,
        client_address="0xUSER000000000000000000000000000000000001",
        feedback_index=1,
        value=100,
        tag1="starred",
        tx_hash="0xstar",
        block_number=2,
    )

    agents = [
        {"agent_id": aid_with,    "token_id": token_with_uf},
        {"agent_id": aid_without, "token_id": token_without_uf},
    ]
    result = compute_eigentrust(agents)

    gt_with    = result.scores_by_agent[aid_with]["global_trust"]
    gt_without = result.scores_by_agent[aid_without]["global_trust"]
    fs_with    = result.scores_by_agent[aid_with]["final_score"]
    fs_without = result.scores_by_agent[aid_without]["final_score"]

    # p identique → global_trust identique (f n'influence pas EigenTrust)
    assert abs(gt_with - gt_without) < 0.01, (
        f"global_trust devrait être identique (même p). "
        f"with={gt_with:.4f}, without={gt_without:.4f}"
    )
    # f[with] > f[without] → final_score différent
    assert fs_with > fs_without, (
        f"starred doit augmenter final_score via f[i]. "
        f"with={fs_with:.4f}, without={fs_without:.4f}"
    )

    for tid in (token_with_uf, token_without_uf):
        with _engine.connect() as conn:
            conn.execute(
                text("DELETE FROM reputation_events WHERE agent_token_id = :tid"),
                {"tid": tid},
            )
            conn.commit()


@pytest.mark.unit
def test_workflow_process_pipeline_task():
    """
    process_pipeline_task(pipeline) :
    - Calcule p frais pour chaque agent du pipeline
    - L'agent avec les meilleurs scores juges a le plus grand p.
    """
    from app.services.eigentrust_service import process_pipeline_task

    aid_A = f"pipe-A-{uuid.uuid4().hex[:8]}"
    aid_B = f"pipe-B-{uuid.uuid4().hex[:8]}"
    aid_C = f"pipe-C-{uuid.uuid4().hex[:8]}"

    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
        {"agent_id": aid_C, "token_id": 0},
    ]

    pipeline = [
        {"agent_id": aid_A, "judge_scores": [80.0, 85.0, 90.0]},          # mean = 85, no UF
        {"agent_id": aid_B, "judge_scores": [70.0, 75.0, 80.0]},   # mean = 75
        {"agent_id": aid_C, "judge_scores": [60.0, 65.0, 70.0]},   # mean = 65
    ]

    result = process_pipeline_task(pipeline, agents=agents)

    assert result.converged
    pA = result.scores_by_agent[aid_A]["pre_trust"]
    pB = result.scores_by_agent[aid_B]["pre_trust"]
    pC = result.scores_by_agent[aid_C]["pre_trust"]

    # p est normalisé → pA > pB > pC (85 > 75 > 72.5)
    assert pA > pB, f"pA={pA:.4f} devrait > pB={pB:.4f}"
    assert pB > pC, f"pB={pB:.4f} devrait > pC={pC:.4f}"


@pytest.mark.unit
def test_workflow_upstream_agent_gets_credit():
    """
    Scénario complet :
      Agent A (upstream, no pipeline) est utilisé par B et C.
      B et C ont un fort uplift pipeline → donnent crédit à A.
      Résultat attendu : global_trust[A] > global_trust[C] à convergence.

    Setup identique à test_workflow_pipeline_credit_propagation mais
    on vérifie aussi que le résultat est stable (2ème run = même scores).
    """
    from app.services.eigentrust_service import compute_eigentrust
    from app.db.collaboration_repo import insert_collaboration_score
    from app.db.database import _engine
    from sqlalchemy import text

    aid_A = f"up-A-{uuid.uuid4().hex[:8]}"
    aid_B = f"up-B-{uuid.uuid4().hex[:8]}"
    aid_C = f"up-C-{uuid.uuid4().hex[:8]}"

    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_A, "t1", 72.0, 0, "0xA", 1)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_B, "t2", 64.0, 0, "0xB1", 2)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_B, "t3", 86.0, 1, "0xB2", 3)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_C, "t4", 62.0, 0, "0xC1", 4)
    insert_collaboration_score(f"ev-{uuid.uuid4().hex}", aid_C, "t5", 90.0, 1, "0xC2", 5)

    agents = [
        {"agent_id": aid_A, "token_id": 0},
        {"agent_id": aid_B, "token_id": 0},
        {"agent_id": aid_C, "token_id": 0},
    ]

    result1 = compute_eigentrust(agents)
    result2 = compute_eigentrust(agents)   # déterministe → même résultat

    tA1 = result1.scores_by_agent[aid_A]["global_trust"]
    tA2 = result2.scores_by_agent[aid_A]["global_trust"]
    tC  = result1.scores_by_agent[aid_C]["global_trust"]

    assert tA1 > tC, (
        f"A (upstream bénéficiaire) devrait > C. A={tA1:.4f}, C={tC:.4f}"
    )
    assert abs(tA1 - tA2) < 1e-8, (
        f"compute_eigentrust n'est pas déterministe : run1={tA1}, run2={tA2}"
    )

    for aid in (aid_A, aid_B, aid_C):
        with _engine.connect() as conn:
            conn.execute(text("DELETE FROM collaboration_log WHERE agent_id = :a"), {"a": aid})
            conn.commit()
