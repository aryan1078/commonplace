"""The JSON shapes the model is asked to reply with.

Model output is untrusted: it is parsed and validated against these models,
and anything that does not fit is retried or dropped, never passed on.
"""

import json
import re

from pydantic import BaseModel, field_validator


class Fix(BaseModel):
    original: str
    replacement: str
    # Small models write null for fields they have nothing to say about;
    # that is no reason to throw away the fix.
    reason: str | None = ""
    kind: str | None = "grammar"

    @field_validator("reason", "kind", mode="after")
    @classmethod
    def _null_to_default(cls, value: str | None, info) -> str:
        return value if value is not None else cls.model_fields[info.field_name].default


class GrammarResult(BaseModel):
    fixes: list[Fix] = []


def parse_grammar_result(raw: str) -> GrammarResult:
    """Parses a grammar reply. Raises json.JSONDecodeError or ValidationError.

    Small local models sometimes wrap the JSON in ```json fences or add a
    sentence before it even in JSON mode, so the outermost {...} is used.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return GrammarResult.model_validate(json.loads(cleaned))
