"""The factory that builds the chat model the agents talk to.

One function, ``get_chat_model``, returns a configured LangChain chat model for
whichever provider the environment selects (Groq or OpenAI). Keeping it here means
the agent nodes don't know or care which LLM is behind them, and switching
providers is a one-line change in ``backend/.env``.
"""

from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


class LLMConfigurationError(RuntimeError):
    """Raised when the selected LLM provider is missing required configuration.

    The pipeline's per-agent error handling surfaces this as a draft failure with
    a clear message (for example "GROQ_API_KEY is not set") rather than an opaque
    crash.
    """


def get_chat_model() -> BaseChatModel:
    """Return a chat model for the configured provider.

    Reads ``LLM_PROVIDER`` (plus the matching API key and model name) from
    settings. The provider package is imported lazily so picking one provider
    never requires the other's package to be installed.

    Raises ``LLMConfigurationError`` if the provider is unknown or its API key is
    unset.
    """
    settings = get_settings()
    provider = (settings.llm_provider or "").strip().lower()

    if provider == "groq":
        if not settings.groq_api_key:
            raise LLMConfigurationError(
                "GROQ_API_KEY is not set. Add it to backend/.env to use the Groq provider."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=settings.llm_temperature,
            max_retries=2,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not set. Add it to backend/.env to use the OpenAI provider."
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=settings.llm_temperature,
            max_retries=2,
        )

    raise LLMConfigurationError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'groq' or 'openai'."
    )
