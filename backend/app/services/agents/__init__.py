"""The LangGraph multi-agent pipeline package.

Public entry points:
    run_pipeline           run the whole pipeline and get the final state
    get_compiled_pipeline  the cached compiled graph (for advanced use / tests)

Internal modules: ``state`` (the shared state), ``llm_provider`` (the Groq/OpenAI
factory), ``prompts`` (each agent's system prompt), ``nodes`` (the agent
functions), and ``graph`` (the topology and orchestration).
"""

from app.services.agents.graph import get_compiled_pipeline, run_pipeline

__all__ = ["run_pipeline", "get_compiled_pipeline"]
