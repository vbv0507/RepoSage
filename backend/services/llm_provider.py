import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_provider")

def get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def check_config_status() -> dict:
    key = get_api_key()
    configured = bool(key and len(key) > 5)
    return {
        "configured": configured,
        "model": "gemini-2.5-flash",
        "provider": "Google Gemini (LangChain)"
    }

def get_chat_model(temperature: float = 0.2):
    api_key = get_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment variables.")

    from langchain_google_genai import ChatGoogleGenerativeAI
    
    # Try gemini-2.5-flash or fallback to gemini-1.5-flash
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature
    )
