"""Low-confidence fallback prompt component.

Activates when segment confidence < 0.3. Includes natural elicitation
questions to draw out buyer signals without feeling like an interrogation.

Phase D-3 (#40) of Epic #23.
"""

from __future__ import annotations

from homebuyer.services.faketor.state.buyer import BuyerProfile


def render(profile: BuyerProfile | None = None) -> str:
    """Render the fallback elicitation prompt.

    Selects elicitation questions based on what's already known (avoiding
    redundant questions about known fields).
    """
    questions = _select_questions(profile)
    question_lines = "\n".join(f'- "{q}"' for q in questions)

    return f"""\
=== BUYER CONTEXT ===
Segment: Not yet determined.

When responding, naturally incorporate questions that help clarify this \
buyer's situation. Do NOT interrogate — weave questions into your response:
{question_lines}

One question per response, maximum. Let the conversation flow naturally.
=== END BUYER CONTEXT ==="""


def _select_questions(profile: BuyerProfile | None) -> list[str]:
    """Select relevant elicitation questions based on what's unknown."""
    questions: list[str] = []

    if profile is None:
        return [
            "Are you looking at this as a potential home, or evaluating it as an investment?",
            "Is this your first time buying in Berkeley?",
            "Do you have a sense of your budget or price range?",
        ]

    # Ask about unknown fields
    if profile.intent is None:
        questions.append(
            "Are you looking at this as a potential home, or evaluating it as an investment?"
        )

    if profile.is_first_time_buyer is None and profile.owns_current_home is None:
        questions.append("Is this your first time buying in Berkeley?")

    if profile.capital is None and profile.income is None:
        questions.append("Do you have a sense of your budget or price range?")
    elif profile.capital is None:
        questions.append(
            "Do you have a down payment range in mind, or are you still exploring options?"
        )
    elif profile.income is None:
        questions.append(
            "What monthly payment range would be comfortable for you?"
        )

    if profile.owns_current_home is None and profile.intent == "occupy":
        questions.append("Are you currently renting, or do you own a place you'd be selling?")

    # Always have at least one question
    if not questions:
        questions.append("What's most important to you in your home search right now?")

    return questions[:3]  # Max 3 options to keep it manageable
