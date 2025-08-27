import os
from typing import List, Dict, Any

# Simple wrapper so you can swap providers later
class ChatLLM:
    def __init__(self):
        self.use_openai = bool(os.getenv("OPENAI_API_KEY"))
        if self.use_openai:
            from openai import OpenAI
            self.client = OpenAI()
            # Choose a capable, cost-effective model
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        else:
            # Fallback: no external LLM; raise helpful error on first use
            self.client = None

    def chat(self, system: str, messages: List[Dict[str,str]], temperature: float = 0.3) -> str:
        if not self.use_openai:
            raise RuntimeError("No LLM configured. Set OPENAI_API_KEY in .env to enable responses.")
        # Convert to OpenAI format
        full = [{"role":"system","content":system}] + messages
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=full,
            temperature=temperature
        )
        return resp.choices[0].message.content.strip()
