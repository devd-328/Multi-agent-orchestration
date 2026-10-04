import json
import re

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class JsonOutputError(ValueError):
    """Model output has no JSON value. The message never includes the output."""


def extract_json(raw: object) -> object:
    """Return the JSON value in model output.

    Accepts plain JSON, JSON inside a markdown fence, and JSON surrounded by
    prose (the first object or array that parses is used).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise JsonOutputError("Model output is empty.")
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(text):
        if char in "{[":
            try:
                value, _end = json.JSONDecoder().raw_decode(text[index:])
            except json.JSONDecodeError:
                break
            return value
    raise JsonOutputError("Model output is not valid JSON.")
