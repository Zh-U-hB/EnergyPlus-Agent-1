import json
import os
import re
import time
from pathlib import Path
from typing import Any, Final

from langchain_core.messages import BaseMessage
from loguru import logger
from pydantic import BaseModel

from src.validator import BaseSchema

MAX_RETRIES: Final[int] = 2
"""Max directed-rollback rounds the validate node will attempt before
falling through to human-in-the-loop review.

Two rounds gives the offending phase one shot to fix itself and one
retry if its first attempt introduces a new cross-ref error. Beyond
that, persistent errors usually indicate a spec-level problem better
handled by a human (reject + revise in the validate interrupt)."""

MAX_SIM_RETRIES: Final[int] = 10
"""Max simulate->revise rollback rounds when an EnergyPlus run fails with
Fatal/Severe errors. Independent from MAX_RETRIES (which gates validate's
cross-ref rollback) so the two loops don't starve each other's budget.
Once exhausted, simulate lets the run fall through to analyze and the
failure is recorded by the test harness.

Note: 10 rounds means up to 11 simulate runs per case in the worst case —
on large buildings this can take a very long time (each round is a full
rebuild + EnergyPlus run). Tune down for faster smoke tests."""

DEFAULT_OUTPUT_DIR: Final[Path] = Path("output")

IDD_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "dependencies"
    / "Energy+.idd"
)

AGENT_LANGUAGE: Final[str] = os.getenv("AGENT_LANGUAGE", "English")
"""Language every agent uses for narrative / summary / explanation text.

Applied project-wide by `language_directive()`. Override via the
`AGENT_LANGUAGE` env var (e.g. "English", "日本語"). Empty / "English"
collapses to a no-op.

EnergyPlus identifiers (tool arg values like object names, schedule
names, construction names, IDD enum choices such as 'Outdoors' /
'Weekdays' / 'FullExterior', numeric values) always remain English
ASCII regardless of this setting — they are consumed by the IDF parser,
not by humans.
"""


def language_directive() -> str:
    """Return a system-prompt suffix enforcing AGENT_LANGUAGE.

    Emits an empty string when the configured language is English, so
    existing prompts stay byte-identical in the default case.
    """
    lang = AGENT_LANGUAGE.strip()
    if lang.lower() in {"", "english", "en"}:
        return ""
    return (
        "\n\n=== Language ===\n"
        f"Write all narrative / summary / explanation text in {lang}. "
        f"This includes your final AIMessage, intake `*_specs` strings, "
        f"and any natural-language error reports.\n"
        "HOWEVER, the following MUST remain English ASCII regardless:\n"
        "  - Tool names and argument keys (name, zone_name, variable_name, ...)\n"
        "  - Argument values that are EnergyPlus identifiers (object names,\n"
        "    schedule names, construction names, material names, layer names)\n"
        "  - Enum choices defined by the IDD (e.g. 'Outdoors', 'Weekdays',\n"
        "    'FullExterior', 'MediumRough', 'SunExposed', 'NoSun', 'Yes', 'No')\n"
        "  - Numeric values, paths, file names\n"
        "Those identifiers are read by the EnergyPlus IDF parser, not by\n"
        "humans — never translate or transliterate them.\n"
    )


_SCHEMA_INITIALIZED = False


def ensure_schema_initialized() -> None:
    """Initialize a blank idfpy IDF in BaseSchema once per process."""
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return
    BaseSchema.set_idf()
    _SCHEMA_INITIALIZED = True


