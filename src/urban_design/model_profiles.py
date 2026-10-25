"""Typed, secret-free model-provider profile configuration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/model-providers.json"
RESERVED_LOCAL_PORTS = frozenset({8787, 8788, 8789, 9876})
CODEX_CLI_PATH = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
ModelProfileAvailability = Literal[
    "AVAILABLE",
    "NOT_LOGGED_IN",
    "MISSING_KEY",
    "DISABLED",
    "NOT_CONFIGURED",
    "JSON_SCHEMA_UNSUPPORTED",
    "OVER_BUDGET",
    "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED",
    "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE",
    "CLI_NOT_INSTALLED",
    "HERMES_NOT_CONFIGURED",
    "HERMES_TOOLSET_CHECK_REQUIRED",
]


class ModelProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1)
    adapter: Literal["openai_compatible", "anthropic", "gemini", "cli_subprocess"]
    base_url: str = ""
    model: str = ""
    cli_command: Literal["codex", "claude"] | None = None
    reasoning_effort: Literal["max"] | None = None
    keychain_service: str | None = None
    supports_json_schema: bool = False
    data_egress: Literal["cloud", "local", "hermes"]
    enabled: bool = False
    fallback_priority: int | None = Field(None, ge=1)
    upstream_profile_path: str | None = None
    use_ariadne_persona: bool = False

    @model_validator(mode="after")
    def validate_endpoint_and_enabled_profile(self) -> "ModelProviderProfile":
        if self.adapter == "cli_subprocess":
            if self.cli_command is None:
                raise ValueError("CLI subprocess profiles require a fixed cli_command")
            if self.base_url or self.keychain_service:
                raise ValueError("CLI subprocess profiles must not configure an API endpoint or Keychain key")
            if self.data_egress != "cloud":
                raise ValueError("Codex and Claude CLI profiles must declare cloud egress")
            if self.cli_command == "codex" and (self.model != "gpt-6-luna" or self.reasoning_effort != "max"):
                raise ValueError("the codex-cli profile must use the approved gpt-6-luna model with max reasoning effort")
            if self.cli_command != "codex" and self.reasoning_effort is not None:
                raise ValueError("reasoning_effort is only valid for Codex CLI")
            return self
        if self.reasoning_effort is not None:
            raise ValueError("reasoning_effort is only valid for the approved Codex CLI")
        if self.cli_command is not None:
            raise ValueError("cli_command is only valid for CLI subprocess profiles")
        if self.enabled and (not self.base_url.strip() or not self.model.strip()):
            raise ValueError("enabled profiles require a base_url and model")
        if self.enabled and self.data_egress != "hermes" and not self.keychain_service:
            raise ValueError("enabled cloud/local profiles require a Keychain service name")
        if not self.base_url:
            return self

        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not include credentials, query, or fragment data")
        if self.data_egress in {"cloud", "local"} and parsed.scheme != "https":
            if self.data_egress != "local" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("non-HTTPS endpoints are allowed only for loopback local profiles")
        if self.data_egress == "hermes":
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Hermes profiles must target a loopback dedicated profile endpoint")
            if parsed.port in RESERVED_LOCAL_PORTS:
                raise ValueError(f"Hermes profile endpoint port {parsed.port} is reserved")
        elif parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port in RESERVED_LOCAL_PORTS:
            raise ValueError(f"local model profile endpoint port {parsed.port} is reserved")
        return self


class ModelProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    weekly_call_limit: int = Field(..., ge=1)
    max_output_tokens: int = Field(..., ge=1, le=2048)
    timeout_seconds: float = Field(..., gt=0, le=30)
    # Design skills use gpt-6-luna at max effort; one call routinely exceeds 30 s.
    skill_timeout_seconds: float = Field(600, gt=0, le=900)
    fallback_order: list[str]
    profiles: list[ModelProviderProfile]

    @model_validator(mode="after")
    def validate_profile_references(self) -> "ModelProviderConfig":
        ids = [profile.id for profile in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("model profile ids must be unique")
        if len(self.fallback_order) != len(set(self.fallback_order)):
            raise ValueError("fallback order must not repeat a profile")
        unknown = sorted(set(self.fallback_order) - set(ids))
        if unknown:
            raise ValueError(f"fallback order references unknown profile ids: {', '.join(unknown)}")
        return self


def load_model_provider_config(path: str | Path | None = None) -> ModelProviderConfig:
    config_path = Path(path) if path is not None else CONFIG_PATH
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("model-provider configuration could not be loaded") from exc
    if not isinstance(data, dict):
        raise ValueError("model-provider configuration must be a JSON object")
    return ModelProviderConfig.model_validate(data)


class ModelProfileStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    provider: str
    model: str
    status: ModelProfileAvailability
    status_detail: str
    enabled: bool
    active: bool
    supports_json_schema: bool
    egress: Literal["cloud", "local", "hermes"]


class ModelProfilesStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_profile_id: str | None
    weekly_call_limit: int
    weekly_calls_used: int | None
    live_dispatch_enabled: bool
    dispatch_block_reason: str | None
    profiles: list[ModelProfileStatus]


class ModelProfileSelectionStore:
    """Persist only the selected model profile ID, never provider credentials."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_model_profile_selection_path()

    def load(self) -> str | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != 1
            or set(data) != {"schema_version", "profile_id"}
        ):
            return None
        profile_id = data.get("profile_id")
        return profile_id.strip() if isinstance(profile_id, str) and profile_id.strip() else None

    def save(self, profile_id: str) -> None:
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("profile_id must not be blank")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profile_id": profile_id.strip(), "schema_version": 1}
        self.path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def default_model_profile_selection_path() -> Path:
    return Path.cwd() / ".urban_design_runtime" / "model-profile-selection.json"


