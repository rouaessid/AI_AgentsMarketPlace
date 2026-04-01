from __future__ import annotations
import asyncio
import base64
import concurrent.futures
import hashlib
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class SandboxInput:
    task_id:     str
    agent_id:    str
    task_prompt: str
    task_params: dict[str, Any] = field(default_factory=dict)
    token_id:    int | None     = None


@dataclass
class ExecutionManifest:
    run_id:            str
    registration_id:   str
    agent_id:          str
    token_id:          int | None
    docker_image:      str
    task_id:           str
    exit_code:         int
    output:            Any
    output_raw:        str
    logs:              str
    output_hash:       str
    manifest_hash:     str
    platform_sig:      str
    started_at:        str
    finished_at:       str
    duration_sec:      float
    status:            str
    error:             str | None
    platform_endpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id":            self.run_id,
            "registration_id":   self.registration_id,
            "agent_id":          self.agent_id,
            "token_id":          self.token_id,
            "docker_image":      self.docker_image,
            "task_id":           self.task_id,
            "exit_code":         self.exit_code,
            "output_hash":       self.output_hash,
            "manifest_hash":     self.manifest_hash,
            "platform_sig":      self.platform_sig,
            "started_at":        self.started_at,
            "finished_at":       self.finished_at,
            "duration_sec":      self.duration_sec,
            "status":            self.status,
            "error":             self.error,
            "platform_endpoint": self.platform_endpoint,
            "logs_preview":      (self.logs or "")[:2000],
            "output_preview":    str(self.output or "")[:500],
        }


def _validate_output(raw: str, schema: str = "default_v1") -> Any:
    if schema == "text_plain":
        return raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Output invalide (JSON attendu): {e}")
    if schema == "default_v1" and not isinstance(parsed, dict):
        raise ValueError("default_v1: objet JSON racine attendu")
    return parsed


def _sign(manifest_hash: str) -> str:
    if settings.platform_private_key:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            msg    = encode_defunct(hexstr=manifest_hash)
            signed = Account.sign_message(
                msg, private_key=settings.platform_private_key
            )
            return "0x" + signed.signature.hex()
        except ImportError:
            pass
    fake = hashlib.sha256((manifest_hash + "dev").encode()).hexdigest()
    return "0x" + fake + fake[:2]


def _docker_inspect_sync(image: str) -> str:
    """
    Récupère le digest SHA256 en synchrone (compatible Windows).
    Préserve le tag original : "strategy-agent:v1@sha256:abc..."
    """
    try:
        # Pull seulement si image Docker Hub
        if "/" in image:
            subprocess.run(
                ["docker", "pull", image],
                capture_output=True,
                timeout=60,
            )

        # Essayer RepoDigest (image Docker Hub pushée)
        r = subprocess.run(
            ["docker", "inspect", "--format={{index .RepoDigests 0}}", image],
            capture_output=True, text=True, timeout=15,
        )
        digest = r.stdout.strip()
        if digest and "@sha256:" in digest:
            return digest

        # Fallback → Image ID local
        # Préserver le tag original : "strategy-agent:v1" + "@sha256:abc..."
        r2 = subprocess.run(
            ["docker", "inspect", "--format={{.Id}}", image],
            capture_output=True, text=True, timeout=15,
        )
        image_id = r2.stdout.strip()
        if image_id:
            # Retirer digest existant si présent, garder le tag
            tag = image.split("@")[0]  # "strategy-agent:v1"
            return f"{tag}@{image_id}"  # "strategy-agent:v1@sha256:8c5f2..."

    except FileNotFoundError:
        logger.warning("Docker non disponible")
    except Exception as e:
        logger.warning("Digest sync error: %s", e)

    return image