# ── Structured-output text fallback ─────────────────────────────────────────
#
# Some OpenAI-compatible providers (notably Zhipu GLM via the coding endpoint)
# do NOT emit a function_call / tool_call for large nested schemas — instead
# they return the JSON object as plain text, often wrapped in ```json ... ```
# code fences. LangChain's `with_structured_output(method="function_calling")`
# only inspects tool_calls, so it yields `parsed=None, parsing_error=None`
# while `raw.content` holds perfectly valid JSON text. The helpers below
# recover that case without changing the fast path (real tool_calls).

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)```(?:\s)*$",
    re.DOTALL,
)


def strip_code_fences(text: str) -> str:
    """Strip a single wrapping ```json ... ``` / ``` ... ``` fence.

    Returns ``text`` unchanged if it isn't fenced. Only a fence spanning the
    whole string (the common LLM case) is stripped, so embedded snippets are
    left intact.
    """
    if not text:
        return text
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text


def _extract_first_json_object(text: str) -> str | None:
    """Return the substring of ``text`` covering the first balanced ``{...}``.

    Uses brace matching with naive string/escape awareness so it works even
    when the JSON is preceded/followed by prose (e.g. "Here is the result:
    {...} Hope it helps"). Returns ``None`` if no balanced object is found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_structured_from_text[T: BaseModel](text: str, schema: type[T]) -> T | None:
    """Best-effort: parse a Pydantic model out of free-form LLM text.

    Pipeline: strip code fences → locate the first balanced JSON object →
    ``json.loads`` → ``schema.model_validate``. Any failure returns ``None``
    (never raises), so callers can branch on ``is None``.
    """
    if not text:
        return None
    candidate = _extract_first_json_object(strip_code_fences(text))
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return schema.model_validate(data)
    except Exception:
        logger.debug(
            "parse_structured_from_text: model_validate failed for {}",
            schema.__name__,
        )
        return None


def invoke_structured_robust[T: BaseModel](
    llm: Any,
    messages: list[BaseMessage],
    schema: type[T],
    *,
    node_name: str,
    max_retries: int = 1,
) -> T:
    """Invoke a structured-output LLM with a text-JSON fallback.

    ``llm`` must be the result of ``create_llm().with_structured_output(
    schema, method="function_calling", include_raw=True)`` so that
    ``invoke()`` returns ``{"parsed", "parsing_error", "raw"}``.

    Resolution order:
    1. Fast path — the model emitted a real tool_call; ``parsed`` is returned
       unchanged (zero overhead / regression for well-behaved providers).
    2. Text fallback — when ``parsed`` is None but ``raw.content`` carries a
       fenced JSON object (the GLM large-schema case), parse it with
       :func:`parse_structured_from_text`.
    3. Retry — if both fail and ``max_retries`` allows, back off (2s) and try
       again; otherwise raise ``RuntimeError`` with diagnostics.
    """
    attempts = max_retries + 1
    last_raw: BaseMessage | None = None
    last_parsing_error: Any = None
    for attempt in range(attempts):
        result = llm.invoke(messages)
        if not isinstance(result, dict):  # defensive; should not happen
            raise RuntimeError(
                f"{node_name}: structured output wrapper returned "
                f"unexpected type {type(result).__name__}"
            )
        parsed = result.get("parsed")
        if parsed is not None:
            return parsed

        last_raw = result.get("raw")
        last_parsing_error = result.get("parsing_error")
        raw_content = (
            last_raw.content if last_raw is not None and isinstance(last_raw.content, str) else ""
        )

        # Text fallback — try to recover JSON the model emitted as plain text.
        recovered = parse_structured_from_text(raw_content, schema)
        if recovered is not None:
            logger.info(
                "{}: model returned text instead of a tool_call; "
                "recovered {} via JSON text fallback.",
                node_name,
                schema.__name__,
            )
            return recovered

        raw_preview = repr(raw_content)[:500]
        is_truly_empty = last_parsing_error is None and raw_preview in ("''", "None")
        if attempt < attempts - 1:
            sleep_s = 2 ** (attempt + 1)
            logger.warning(
                "{}: structured parse failed (attempt {}/{}); "
                "parsing_error={} raw_preview={} — retrying in {}s",
                node_name,
                attempt + 1,
                attempts,
                last_parsing_error,
                raw_preview,
                sleep_s,
            )
            time.sleep(sleep_s)
            continue

        # Final attempt exhausted.
        if is_truly_empty:
            detail = "The LLM returned an empty reply."
        else:
            detail = (
                "The LLM replied with text instead of a tool call, and the "
                "text did not contain a parseable JSON object."
            )
        logger.error(
            "{}: structured output parsing exhausted. parsing_error={} "
            "raw_preview={}",
            node_name,
            last_parsing_error,
            raw_preview,
        )
        raise RuntimeError(
            f"{node_name}: structured output parsing failed after {attempts} "
            f"attempt(s). {detail} parsing_error={last_parsing_error!r}; "
            f"raw preview: {raw_preview}"
        )

    # Unreachable — loop either returns or raises.
    raise RuntimeError(f"{node_name}: unreachable")
