"""CloudAgent agent runtime layer.

Public surface:
  - run_agent: the observe -> think -> act loop.
  - LangChainProvider: Together AI + Qwen LLM provider.
  - ToolRegistry: holds the read/write/shell/finish tools.
  - Middleware: BudgetGuardMiddleware, TrimHistoryMiddleware, CapOutputMiddleware.
"""

from .llm import LangChainProvider
from .middleware import (
    BudgetExceeded,
    BudgetGuardMiddleware,
    CapOutputMiddleware,
    TrimHistoryMiddleware,
)
from .prompts import system_prompt
from .runner import run_agent
from .tools import (
    FinishTool,
    ReadFileTool,
    ShellTool,
    Tool,
    ToolRegistry,
    WriteFileTool,
    default_registry,
)

__all__ = [
    "run_agent",
    "LangChainProvider",
    "ToolRegistry",
    "default_registry",
    "Tool",
    "ReadFileTool",
    "WriteFileTool",
    "ShellTool",
    "FinishTool",
    "system_prompt",
    "BudgetGuardMiddleware",
    "BudgetExceeded",
    "TrimHistoryMiddleware",
    "CapOutputMiddleware",
]
