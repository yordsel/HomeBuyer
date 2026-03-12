"""AI-powered property development potential summarizer using Claude API."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from homebuyer.config import ANTHROPIC_API_KEY
from homebuyer.utils.serialization import safe_json_dumps

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86_400  # 24 hours


@dataclass
class PotentialSummary:
    """AI-generated summary of development potential."""

    summary: str
    recommendation: str
    caveats: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    generated_at: float = 0.0


@dataclass
class PotentialSummaryResponse:
    """Combined potential data + AI summary returned to the frontend."""

    potential: dict
    ai_summary: Optional[PotentialSummary] = None
    ai_error: Optional[str] = None


class PotentialSummarizer:
    """Generates AI summaries of development potential using Claude."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, PotentialSummaryResponse]] = {}
        self._client = None
        self._enabled = bool(ANTHROPIC_API_KEY)

        if self._enabled:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception as e:
                logger.warning("Failed to initialize Anthropic client: %s", e)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _cache_key(self, lat: float, lon: float) -> str:
        rounded = f"{lat:.5f},{lon:.5f}"
        return hashlib.md5(rounded.encode()).hexdigest()

    def _get_cached(self, lat: float, lon: float) -> Optional[PotentialSummaryResponse]:
        key = self._cache_key(lat, lon)
        if key in self._cache:
            cached_time, cached_resp = self._cache[key]
            if time.time() - cached_time < CACHE_TTL_SECONDS:
                logger.info("Cache hit for potential summary at (%s, %s)", lat, lon)
                return cached_resp
            else:
                del self._cache[key]
        return None

    def _set_cached(self, lat: float, lon: float, resp: PotentialSummaryResponse) -> None:
        key = self._cache_key(lat, lon)
        self._cache[key] = (time.time(), resp)

    def _build_prompt(self, potential: dict, property_context: dict) -> str:
        return f"""You are an expert Berkeley, California real estate analyst specializing in development potential and zoning regulations. Analyze the following property's development potential data and provide a concise, actionable summary for a home buyer.

PROPERTY CONTEXT:
- Address: {property_context.get('address', 'Unknown')}
- Neighborhood: {property_context.get('neighborhood', 'Unknown')}
- Lot Size: {property_context.get('lot_size_sqft', 'Unknown')} sqft
- Building Size: {property_context.get('sqft', 'Unknown')} sqft
- Year Built: {property_context.get('year_built', 'Unknown')}
- Beds/Baths: {property_context.get('beds', '?')}/{property_context.get('baths', '?')}

DEVELOPMENT POTENTIAL DATA:
{safe_json_dumps(potential, indent=2)}

Respond in valid JSON with exactly these fields:
{{
  "summary": "A 2-3 sentence overview of this property's development potential. Mention the most impactful opportunities (ADU, unit potential, SB 9, Middle Housing) in plain language. Be specific about numbers (e.g., 'could add up to 3 units' not just 'has potential').",
  "recommendation": "A 1-2 sentence recommendation for a home buyer considering this property's development upside. Frame as whether the development potential adds meaningful value to the purchase. Be balanced and honest.",
  "caveats": ["List of 2-4 important caveats, fine print, or nuances the buyer should be aware of. Include things like: permit requirements, timeline realities, hillside constraints, actual cost vs permit value, Middle Housing being new/untested, BESO compliance requirements, etc."],
  "highlights": ["List of 2-3 top positive highlights about this property's development potential. Be specific."]
}}

IMPORTANT RULES:
- Be specific to THIS property's data, not generic advice.
- If zoning is null or the location is outside Berkeley boundaries, say so clearly.
- If data is incomplete (missing lot size, etc.), note that as a caveat.
- Mention Berkeley-specific regulations by name (Middle Housing Ordinance, BESO, BMC Title 23).
- Do NOT provide investment advice or guaranteed returns.
- Keep language accessible to non-expert home buyers.
- Each caveat should be a single sentence.
- Each highlight should be a single sentence."""

    def generate_summary(
        self,
        potential_dict: dict,
        property_context: dict,
        lat: float,
        lon: float,
    ) -> PotentialSummaryResponse:
        """Generate AI summary for development potential data."""
        cached = self._get_cached(lat, lon)
        if cached is not None:
            return cached

        resp = PotentialSummaryResponse(potential=potential_dict)

        if not self._enabled or not self._client:
            resp.ai_error = "AI summary unavailable (no API key configured)"
            self._set_cached(lat, lon, resp)
            return resp

        try:
            prompt = self._build_prompt(potential_dict, property_context)

            message = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = message.content[0].text

            # Handle markdown code fences
            if raw_text.strip().startswith("```"):
                raw_text = raw_text.strip()
                raw_text = raw_text.split("\n", 1)[1]
                raw_text = raw_text.rsplit("```", 1)[0]

            parsed = json.loads(raw_text)
            resp.ai_summary = PotentialSummary(
                summary=parsed.get("summary", ""),
                recommendation=parsed.get("recommendation", ""),
                caveats=parsed.get("caveats", []),
                highlights=parsed.get("highlights", []),
                generated_at=time.time(),
            )

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse Claude response as JSON: %s", e)
            resp.ai_error = "AI summary format error"
        except Exception as e:
            error_type = type(e).__name__
            logger.warning("Claude API call failed (%s): %s", error_type, e)
            error_str = str(e).lower()
            if "rate_limit" in error_str or "429" in str(e):
                resp.ai_error = "AI summary temporarily unavailable (rate limited)"
            elif "authentication" in error_str or "401" in str(e):
                resp.ai_error = "AI summary unavailable (invalid API key)"
            else:
                resp.ai_error = "AI summary generation failed"

        self._set_cached(lat, lon, resp)
        return resp