def _docker_run_sync(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """
    Exécute docker run en synchrone (compatible Windows).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
        return (
            result.returncode,
            result.stdout.decode(errors="replace"),
            result.stderr.decode(errors="replace"),
        )
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        logger.warning("Docker non disponible — mode mock")
        return _mock_output()


def _mock_output() -> tuple[int, str, str]:
    return 0, json.dumps({
        "status":  "success",
        "output":  "[mock] Docker non disponible — sortie simulee",
        "logs":    [],
        "metrics": {"tokens_used": 0},
    }), ""


class SandboxService:

    async def resolve_image_digest(self, image: str) -> str:
        """
        Récupère le digest SHA256 immuable de l'image Docker.
        Compatible Windows — subprocess dans un thread.

        strategy-agent:v1  →  strategy-agent:v1@sha256:8c5f2...  ✅ tag préservé
        username/agent:v1  →  username/agent@sha256:abc...         ✅ RepoDigest
        image@sha256:...   →  retournée telle quelle               ✅ déjà un digest
        """
        if "@sha256:" in image:
            return image

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, _docker_inspect_sync, image)

        if result != image:
            logger.info("Digest resolu: %s → %s", image, result)
        else:
            logger.warning("Digest non resolu: %s", image)

        return result

    async def run_agent(
        self,
        record: Any,
        sandbox_input: SandboxInput,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionManifest:
        from app.services.ngrok_service import get_agent_endpoint

        sc           = record.registration_file.sandbox_config \
                       if record.registration_file else {}
        docker_image = sc.get("docker_image") or record.docker_image \
                       or "python:3.11-slim"
        cpu          = sc.get("cpu_limit", 1)
        ram          = sc.get("ram_limit_mb", 512)
        timeout      = sc.get("timeout_sec", 60)
        schema       = sc.get("manifest_schema", "default_v1")

        run_id     = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        # TASK_INPUT en base64 — évite les problèmes de guillemets sur Windows
        task_input_json = json.dumps({
            "task_id":    sandbox_input.task_id,
            "prompt":     sandbox_input.task_prompt,
            "params":     sandbox_input.task_params,
            "agent_id":   record.agent_id,
            "agent_name": record.name,
            "token_id":   record.current_token_id,
        })
        task_input_b64 = base64.b64encode(task_input_json.encode()).decode()

        cmd = [
            "docker", "run", "--rm",
            "--network",      settings.sandbox_network,
            "--dns",          "8.8.8.8",
            "--dns",          "1.1.1.1",
            "--cpus",         str(cpu),
            "--memory",       f"{ram}m",
            "--memory-swap",  f"{ram}m",
            # "--read-only",
            # "--tmpfs",        "/tmp:size=64m,noexec,nosuid",
            # "--security-opt", "no-new-privileges",
            # "--user",         "65534:65534",
            "-e",             f"TASK_INPUT={task_input_b64}",
        ]
        # Clés du buyer injectées dans le container
        for k, v in (env_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        cmd.append(docker_image)

        logger.info("Sandbox: image=%s agent=%s", docker_image, record.agent_id)
        logger.debug("Docker cmd: %s", " ".join(cmd))

        logger.info("Docker cmd: %s", " ".join(cmd))

        exit_code, stdout, stderr = await self._run_docker(cmd, timeout)

        finished_at = datetime.now(timezone.utc)
        duration    = (finished_at - started_at).total_seconds()
        logs        = f"[STDOUT]\n{stdout}\n[STDERR]\n{stderr}".strip()

        status = "success"
        output = None
        error  = None

        if exit_code == -1:
            status = "timeout"
            error  = f"Timeout after {timeout}s"
        elif exit_code != 0:
            status = "failure"
            error  = f"Exit code {exit_code} — stderr: {stderr[:200]}"
        else:
            try:
                output = _validate_output(stdout, schema)
            except ValueError as e:
                status = "failure"
                error  = str(e)

        output_hash = "0x" + hashlib.sha256(stdout.encode()).hexdigest()
        partial = {
            "run_id":       run_id,
            "agent_id":     record.agent_id,
            "docker_image": docker_image,
            "token_id":     record.current_token_id,
            "task_id":      sandbox_input.task_id,
            "output_hash":  output_hash,
            "exit_code":    exit_code,
            "status":       status,
            "started_at":   started_at.isoformat(),
        }
        manifest_hash = "0x" + hashlib.sha256(
            json.dumps(partial, sort_keys=True).encode()
        ).hexdigest()

        platform_sig      = _sign(manifest_hash)
        platform_endpoint = get_agent_endpoint(record.agent_id)
       
        return ExecutionManifest(
            run_id=run_id,
            registration_id=record.id,
            agent_id=record.agent_id,
            token_id=record.current_token_id,
            docker_image=docker_image,
            task_id=sandbox_input.task_id,
            exit_code=exit_code,
            output=output,
            output_raw=stdout,
            logs=logs,
            output_hash=output_hash,
            manifest_hash=manifest_hash,
            platform_sig=platform_sig,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_sec=round(duration, 3),
            status=status,
            error=error,
            platform_endpoint=platform_endpoint,
        )

    async def _run_docker(
        self,
        cmd: list[str],
        timeout: int,
    ) -> tuple[int, str, str]:
        """
        Exécute docker run via subprocess dans un thread (compatible Windows).
        """
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(
                pool,
                _docker_run_sync,
                cmd,
                timeout,
            )
        return result