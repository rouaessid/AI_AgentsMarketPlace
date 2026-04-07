"""
backend/app/services/sandbox_service.py  — Phase 2
"""
from __future__ import annotations
import asyncio, base64, concurrent.futures, hashlib, json, logging, subprocess, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class SandboxInput:
    task_id:str; agent_id:str; task_prompt:str
    task_params:dict=field(default_factory=dict); token_id:int|None=None


@dataclass
class ExecutionManifest:
    run_id:str; registration_id:str; agent_id:str; token_id:int|None
    docker_image:str; task_id:str; exit_code:int; output:Any; output_raw:str
    logs:str; output_hash:str; manifest_hash:str; platform_sig:str
    started_at:str; finished_at:str; duration_sec:float; status:str
    error:str|None; platform_endpoint:str|None=None
    proxy_hash:str|None=None
    proxy_cid:str|None=None
    proxy_metrics:dict|None=None

    def to_dict(self):
        return {
            "run_id":self.run_id,"registration_id":self.registration_id,
            "agent_id":self.agent_id,"token_id":self.token_id,
            "docker_image":self.docker_image,"task_id":self.task_id,
            "exit_code":self.exit_code,"output_hash":self.output_hash,
            "manifest_hash":self.manifest_hash,"platform_sig":self.platform_sig,
            "started_at":self.started_at,"finished_at":self.finished_at,
            "duration_sec":self.duration_sec,"status":self.status,"error":self.error,
            "platform_endpoint":self.platform_endpoint,
            "logs_preview":(self.logs or "")[:2000],
            "output_preview":str(self.output or "")[:500],
            "proxy_hash":self.proxy_hash,"proxy_cid":self.proxy_cid,
            "proxy_metrics":self.proxy_metrics,
        }


def _validate_output(raw, schema="default_v1"):
    if schema == "text_plain": return raw.strip()
    try: parsed = json.loads(raw)
    except json.JSONDecodeError as e: raise ValueError(f"JSON attendu: {e}")
    if schema == "default_v1" and not isinstance(parsed, dict):
        raise ValueError("objet JSON attendu")
    return parsed


def _sign(manifest_hash):
    if settings.platform_private_key:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            signed = Account.sign_message(
                encode_defunct(hexstr=manifest_hash),
                private_key=settings.platform_private_key
            )
            return "0x" + signed.signature.hex()
        except ImportError: pass
    fake = hashlib.sha256((manifest_hash + "dev").encode()).hexdigest()
    return "0x" + fake + fake[:2]


def _docker_inspect_sync(image: str) -> str:
    """
    Résout le digest SHA256 d'une image Docker.
    Teste plusieurs variantes du tag pour les images locales.
    Retourne toujours image_tag@sha256:... ou image_tag si non trouvé.
    """
    # Extraire le tag propre (sans digest éventuel)
    image_tag = image.split("@")[0] if "@" in image else image

    # Variantes à tester dans l'ordre
    candidates = [image_tag]
    if ":" not in image_tag:
        # Si pas de tag explicite → essayer :v1 puis :latest
        candidates += [f"{image_tag}:v1", f"{image_tag}:latest"]

    for candidate in candidates:
        try:
            # Méthode 1 — Image ID (images locales buildées avec docker build)
            r = subprocess.run(
                ["docker", "inspect", "--format={{.Id}}", candidate],
                capture_output=True, text=True, timeout=15,
            )
            image_id = r.stdout.strip()
            if image_id and "sha256:" in image_id:
                result = f"{candidate}@{image_id}"
                logger.info("Digest résolu (local): %s → %s", candidate, result[:70])
                return result

            # Méthode 2 — RepoDigests (images Docker Hub pullées)
            r2 = subprocess.run(
                ["docker", "inspect", "--format={{index .RepoDigests 0}}", candidate],
                capture_output=True, text=True, timeout=15,
            )
            repo_digest = r2.stdout.strip()
            if repo_digest and "@sha256:" in repo_digest:
                logger.info("Digest résolu (hub): %s → %s", candidate, repo_digest[:70])
                return repo_digest

        except FileNotFoundError:
            logger.warning("Docker non disponible")
            return image_tag
        except Exception as e:
            logger.warning("Inspect error pour %s: %s", candidate, e)
            continue

    logger.warning(
        "Digest non résolu pour '%s' — testé: %s. "
        "L'image existe localement ?",
        image_tag, candidates
    )
    return image_tag