def default_ariadne_profile_id(config: ModelProviderConfig) -> str | None:
    """Return the configured Ariadne default, following the explicit fallback order."""
    by_id = {profile.id: profile for profile in config.profiles}
    for profile_id in config.fallback_order:
        profile = by_id[profile_id]
        if profile.enabled and profile.supports_json_schema and profile.use_ariadne_persona:
            return profile.id
    return None


def resolve_cli_executable(command: str) -> str | None:
    """Resolve only the two approved CLI entrypoints; never execute them here."""
    if command == "codex":
        return str(CODEX_CLI_PATH) if CODEX_CLI_PATH.is_file() and os.access(CODEX_CLI_PATH, os.X_OK) else None
    if command == "claude":
        return shutil.which("claude")
    return None


def cli_command_available(command: str) -> bool:
    return resolve_cli_executable(command) is not None


_LOGIN_CACHE: dict[str, tuple[float, bool]] = {}
_LOGIN_CACHE_LOCK = threading.Lock()
_INJECTED_CLI_RUNNER: Callable[..., Any] | None = None


def cli_probe_environment() -> dict[str, str]:
    """Pass minimal runtime/login variables plus USER, excluding inherited API keys."""
    allowed = (
        "HOME",
        "PATH",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TERM",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "USER",
    )
    environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    ariadne_home = Path(
        os.environ.get(
            "URBAN_DESIGN_ARIADNE_CODEX_HOME",
            "~/.local/share/urban-design-ariadne/codex-home",
        )
    ).expanduser()
    if (ariadne_home / "auth.json").exists():
        environment["CODEX_HOME"] = str(ariadne_home)
    return environment


def clear_cli_login_cache() -> None:
    with _LOGIN_CACHE_LOCK:
        _LOGIN_CACHE.clear()


def set_cli_login_runner(runner: Callable[..., Any] | None) -> None:
    global _INJECTED_CLI_RUNNER
    _INJECTED_CLI_RUNNER = runner
    clear_cli_login_cache()


