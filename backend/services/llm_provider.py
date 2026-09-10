import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_provider")

def get_api_key() -> str:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "")
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def check_config_status() -> dict:
    key = get_api_key()
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "openai"}:
        provider = "gemini"
    configured = bool(key and len(key) > 5)
    return {
        "configured": configured,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini") if provider == "openai" else os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "provider": provider
    }

def get_chat_model(temperature: float = 0.2):
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    api_key = get_api_key()
    if not api_key:
        key_name = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
        raise ValueError(f"{key_name} is not set in environment variables.")

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            temperature=temperature
        )

    if provider != "gemini":
        raise ValueError("LLM_PROVIDER must be either 'gemini' or 'openai'.")

    from langchain_google_genai import ChatGoogleGenerativeAI
    
    # Try gemini-2.5-flash or fallback to gemini-1.5-flash
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature
    )
