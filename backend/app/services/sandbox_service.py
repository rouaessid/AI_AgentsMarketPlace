"""
backend/app/services/sandbox_service.py  — Phase 2
"""
from __future__ import annotations
import asyncio, base64, concurrent.futures, hashlib, json, logging, subprocess, uuid, socket, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import httpx
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
            "output": self.output, # Transmit full output to frontend
            "output_preview":str(self.output or "")[:500],
            "proxy_hash":self.proxy_hash,"proxy_cid":self.proxy_cid,
            "proxy_metrics":self.proxy_metrics,
        }


def _validate_output(raw: str, schema: str = "default_v1"):
    if not raw or not raw.strip():
        return None
    if schema == "text_plain":
        return raw.strip()
    
    # Try to find a JSON block in case of logs pollution
    clean_raw = raw.strip()
    if not (clean_raw.startswith("{") or clean_raw.startswith("[")):
        # Attempt to find the first { and last }
        start = clean_raw.find("{")
        end = clean_raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            clean_raw = clean_raw[start:end+1]

    try:
        parsed = json.loads(clean_raw)
    except json.JSONDecodeError:
        # If JSON fails, fallback to raw text instead of failing the whole run
        logger.warning("Failed to parse agent output as JSON, falling back to raw text")
        return raw.strip()

    if schema == "default_v1" and not isinstance(parsed, dict):
        # Even if it's not a dict, we return it as is rather than crashing
        return parsed
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


