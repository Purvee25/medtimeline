"""Gemini call with the same prompt and schema as the Claude extractor, for cheap eval runs.

Eval-only: not wired into the web app. The Gemini free tier lets Google use prompts to improve
its products, so only ever run it on the synthetic reports in `data/`, never real patient data.
Needs `pip install -e ".[gemini]"` and `GEMINI_API_KEY`.
"""

import logging
from typing import TYPE_CHECKING

from .llm import SYSTEM_PROMPT, Extraction

if TYPE_CHECKING:
    from google import genai

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"


def extract_results_gemini(text: str, client: "genai.Client | None" = None) -> Extraction:
    """Ask Gemini for structured results from redacted report text.

    Args:
        text: Redacted report text.
        client: Gemini client; a default one (reads `GEMINI_API_KEY`) is created when omitted.

    Raises:
        pydantic.ValidationError: The response did not match the `Extraction` schema.
        google.genai.errors.APIError: The API call failed.
    """
    from google import genai
    from google.genai import types

    client = client or genai.Client()
    response = client.models.generate_content(
        model=MODEL,
        contents=f"<report>\n{text}\n</report>",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=Extraction,
        ),
    )
    usage = response.usage_metadata
    logger.info(
        "Gemini extraction call done",
        extra={
            "model": MODEL,
            "input_tokens": usage.prompt_token_count if usage else None,
            "output_tokens": usage.candidates_token_count if usage else None,
        },
    )
    return Extraction.model_validate_json(response.text or "")
