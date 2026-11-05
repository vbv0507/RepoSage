import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_provider")


class GeminiWithGrokFallback:
    """Use Gemini first, then retry the same request with Grok on failure."""
    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    async def ainvoke(self, *args, **kwargs):
        try:
            return await self.primary.ainvoke(*args, **kwargs)
        except Exception as exc:
            logger.warning("Gemini request failed; retrying with Grok: %s", exc)
            return await self.fallback.ainvoke(*args, **kwargs)

    async def astream(self, *args, **kwargs):
        try:
            async for chunk in self.primary.astream(*args, **kwargs):
                yield chunk
            return
        except Exception as exc:
            logger.warning("Gemini stream failed; retrying with Grok: %s", exc)
            async for chunk in self.fallback.astream(*args, **kwargs):
                yield chunk


def _grok_model(api_key: str, temperature: float):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("XAI_MODEL", "grok-4.7"),
        api_key=api_key,
        base_url="https://api.x.ai/v1",
        temperature=temperature,
    )


def get_api_key() -> str:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    if provider == "grok":
        return os.getenv("XAI_API_KEY", "")
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def check_config_status() -> dict:
    key = get_api_key()
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "openai", "grok"}:
        provider = "gemini"
    grok_configured = bool(os.getenv("XAI_API_KEY", "") and len(os.getenv("XAI_API_KEY", "")) > 5)
    configured = bool(key and len(key) > 5) or (provider == "gemini" and grok_configured)
    return {
        "configured": configured,
        "model": (
            os.getenv("OPENAI_MODEL", "gpt-4o-mini") if provider == "openai"
            else os.getenv("XAI_MODEL", "grok-4.7") if provider == "grok"
            else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        ),
        "provider": provider,
        "fallback": "grok" if provider == "gemini" and grok_configured else None,
    }

def get_chat_model(temperature: float = 0.2):
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    api_key = get_api_key()
    grok_key = os.getenv("XAI_API_KEY", "")
    if not api_key and not (provider == "gemini" and grok_key):
        key_name = "OPENAI_API_KEY" if provider == "openai" else "XAI_API_KEY" if provider == "grok" else "GEMINI_API_KEY"
        raise ValueError(f"{key_name} is not set in environment variables.")

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            temperature=temperature
        )

    if provider == "grok":
        return _grok_model(api_key, temperature)

    if provider != "gemini":
        raise ValueError("LLM_PROVIDER must be 'gemini', 'grok', or 'openai'.")

    from langchain_google_genai import ChatGoogleGenerativeAI

    if not api_key:
        return _grok_model(grok_key, temperature)

    primary = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        google_api_key=api_key,
        temperature=temperature,
    )
    return GeminiWithGrokFallback(primary, _grok_model(grok_key, temperature)) if grok_key else primary