def probe_cli_login(
    command: str,
    *,
    runner: Callable[..., Any] | None = None,
    executable: str | None = None,
    force_refresh: bool = False,
) -> bool:
    """Probe CLI login status without dispatching model requests or reading tokens."""
    if command not in {"codex", "claude"}:
        return False

    now = time.monotonic()
    with _LOGIN_CACHE_LOCK:
        cached = _LOGIN_CACHE.get(command)
        if cached is not None and not force_refresh and (now - cached[0] < 60.0):
            return cached[1]

    exe = executable or resolve_cli_executable(command)
    if exe is None:
        return False

    active_runner = runner or _INJECTED_CLI_RUNNER or subprocess.run
    env = cli_probe_environment()

    logged_in = False
    try:
        if command == "claude":
            # claude auth status returns JSON with {"loggedIn": bool, ...}
            result = active_runner(
                [exe, "auth", "status"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env=env,
            )
            stdout = getattr(result, "stdout", "") or ""
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                logged_in = bool(parsed.get("loggedIn"))
        elif command == "codex":
            # codex login status exits 0 when logged in
            result = active_runner(
                [exe, "login", "status"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env=env,
            )
            logged_in = getattr(result, "returncode", None) == 0
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        logged_in = False

    with _LOGIN_CACHE_LOCK:
        _LOGIN_CACHE[command] = (now, logged_in)

    return logged_in


def keychain_service_exists(service: str) -> bool:
    """Check Keychain item presence without requesting, printing, or storing its value."""
    security = Path("/usr/bin/security")
    if not security.is_file():
        return False
    try:
        result = subprocess.run(
            [str(security), "find-generic-password", "-s", service],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def describe_model_profiles(
    config: ModelProviderConfig,
    *,
    active_profile_id: str | None,
    weekly_calls_used: int | None,
    project_ai_authorized: bool,
    model_run_accounting_available: bool,
    credential_exists: Callable[[str], bool] | None = None,
    cli_available: Callable[[str], bool] | None = None,
    cli_logged_in: Callable[[str], bool] | None = None,
) -> list[ModelProfileStatus]:
    """Return profile metadata and availability without exposing credentials or probing providers."""
    credential_exists = credential_exists or keychain_service_exists
    cli_available = cli_available or cli_command_available
    cli_logged_in = cli_logged_in or probe_cli_login
    statuses: list[ModelProfileStatus] = []
    for profile in config.profiles:
        status: ModelProfileAvailability
        detail: str
        if profile.adapter == "openai_compatible" and profile.data_egress == "local" and (
            not profile.base_url.strip() or not profile.model.strip()
        ):
            status, detail = "NOT_CONFIGURED", "Ollama endpoint 與模型尚未設定；未設定前不會呼叫模型。"
        elif not profile.enabled:
            status, detail = "DISABLED", "此 profile 在設定檔中停用。"
        elif not profile.supports_json_schema:
            status, detail = "JSON_SCHEMA_UNSUPPORTED", "此 profile 不支援 Ariadne 所需的 JSON Schema 輸出。"
        elif weekly_calls_used is not None and weekly_calls_used >= config.weekly_call_limit:
            status, detail = "OVER_BUDGET", "本週模型呼叫上限已用完。"
        elif profile.adapter == "cli_subprocess":
            if profile.cli_command is None or not cli_available(profile.cli_command):
                status, detail = "CLI_NOT_INSTALLED", "核准的 CLI 執行檔不存在或不可執行。"
            elif not cli_logged_in(profile.cli_command):
                status, detail = "NOT_LOGGED_IN", "CLI 尚未登入；請在終端機執行 claude 並使用 /login（或 codex login）後重新整理。"
            elif not project_ai_authorized:
                status, detail = "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED", "尚未啟用專案層級 Live AI 授權。"
            elif not model_run_accounting_available or weekly_calls_used is None:
                status, detail = "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE", "耐久 ModelRun 預算與生命週期記帳尚未接線。"
            else:
                status, detail = "AVAILABLE", "設定與執行檔可用，CLI 已登入。"
        elif profile.data_egress == "hermes":
            if not profile.base_url or not profile.model:
                status, detail = "HERMES_NOT_CONFIGURED", "專用 Hermes profile 尚未設定 endpoint 與模型。"
            elif not project_ai_authorized:
                status, detail = "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED", "尚未啟用專案層級 Live AI 授權。"
            elif not model_run_accounting_available or weekly_calls_used is None:
                status, detail = "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE", "耐久 ModelRun 預算與生命週期記帳尚未接線。"
            else:
                status, detail = "HERMES_TOOLSET_CHECK_REQUIRED", "每次請求前仍須確認 Hermes 未啟用任何工具。"
        elif profile.keychain_service and not credential_exists(profile.keychain_service):
            status, detail = "MISSING_KEY", "Keychain 中找不到此服務項目；不讀取或顯示 key 值。"
        elif not project_ai_authorized:
            status, detail = "BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED", "尚未啟用專案層級 Live AI 授權。"
        elif not model_run_accounting_available or weekly_calls_used is None:
            status, detail = "BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE", "耐久 ModelRun 預算與生命週期記帳尚未接線。"
        else:
            status, detail = "AVAILABLE", "設定與必要授權可用；實際模型清單仍會在首次請求前驗證。"

        statuses.append(ModelProfileStatus(
            id=profile.id,
            provider=(profile.cli_command + "-cli") if profile.cli_command else ("hermes" if profile.data_egress == "hermes" else profile.id.split("-", 1)[0]),
            model=profile.model,
            status=status,
            status_detail=detail,
            enabled=profile.enabled,
            active=profile.id == active_profile_id,
            supports_json_schema=profile.supports_json_schema,
            egress=profile.data_egress,
        ))
    return statuses
