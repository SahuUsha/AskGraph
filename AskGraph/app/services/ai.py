import json
import re

from openai import OpenAI
from pydantic import TypeAdapter

from ..sql_guard import is_read_only


def create_ai_service(
    *,
    api_key: str | None,
    base_url: str,
    model: str,
    timeout_seconds: int = 120,
) -> "AIService":
    return AIService(api_key=api_key, base_url=base_url, model=model, timeout_seconds=timeout_seconds)


class AIService:
    """OpenAI-compatible chat client (NVIDIA API by default)."""

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_seconds: int = 120):
        if not api_key or not base_url or not model:
            raise ValueError("LLM requires NVIDIA_API_KEY, LLM_BASE_URL and LLM_MODEL (see .env.example).")
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_seconds)

    def _complete(self, system_instruction: str, user_content: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            temperature=0.5,
            top_p=1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        match = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        if text.startswith("```"):
            text = (
                text.replace("```sql", "")
                .replace("```python", "")
                .replace("```json", "")
                .replace("```", "")
            )
        return text.strip()

    def gemini_call(self, system_instruction: str, user_content: str) -> str:
        try:
            return self._strip_fences(self._complete(system_instruction, user_content))
        except Exception as e:
            print(f"❌ LLM API Error: {str(e)}")
            return ""

    def gemini_json(self, system_instruction: str, user_content: str, response_schema):
        """Structured JSON call, validated against response_schema. Returns None on failure.

        The schema goes in the prompt rather than response_format, since not every
        OpenAI-compatible endpoint supports structured output.
        """
        adapter = TypeAdapter(response_schema)
        system_instruction += (
            "\n\nRespond with ONLY JSON matching this JSON Schema, no prose:\n"
            + json.dumps(adapter.json_schema())
        )
        try:
            text = self._complete(system_instruction, user_content)
        except Exception as e:
            print(f"❌ LLM API Error: {str(e)}")
            return None
        try:
            return adapter.validate_json(self._strip_fences(text))
        except Exception as e:
            print(f"❌ LLM returned JSON that doesn't match the schema: {e}")
            return None

    def validate_sql_safety(self, sql_query: str, safe_mode: bool, dialect: str = "postgres") -> bool:
        """Safe mode = one read-only statement, parsed. Not a keyword scan."""
        if not sql_query:
            return False
        if not safe_mode:
            return True
        return is_read_only(sql_query, dialect)

    def fix_sql(self, original_sql: str, error_message: str, schema_str: str, dialect: str) -> str:
        system_instruction = (
            f"You are a {dialect.upper()} SQL Expert. Fix the provided SQL based on the error message."
        )
        user_content = (
            f"Schema: {schema_str}\nOriginal SQL: {original_sql}\nError: {error_message}\n"
            "Provide ONLY the corrected raw SQL. No markdown."
        )
        return self.gemini_call(system_instruction, user_content)
