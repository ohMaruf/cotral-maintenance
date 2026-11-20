import json
import os
import subprocess
import time

CHILD_ENV_DROP = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET",
                  "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED",
                  "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}
TIMEOUT_S = 180


def child_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}


class ClaudeCodeClient:
    dialect = "strict"

    def __init__(self, model: str, cwd: str) -> None:
        self.model = model
        self.cwd = cwd

    def complete(self, messages: list[dict], tools: list[dict], slot, seed: int, template=None):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system" and isinstance(m["content"], str))
        content = []
        for m in messages:
            if m["role"] != "user":
                continue
            parts = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            for part in parts:
                if part["type"] == "text":
                    content.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image_url":
                    header, data = part["image_url"]["url"].split(",", 1)
                    media = header.split(":", 1)[1].split(";", 1)[0]
                    content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
        message = {"type": "user", "message": {"role": "user", "content": content}}
        command = ["claude", "-p", "--model", self.model, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                   "--no-session-persistence", "--input-format", "stream-json", "--output-format", "stream-json",
                   "--verbose"]
        if system:
            command += ["--system-prompt", system]
        started = time.monotonic()
        try:
            run = subprocess.run(command, input=json.dumps(message) + "\n", capture_output=True, text=True,
                                 env=child_env(), cwd=self.cwd, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return 0, "timed out", time.monotonic() - started
        seconds = time.monotonic() - started
        result = next((json.loads(line) for line in reversed(run.stdout.splitlines())
                       if line.strip().startswith("{") and '"type":"result"' in line.replace(" ", "")), None)
        if result is None or result.get("is_error"):
            return 0, f"claude -p failed (exit {run.returncode}): {(run.stderr or run.stdout)[-500:]}", seconds
        text = str(result.get("result") or "")
        return 200, {"choices": [{"message": {"content": text}}]}, seconds
