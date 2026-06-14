"""LLM provider for CloudAgent.

Wraps Together AI's OpenAI-compatible endpoint behind the LLMProvider
protocol defined in SPECS.md (§ 1.1, § 6). The API key lives in the worker
process only (TOGETHER_API_KEY env var) and is never passed into the sandbox
container.
"""

from __future__ import annotations

import os

from langchain_core.callbacks import FileCallbackHandler
from langchain_core.runnables import RunnableConfig

# langchain_openai is a worker-process dependency only. Import lazily inside
# __init__ so this module can be imported (e.g. for tests with a fake provider)
# even when the package is not installed.

MODEL = "Qwen/Qwen2.5-7B-Instruct-Turbo"
BASE_URL = "https://api.together.xyz/v1"
DEFAULT_LOG_PATH = "/tmp/cloudagent_llm.log"


class LangChainProvider:
    """LLMProvider implementation backed by LangChain + Together AI.

    complete(messages, tools) -> {"is_final": bool, "text": str, "tool_calls": [...]}

    Each call is logged via FileCallbackHandler to `log_path` (middleware).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = MODEL,
        base_url: str = BASE_URL,
        temperature: float = 0.7,
        timeout: int = 30,
        log_path: str = DEFAULT_LOG_PATH,
    ):
        api_key = api_key or os.environ.get("TOGETHER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "TOGETHER_API_KEY not set. The LLM key must be provided to the "
                "worker process (never inside the sandbox container)."
            )

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - environment guard
            raise RuntimeError(
                "langchain_openai is required for LangChainProvider. "
                "Install it in the worker environment."
            ) from exc

        self.model = model
        self.log_path = log_path
        self.llm = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        """Bind tools, invoke the model, and parse the response.

        Returns a normalized dict:
          - tool calls present  -> {"is_final": False, "text": "", "tool_calls": [...]}
          - no tool calls       -> {"is_final": True, "text": <content>, "tool_calls": []}

        Each tool_call is {"name": str, "arguments": dict}.
        Each invocation is logged to self.log_path via FileCallbackHandler.
        """
        llm_with_tools = self.llm.bind_tools(tools) if tools else self.llm

        with FileCallbackHandler(self.log_path) as log_handler:
            config = RunnableConfig(callbacks=[log_handler])
            try:
                response = llm_with_tools.invoke(messages, config=config)
            except Exception as exc:  # surface as a final error rather than crashing the loop
                return {
                    "is_final": True,
                    "is_error": True,
                    "text": f"LLM call failed: {exc}",
                    "tool_calls": [],
                }

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            parsed = []
            for tc in tool_calls:
                # LangChain returns dict-like tool calls: {"name", "args", "id"}
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                parsed.append({"name": name, "arguments": args or {}})
            return {"is_final": False, "text": "", "tool_calls": parsed}

        content = getattr(response, "content", "")
        if isinstance(content, list):
            # Some providers return content as a list of blocks; join text parts.
            parts = [
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            ]
            content = "".join(parts)
        return {"is_final": True, "text": content or "", "tool_calls": []}