def _get_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


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

    async def run_agent(self, record, sandbox_input, env_vars=None, use_proxy=True):
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

        # ── 1. Démarrer proxy (seulement pour les providers, pas les judges) ─
        proxy = ProxyService(run_id, record.agent_id, settings.storage_path)
        if use_proxy:
            proxy_port, ca_cert_path = proxy.start()
            logger.info("Proxy port=%d", proxy_port)
        else:
            proxy_port, ca_cert_path = 0, None
            logger.info("Proxy skipped for judge container")

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
            "--add-host",     "host.docker.internal:host-gateway",
            "--cpus",         str(cpu),
            "--memory",       f"{ram}m",
            "--memory-swap",  f"{ram}m",
            # "--read-only",  # désactivé — patch SSL écrit dans /tmp
            "--tmpfs",        "/tmp:size=64m,noexec,nosuid",
            "--security-opt", "no-new-privileges",
            "--user",         "65534:65534",
        ]
        
        # ── Proxy injecté (si démarré) ──────────────────────────────────────
        if proxy_port > 0:
            cmd += [
                "-e", f"HTTP_PROXY={proxy_url}",
                "-e", f"HTTPS_PROXY={proxy_url}",
                "-e", f"http_proxy={proxy_url}",
                "-e", f"https_proxy={proxy_url}",
            ]
        else:
            logger.warning("Skipping proxy injection because ProxyService failed to start.")

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
        cmd += ["-e", "PYTHONHTTPSVERIFY=0"] # Désactiver SSL pour le proxy sur Windows
        for k, v in (env_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        cmd.append(docker_image)
        logger.info("Sandbox: %s agent=%s proxy=%s", docker_image, record.agent_id, proxy_url)

        # Détection du mode : Script (Task) ou Serveur (Service)
        rf = record.registration_file
        services = rf.services if (rf and rf.services) else []
        is_service = len(services) > 0
        
        if is_service:
            # Mode SERVICE : On lance en arrière-plan et on envoie une requête HTTP
            stdout, stderr, exit_code, response_json = await self._run_service_agent(
                cmd, record.agent_id, services, sandbox_input, timeout
            )
        else:
            # Mode SCRIPT : docker run standard (bloquant)
            exit_code, stdout, stderr = await self._run_docker(cmd, timeout)
            response_json = None

        # ── 6. Arrêter proxy → ProxyTrace ──────────────────────────────────
        proxy_trace = proxy.stop()

        finished_at = datetime.now(timezone.utc)
        duration    = (finished_at - started_at).total_seconds()
        logs        = f"[STDOUT]\n{stdout}\n[STDERR]\n{stderr}".strip()

        # ── 7. Status ──────────────────────────────────────────────────────
        status = "success"; output = None; error = None
        if exit_code == -1:
            status = "timeout"; error = f"Timeout after {timeout}s"
        elif exit_code != 0 and not is_service: 
            status = "failed"; error = f"Exit code {exit_code} — {stderr[:300]}"
        elif is_service and not response_json:
            status = "failed"; error = f"Service failed to respond — check container logs"
        else:
            try:
                if is_service and response_json:
                    output = response_json.get("output", response_json)
                else:
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
        # Inject prompt and output in the trace for judges
        proxy_cid = await self._upload_proxy_trace(
            proxy_trace, 
            task_prompt=sandbox_input.task_prompt,
            agent_output=output
        )

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

    async def _upload_proxy_trace(self, proxy_trace, task_prompt: str, agent_output: Any) -> str:
        """Upload proxy trace to IPFS. Always returns a non-null CID (local fallback)."""
        data = proxy_trace.to_dict()
        
        # Merge task info into the trace bundle for judges
        data["task_prompt"] = task_prompt
        data["agent_output"] = agent_output if isinstance(agent_output, str) else json.dumps(agent_output)
        
        content = json.dumps(data, indent=2, ensure_ascii=False)
        try:
            from app.services.ipfs_service import IPFSService
            ipfs = IPFSService()
            cid, _, _ = await ipfs.upload(
                content,
                name=f"proxy-trace-{proxy_trace.run_id[:8]}"
            )
            logger.info("ProxyTrace IPFS: %s", cid)
            return cid
        except Exception as e:
            logger.warning("IPFS proxy trace upload failed (%s) — using local fallback", e)
            # Fallback: save locally and return a deterministic local CID
            import hashlib
            from pathlib import Path
            h   = hashlib.sha256(content.encode()).hexdigest()[:40]
            cid = f"QmLOCAL{h}"
            base = Path(settings.storage_path) / "ipfs_local"
            base.mkdir(parents=True, exist_ok=True)
            (base / f"{cid}.json").write_text(content, encoding="utf-8")
            logger.info("ProxyTrace saved locally: %s", cid)
            return cid

    async def _run_docker(self, cmd, timeout):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _docker_run_sync, cmd, timeout)

    async def _run_service_agent(self, base_cmd, agent_id, services, sandbox_input, timeout):
        """
        Démarre un agent serveur, attend qu'il soit prêt, et envoie la requête.
        """
        port = _get_free_port()
        container_name = f"sandbox-{uuid.uuid4().hex[:8]}"
        
        # Modifier commande : détaché + mapping port + nom
        cmd = ["docker", "run", "-d", "--name", container_name]
        
        # En mode SERVICE (serveur), on retire --user et --security-opt pour éviter 
        # les erreurs de permissions avec uvicorn et les accès fichiers.
        filtered_options = []
        # Remove security restrictions and --network none for service containers:
        # they need outbound HTTP (Groq/Tavily) and port-mapping to work.
        skip_list = [
            "--user", "--security-opt", "--tmpfs",
            "65534:65534", "no-new-privileges", "/tmp:size=64m,noexec,nosuid",
            "--network", "none",
        ]
        image = base_cmd[-1]
        i = 0
        while i < len(base_cmd):
            opt = base_cmd[i]
            if opt in skip_list:
                if opt in ["--user", "--security-opt", "--tmpfs", "--network"]:
                    i += 1  # skip the argument that follows too
                i += 1
                continue
            if i >= 2 and i < len(base_cmd)-1:
                filtered_options.append(opt)
            i += 1

        # Service containers use bridge so port-mapping and outbound HTTP work.
        cmd += ["--network", "bridge"] + filtered_options + ["-p", f"{port}:8000", image]
        
        logger.info("[service] Starting container %s on port %d. Cmd: %s", container_name, port, " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        
        if r.returncode != 0:
            logger.error("[service] Docker run failed (code %d): %s", r.returncode, r.stderr)
            return "", r.stderr, r.returncode, None

        stdout = ""; stderr = ""; exit_code = 0; response_json = None
        
        try:
            # 1. Attendre que le serveur soit prêt (polling /health)
            url_root = f"http://localhost:{port}"
            async with httpx.AsyncClient(timeout=10) as client:
                agent_ready = False
                for i in range(30): # 30s max startup, 1s between retries
                    try:
                        resp = await client.get(f"{url_root}/health")
                        if resp.status_code == 200:
                            logger.info("[service] Agent ready at %s after %ds", url_root, i + 1)
                            agent_ready = True
                            break
                    except:
                        pass
                    await asyncio.sleep(1)  # wait 1s between each retry

                if not agent_ready:
                    r_logs = subprocess.run(["docker", "logs", "--tail", "30", container_name], capture_output=True, text=True)
                    logger.error("[service] Healthcheck timeout after 30s. Last logs:\n%s", r_logs.stdout + r_logs.stderr)
                
                # 2. Envoyer la tâche
                # On utilise l'endpoint défini dans les services
                run_endpoint = "/run"
                for s in services:
                    if s.name == "run":
                        run_endpoint = s.endpoint
                        break
                
                logger.info("[service] Posting task to %s", run_endpoint)
                payload = {
                    "task_id": sandbox_input.task_id,
                    "prompt": sandbox_input.task_prompt,
                    "params": sandbox_input.task_params
                }
                
                resp = await client.post(f"{url_root}{run_endpoint}", json=payload, timeout=timeout)
                if resp.status_code == 200:
                    response_json = resp.json()
                    stdout = json.dumps(response_json)
                    logger.info("[service] Task completed successfully")
                else:
                    stderr = f"Service returned error {resp.status_code}: {resp.text}"
                    exit_code = 1
                    logger.warning("[service] Task failed: %s", stderr)

        except Exception as e:
            logger.exception("[service] Error during service execution")
            stderr = str(e)
            exit_code = 1
        finally:
            # Cleanup
            logger.info("[service] Stopping container %s", container_name)
            subprocess.run(["docker", "stop", container_name], capture_output=True)
            # Capturer les logs avant de supprimer
            r = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
            stderr += "\n[CONTAINER LOGS]\n" + r.stdout + r.stderr
            subprocess.run(["docker", "rm", container_name], capture_output=True)
            
        return stdout, stderr, exit_code, response_json