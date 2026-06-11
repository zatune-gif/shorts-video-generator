import os
import requests


class LLMUnavailableError(Exception):
    pass


class LLMClient:
    def __init__(self):
        self._ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._ollama_model = os.environ.get("OLLAMA_MODEL", "phi3.5")
        self._anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        self._anthropic_model = os.environ.get(
            "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"
        )

    def _ollama_available(self) -> bool:
        try:
            r = requests.get(f"{self._ollama_url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _generate_ollama(self, prompt: str) -> str:
        r = requests.post(
            f"{self._ollama_url}/api/generate",
            json={"model": self._ollama_model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["response"]

    def _chat_ollama(self, messages: list) -> str:
        r = requests.post(
            f"{self._ollama_url}/api/chat",
            json={"model": self._ollama_model, "messages": messages, "stream": False},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _anthropic_client(self):
        if not hasattr(self, "_anthropic_client_instance"):
            import anthropic
            self._anthropic_client_instance = anthropic.Anthropic(api_key=self._anthropic_key)
        return self._anthropic_client_instance

    def _generate_anthropic(self, prompt: str) -> str:
        message = self._anthropic_client().messages.create(
            model=self._anthropic_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _chat_anthropic(self, messages: list) -> str:
        message = self._anthropic_client().messages.create(
            model=self._anthropic_model,
            max_tokens=1024,
            messages=messages,
        )
        return message.content[0].text

    def generate(self, prompt: str) -> str:
        if self._ollama_available():
            return self._generate_ollama(prompt)
        if self._anthropic_key:
            return self._generate_anthropic(prompt)
        raise LLMUnavailableError(
            "OllamaもClaude APIも利用できません。"
            "Ollamaを起動するかANTHROPIC_API_KEYを設定してください。"
        )

    def chat(self, messages: list) -> str:
        if self._ollama_available():
            return self._chat_ollama(messages)
        if self._anthropic_key:
            return self._chat_anthropic(messages)
        raise LLMUnavailableError(
            "OllamaもClaude APIも利用できません。"
            "Ollamaを起動するかANTHROPIC_API_KEYを設定してください。"
        )
