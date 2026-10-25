"""One bounded Codex CLI invocation. No fallback provider or automatic retry."""
from __future__ import annotations
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time
from typing import Callable
from urban_design.model_profiles import ModelProviderProfile, resolve_cli_executable
from urban_design.model_provider import CliSubprocessCriticProvider, NoRequestDispatched


class OutcomeUnknown(RuntimeError):
    """Launch occurred; delivery cannot be established."""


class CodexSkillProvider:
    provider_name = 'codex-cli'

    def __init__(self, profile: ModelProviderProfile, *, timeout_seconds: float = 30,
                 max_output_bytes: int = 262144, transport: Callable | None = None):
        if (profile.id, profile.adapter, profile.cli_command, profile.model, profile.reasoning_effort) != (
                'codex-cli', 'cli_subprocess', 'codex', 'gpt-6-luna', 'max'):
            raise ValueError('skills require the approved codex-cli gpt-6-luna + max profile')
        if not 0 < timeout_seconds <= 900 or not 1024 <= max_output_bytes <= 1048576:
            raise ValueError('invalid bounded CLI limits')
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.transport = transport

    def available(self) -> bool:
        return self.profile.enabled and (self.transport is not None or resolve_cli_executable('codex') is not None)

    def generate(self, prompt: str, runtime: Path) -> str:
        if os.environ.get('PROJECT_AI_AUTHORIZED', '').strip() != '1':
            raise NoRequestDispatched('project AI authorization is disabled')
        executable = resolve_cli_executable('codex') if self.transport is None else '/fake/codex'
        if executable is None or not self.profile.enabled:
            raise NoRequestDispatched('approved CLI unavailable')
        # Retained for inspection; never pass a repository as cwd.
        work_root = runtime / 'cli-work'
        work_root.mkdir(parents=True, exist_ok=True)
        cwd = tempfile.mkdtemp(prefix='run-', dir=work_root)
        args = [executable, 'exec', '-m', 'gpt-6-luna', '-c', 'model_reasoning_effort=max',
                '-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '--json', prompt]
        options = dict(cwd=cwd, stdin=subprocess.DEVNULL,
                       timeout=self.timeout_seconds, max_output_bytes=self.max_output_bytes,
                       env=CliSubprocessCriticProvider._subprocess_environment())
        raw = self.transport(args, **options) if self.transport is not None else self._execute(args, options)
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > self.max_output_bytes:
            raise OutcomeUnknown('CLI output exceeded limit or was not text')
        # Codex --json emits JSONL events. Fake transports may return the JSON directly.
        try:
            value = json.loads(raw)
            if isinstance(value, dict) and 'design_intent_zh' in value:
                return raw
        except ValueError:
            pass
        messages = []
        event_stream = False
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and 'type' in event:
                event_stream = True
            item = event.get('item', {}) if isinstance(event, dict) else {}
            if isinstance(item, dict) and item.get('type') == 'agent_message' and event.get('type') == 'item.completed':
                messages.append(item.get('text', ''))
        if event_stream and not messages:
            raise OutcomeUnknown('CLI event stream had no final agent message')
        return messages[-1] if messages else raw

    def _execute(self, args, options) -> str:
        try:
            process = subprocess.Popen(args, cwd=options['cwd'], env=options['env'],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            raise NoRequestDispatched(type(exc).__name__) from exc
        deadline = time.monotonic() + self.timeout_seconds
        stdout = bytearray()
        total = 0
        selector = selectors.DefaultSelector()
        assert process.stdout is not None and process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, True)
        selector.register(process.stderr, selectors.EVENT_READ, False)
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OutcomeUnknown('CLI timeout after launch')
                for key, _ in selector.select(min(remaining, .1)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > self.max_output_bytes:
                        raise OutcomeUnknown('CLI combined output exceeded limit')
                    if key.data:
                        stdout.extend(chunk)
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
            if code != 0:
                raise OutcomeUnknown('CLI nonzero exit after launch')
            return stdout.decode('utf-8')
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise OutcomeUnknown(type(exc).__name__) from exc
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            process.stdout.close()
            process.stderr.close()
