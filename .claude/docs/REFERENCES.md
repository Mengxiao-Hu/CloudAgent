# External references (non-binding)

Binding behavior: **`.claude/docs/SPECS.md`** and **`MVP.md`**.

## Primary — LLM + agent loop

| Item | Location |
|------|----------|
| LangChain + Together | `../learn-agent/learn_LangChain/start.py` |

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="Qwen/Qwen2.5-7B-Instruct-Turbo",
    base_url="https://api.together.xyz/v1",
    api_key=os.environ["TOGETHER_API_KEY"],
)
```

- API keys on worker only; never in container.
- Wrap behind `LLMProvider` per `SPECS.md`.

## Demo repository (no login)

| Item | Value |
|------|--------|
| **Default public repo** | https://github.com/vllm-project/vllm |
| **Clone in sandbox** | `git clone --depth 1` → `/workspace/repo` |
| **Analysis** | `rg`/`grep` for TODO/FIXME, then read snippets — not full-repo ingest |
| **Remote writes** | Forbidden (no push/PR) |
| **User-picked URL** | Forbidden in 8h MVP |
| **Offline fallback** | `fixtures/sample-repo/` for dev only |

## Agent tools (flexible, simple only)

Implement straightforward tools (`read`, `write`, `shell`, `finish`). **Reject** with clear errors when asked to: build/install vllm, push git, use private repos, or other heavy/unsafe ops.

## Optional — architecture ideas

| Item | Notes |
|------|--------|
| [generative-ai](https://github.com/GoogleCloudPlatform/generative-ai) | Ideas only; stack stays LangChain + Together |
| [vllm](https://github.com/vllm-project/vllm) | Default analysis target for demo |

## Local sketch

| Item | Location |
|------|----------|
| Protocols | `skeleton.py` |