def _docker_run_sync(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        logger.warning("Docker non disponible — mock")
        return 0, json.dumps({"status":"success","output":"[mock]","logs":[],"metrics":{}}), ""


def _get_docker_host_ip():
    try:
        r = subprocess.run(
            ["docker", "network", "inspect", "bridge",
             "--format", "{{range .IPAM.Config}}{{.Gateway}}{{end}}"],
            capture_output=True, text=True, timeout=5
        )
        ip = r.stdout.strip()
        if ip: return ip
    except: pass
    return "172.17.0.1"


class SandboxService:

    async def resolve_image_digest(self, image: str) -> str:
        """Résout le digest SHA256. Supporte images locales et Docker Hub."""
        if "@sha256:" in image:
            return image  # déjà un digest valide
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _docker_inspect_sync, image)
        if "@sha256:" not in result:
            logger.warning("Digest non résolu pour '%s'", image)
        return result

    async def run_agent(self, record, sandbox_input, env_vars=None):
        from app.services.ngrok_service import get_agent_endpoint
        from app.services.proxy_service import ProxyService

        sc = record.registration_file.sandbox_config if record.registration_file else {}
        cpu     = sc.get("cpu_limit", 1)
        ram     = sc.get("ram_limit_mb", 512)
        timeout = sc.get("timeout_sec", 60)
        schema  = sc.get("manifest_schema", "default_v1")

        # ── Docker image : toujours utiliser record.docker_image (mis à jour par /run) ──
        # NE PAS utiliser sc.get("docker_image") — il peut être obsolète (sans sha256)
        docker_image = record.docker_image or sc.get("docker_image") or "agentmarket/base:v1"

        run_id     = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # ── 1. Démarrer proxy ──────────────────────────────────────────────
        proxy = ProxyService(run_id, record.agent_id, settings.storage_path)
        proxy_port, ca_cert_path = proxy.start()
        logger.info("Proxy port=%d", proxy_port)

        # ── 2. TASK_INPUT base64 ───────────────────────────────────────────
        task_input_b64 = base64.b64encode(json.dumps({
            "task_id":    sandbox_input.task_id,
            "prompt":     sandbox_input.task_prompt,
            "params":     sandbox_input.task_params,
            "agent_id":   record.agent_id,
            "agent_name": record.name,
            "token_id":   record.current_token_id,
        }).encode()).decode()

        # ── 3. URL proxy ───────────────────────────────────────────────────
        import platform
        proxy_host = "host.docker.internal" if platform.system() == "Windows" else _get_docker_host_ip()
        proxy_url  = f"http://{proxy_host}:{proxy_port}"

        # ── 4. Commande docker run ─────────────────────────────────────────
        cmd = [
            "docker", "run", "--rm",
            "--network",      settings.sandbox_network,
            "--cpus",         str(cpu),
            "--memory",       f"{ram}m",
            "--memory-swap",  f"{ram}m",
            # "--read-only",  # désactivé — patch SSL écrit dans /tmp
            "--tmpfs",        "/tmp:size=64m,noexec,nosuid",
            "--security-opt", "no-new-privileges",
            "--user",         "65534:65534",
            # Proxy injecté
            "-e", f"HTTP_PROXY={proxy_url}",
            "-e", f"HTTPS_PROXY={proxy_url}",
            "-e", f"http_proxy={proxy_url}",
            "-e", f"https_proxy={proxy_url}",
        ]

        # CA cert dynamique — toujours monté
        if ca_cert_path:
            cmd += [
                "--volume", f"{ca_cert_path}:/tmp/mitm-ca.pem:ro",
                "-e",       "MITM_CA_CERT=/tmp/mitm-ca.pem",
                "-e",       "SSL_CERT_FILE=/tmp/mitm-ca.pem",
                "-e",       "REQUESTS_CA_BUNDLE=/tmp/mitm-ca.pem",
                "-e",       "CURL_CA_BUNDLE=/tmp/mitm-ca.pem",
                "-e",       "NODE_EXTRA_CA_CERTS=/tmp/mitm-ca.pem",
            ]

        # TASK_INPUT + clés buyer
        cmd += ["-e", f"TASK_INPUT={task_input_b64}"]
        for k, v in (env_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        cmd.append(docker_image)

        logger.info("Sandbox: %s agent=%s proxy=%s", docker_image, record.agent_id, proxy_url)

        # ── 5. Exécuter container ──────────────────────────────────────────
        exit_code, stdout, stderr = await self._run_docker(cmd, timeout)

        # ── 6. Arrêter proxy → ProxyTrace ──────────────────────────────────
        proxy_trace = proxy.stop()

        finished_at = datetime.now(timezone.utc)
        duration    = (finished_at - started_at).total_seconds()
        logs        = f"[STDOUT]\n{stdout}\n[STDERR]\n{stderr}".strip()

        # ── 7. Status ──────────────────────────────────────────────────────
        status = "success"; output = None; error = None
        if exit_code == -1:
            status = "timeout"; error = f"Timeout after {timeout}s"
        elif exit_code != 0:
            status = "failure"; error = f"Exit code {exit_code} — {stderr[:300]}"
        else:
            try:
                output = _validate_output(stdout, schema)
            except ValueError as e:
                status = "failure"; error = str(e)

        # ── 8. Hashes ──────────────────────────────────────────────────────
        output_hash   = "0x" + hashlib.sha256(stdout.encode()).hexdigest()
        manifest_hash = "0x" + hashlib.sha256(json.dumps({
            "run_id":      run_id,
            "agent_id":    record.agent_id,
            "docker_image": docker_image,
            "token_id":    record.current_token_id,
            "task_id":     sandbox_input.task_id,
            "output_hash": output_hash,
            "exit_code":   exit_code,
            "status":      status,
            "started_at":  started_at.isoformat(),
            "proxy_hash":  proxy_trace.proxy_hash,
        }, sort_keys=True).encode()).hexdigest()
        platform_sig = _sign(manifest_hash)

        # ── 9. Upload proxy trace IPFS ─────────────────────────────────────
        proxy_cid = await self._upload_proxy_trace(proxy_trace)

        proxy_metrics = {
            "total_tokens":     proxy_trace.total_tokens,
            "total_cost_usd":   round(proxy_trace.total_cost_usd, 6),
            "total_latency_ms": round(proxy_trace.total_latency_ms, 1),
            "errors_count":     proxy_trace.errors_count,
            "tools_used":       proxy_trace.tools_used,
            "categories_used":  getattr(proxy_trace, "categories_used", []),
            "llm_calls":        proxy_trace.llm_calls,
            "search_calls":     proxy_trace.search_calls,
            "calls_count":      len(proxy_trace.calls),
        }

        logger.info("Run: status=%s duration=%.1fs tokens=%d llm=%d search=%d",
                    status, duration, proxy_trace.total_tokens,
                    proxy_trace.llm_calls, proxy_trace.search_calls)

        return ExecutionManifest(
            run_id=run_id, registration_id=record.id,
            agent_id=record.agent_id, token_id=record.current_token_id,
            docker_image=docker_image, task_id=sandbox_input.task_id,
            exit_code=exit_code, output=output, output_raw=stdout, logs=logs,
            output_hash=output_hash, manifest_hash=manifest_hash,
            platform_sig=platform_sig, started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(), duration_sec=round(duration, 3),
            status=status, error=error,
            platform_endpoint=get_agent_endpoint(record.agent_id),
            proxy_hash=proxy_trace.proxy_hash, proxy_cid=proxy_cid,
            proxy_metrics=proxy_metrics,
        )

    async def _upload_proxy_trace(self, proxy_trace):
        try:
            from app.services.ipfs_service import IPFSService
            ipfs = IPFSService()
            cid, _, _ = await ipfs.upload(
                json.dumps(proxy_trace.to_dict(), indent=2, ensure_ascii=False),
                name=f"proxy-trace-{proxy_trace.run_id[:8]}"
            )
            logger.info("ProxyTrace IPFS: %s", cid)
            return cid
        except Exception as e:
            logger.warning("IPFS proxy trace: %s", e)
            return None

    async def _run_docker(self, cmd, timeout):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _docker_run_sync, cmd, timeout)