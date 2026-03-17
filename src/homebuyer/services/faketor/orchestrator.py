"""TurnOrchestrator: 9-step pipeline for segment-driven Faketor turns.

Coordinates the full turn lifecycle:
1. Load or create research context
2. Extract buyer signals from user message
3. Classify buyer segment
4. Resolve jobs → TurnPlan
5. Pre-execute proactive analyses
6. Assemble system prompt
7. Run LLM loop (Claude API with tool use)
8. Post-process (extract signals from LLM output, promote state)
9. Persist research context

Phase E-6 (#50) of Epic #23.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from homebuyer.services.faketor.accumulator import AnalysisAccumulator
from homebuyer.services.faketor.classification import SegmentClassifier
from homebuyer.services.faketor.extraction import SignalExtractor
from homebuyer.services.faketor.jobs import JobResolver, TurnPlan
from homebuyer.services.faketor.prompts import PromptAssembler
from homebuyer.services.faketor.state.context import ResearchContext, ResearchContextStore
from homebuyer.services.faketor.tools.executor import ToolExecutor
from homebuyer.services.faketor.tools.preexecution import PreExecutionResult, PreExecutor
from homebuyer.services.faketor.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-sonnet-4-20250514"
_MAX_ITERATIONS = 12
_FALLBACK_REPLY = "Here's what I found based on my analysis so far."


@dataclass
class TurnMetrics:
    """Timing and telemetry for a single turn."""

    extraction_ms: float = 0.0
    classification_ms: float = 0.0
    job_resolution_ms: float = 0.0
    preexecution_ms: float = 0.0
    prompt_assembly_ms: float = 0.0
    llm_loop_ms: float = 0.0
    postprocess_ms: float = 0.0
    total_ms: float = 0.0
    llm_iterations: int = 0
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extraction_ms": round(self.extraction_ms, 1),
            "classification_ms": round(self.classification_ms, 1),
            "job_resolution_ms": round(self.job_resolution_ms, 1),
            "preexecution_ms": round(self.preexecution_ms, 1),
            "prompt_assembly_ms": round(self.prompt_assembly_ms, 1),
            "llm_loop_ms": round(self.llm_loop_ms, 1),
            "postprocess_ms": round(self.postprocess_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "llm_iterations": self.llm_iterations,
            "tools_used": self.tools_used,
        }


@dataclass
class TurnResult:
    """Output of a non-streaming orchestrated turn."""

    reply: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    discussed_properties: list[int] = field(default_factory=list)
    metrics: TurnMetrics = field(default_factory=TurnMetrics)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.error:
            return {"error": self.error}
        return {
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "blocks": self.blocks,
        }


class TurnOrchestrator:
    """Orchestrates a single Faketor chat turn through the 9-step pipeline.

    Usage (non-streaming)::

        orchestrator = TurnOrchestrator(
            client=anthropic_client,
            context_store=context_store,
            signal_extractor=signal_extractor,
            segment_classifier=segment_classifier,
            tool_executor=typed_tool_executor,
            pre_executor=pre_executor,
            registry=tool_registry,
        )
        result = await orchestrator.run(user_id, message, history, property_context)

    Usage (streaming)::

        async for event in orchestrator.run_stream(user_id, message, history, ...):
            yield event  # SSE-compatible dict
    """

    def __init__(
        self,
        *,
        client: Any,  # anthropic.Anthropic
        context_store: ResearchContextStore,
        signal_extractor: SignalExtractor,
        segment_classifier: SegmentClassifier,
        tool_executor: ToolExecutor,
        pre_executor: PreExecutor,
        registry: ToolRegistry,
        job_resolver: JobResolver | None = None,
        prompt_assembler: PromptAssembler | None = None,
        model: str = _CLAUDE_MODEL,
        max_iterations: int = _MAX_ITERATIONS,
    ) -> None:
        self._client = client
        self._context_store = context_store
        self._extractor = signal_extractor
        self._classifier = segment_classifier
        self._tool_executor = tool_executor
        self._pre_executor = pre_executor
        self._registry = registry
        self._resolver = job_resolver or JobResolver()
        self._assembler = prompt_assembler or PromptAssembler()
        self._model = model
        self._max_iterations = max_iterations

    # ------------------------------------------------------------------
    # Step 1: Load or create context
    # ------------------------------------------------------------------

    async def _load_context(self, user_id: str) -> ResearchContext:
        return await self._context_store.load_or_create(user_id)

    # ------------------------------------------------------------------
    # Step 2: Extract buyer signals
    # ------------------------------------------------------------------

    def _extract_signals(
        self,
        message: str,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Extract buyer signals from user message and merge into context."""
        start = time.monotonic()
        try:
            extraction = self._extractor.extract(message)
            if extraction:
                extractions = extraction.to_extractions()
                context.buyer.profile.apply_extraction(extractions)
        except Exception as e:
            logger.warning("Signal extraction failed: %s", e)
        metrics.extraction_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 3: Classify segment
    # ------------------------------------------------------------------

    def _classify_segment(
        self,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Classify buyer segment and update context."""
        start = time.monotonic()
        try:
            result = self._classifier.classify(
                context.buyer.profile,
                context.market,
            )
            context.buyer.record_transition(
                context.buyer.segment_id,
                result.segment_id,
                result.confidence,
            )
        except Exception as e:
            logger.warning("Segment classification failed: %s", e)
        metrics.classification_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 4: Resolve jobs → TurnPlan
    # ------------------------------------------------------------------

    def _resolve_jobs(
        self,
        message: str,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> TurnPlan:
        start = time.monotonic()
        segment_result = None
        if context.buyer.segment_id:
            from homebuyer.services.faketor.classification import SegmentResult
            segment_result = SegmentResult(
                segment_id=context.buyer.segment_id,
                confidence=context.buyer.segment_confidence,
                reasoning="from context",
                factor_coverage=0.5,
            )
        plan = self._resolver.resolve(message, segment_result, context)
        metrics.job_resolution_ms = (time.monotonic() - start) * 1000
        return plan

    # ------------------------------------------------------------------
    # Step 5: Pre-execute proactive analyses
    # ------------------------------------------------------------------

    def _pre_execute(
        self,
        plan: TurnPlan,
        property_context: dict[str, Any] | None,
        metrics: TurnMetrics,
    ) -> PreExecutionResult:
        start = time.monotonic()
        result = self._pre_executor.execute(plan, property_context)
        metrics.preexecution_ms = (time.monotonic() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Step 6: Assemble system prompt
    # ------------------------------------------------------------------

    def _assemble_prompt(
        self,
        context: ResearchContext,
        pre_result: PreExecutionResult,
        accumulated_facts: str | None,
        iteration_remaining: int | None,
        working_set_descriptor: str,
        property_context: dict[str, Any] | None,
        plan: TurnPlan,
        metrics: TurnMetrics,
    ) -> str:
        start = time.monotonic()

        # Combine pre-executed facts with accumulated facts
        all_facts_parts = []
        pre_fragment = pre_result.render_prompt_fragment()
        if pre_fragment:
            all_facts_parts.append(pre_fragment)
        if accumulated_facts:
            all_facts_parts.append(accumulated_facts)
        combined_facts = "\n\n".join(all_facts_parts) if all_facts_parts else None

        prompt = self._assembler.assemble(
            context=context,
            accumulated_facts=combined_facts,
            iteration_remaining=iteration_remaining,
        )

        # Append framing directive from TurnPlan
        if plan.framing.tone or plan.framing.lead_with:
            prompt += "\n\n=== RESPONSE FRAMING ===\n"
            if plan.framing.tone:
                prompt += f"Tone: {plan.framing.tone}\n"
            if plan.framing.lead_with:
                prompt += f"Lead with: {plan.framing.lead_with}\n"
            if plan.framing.avoid:
                prompt += f"Avoid: {plan.framing.avoid}\n"
            prompt += "=== END RESPONSE FRAMING ==="

        # Append secondary nudge
        if plan.secondary_nudge:
            prompt += (
                f"\n\nSECONDARY SUGGESTION: If appropriate, weave in: "
                f'"{plan.secondary_nudge}"'
            )

        # Append property context as JSON for backward compat
        if property_context:
            prompt += (
                f"\n\nCURRENT PROPERTY CONTEXT:\n"
                f"{json.dumps(property_context, indent=2)}"
            )

        if working_set_descriptor:
            prompt += f"\n\n{working_set_descriptor}"

        metrics.prompt_assembly_ms = (time.monotonic() - start) * 1000
        return prompt

    # ------------------------------------------------------------------
    # Step 7: LLM loop (non-streaming)
    # ------------------------------------------------------------------

    def _run_llm_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        accumulator: AnalysisAccumulator,
        metrics: TurnMetrics,
    ) -> TurnResult:
        """Run the Claude API loop with tool use (non-streaming)."""
        start = time.monotonic()
        result = TurnResult()
        tool_schemas = self._registry.get_tool_schemas()

        for iteration in range(self._max_iterations):
            metrics.llm_iterations = iteration + 1

            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                )
            except Exception as e:
                logger.error("Claude API error: %s", e)
                result.error = f"AI service error: {e}"
                break

            # Extract text
            text_parts = [b.text for b in response.content if b.type == "text"]

            # Check for tool use
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                # No tools — done
                result.reply = "\n\n".join(text_parts) or _FALLBACK_REPLY
                break

            # Append assistant response with tool_use blocks
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools
            tool_results_for_api = []
            for tool_block in tool_use_blocks:
                tool_result = self._tool_executor.execute(
                    tool_block.name, tool_block.input
                )
                metrics.tools_used.append(tool_block.name)
                result.tool_calls.append({
                    "name": tool_block.name,
                    "input": tool_block.input,
                })

                # Record facts in accumulator
                if tool_result.has_facts:
                    accumulator.record(
                        tool_block.name, tool_block.input, tool_result.facts
                    )

                # Collect blocks
                block = tool_result.to_block()
                if block:
                    result.blocks.append(block)

                # Track discussed properties
                if tool_result.discussed_property_id:
                    result.discussed_properties.append(
                        tool_result.discussed_property_id
                    )

                tool_results_for_api.append(
                    tool_result.to_anthropic_result(tool_block.id)
                )

            # Append tool results and update system prompt with facts
            messages.append({"role": "user", "content": tool_results_for_api})

            summary = accumulator.get_summary()
            if summary:
                system_prompt = self._update_system_prompt_with_facts(
                    system_prompt, summary, iteration
                )

            if response.stop_reason == "end_turn":
                result.reply = "\n\n".join(text_parts) or _FALLBACK_REPLY
                break
        else:
            # Hit max iterations
            result.reply = _FALLBACK_REPLY

        metrics.llm_loop_ms = (time.monotonic() - start) * 1000
        return result

    def _update_system_prompt_with_facts(
        self,
        prompt: str,
        facts_summary: str,
        iteration: int,
    ) -> str:
        """Update system prompt with accumulated facts and iteration budget."""
        remaining = self._max_iterations - iteration - 1
        from homebuyer.services.faketor.prompts import _render_iteration_budget
        budget_str = _render_iteration_budget(remaining)
        if budget_str:
            return prompt + f"\n\n{facts_summary}\n\n{budget_str}"
        return prompt + f"\n\n{facts_summary}"

    # ------------------------------------------------------------------
    # Step 8: Post-process
    # ------------------------------------------------------------------

    def _post_process(
        self,
        llm_result: TurnResult,
        context: ResearchContext,
        metrics: TurnMetrics,
    ) -> None:
        """Extract signals from LLM output and promote state."""
        start = time.monotonic()
        try:
            # Extract signals from the LLM's response text
            if llm_result.reply:
                output_extraction = self._extractor.extract_from_output(
                    llm_result.reply
                )
                if output_extraction:
                    extractions = output_extraction.to_extractions()
                    context.buyer.profile.apply_extraction(extractions)

            # Re-classify after incorporating output signals
            result = self._classifier.classify(
                context.buyer.profile,
                context.market,
            )
            context.buyer.record_transition(
                context.buyer.segment_id,
                result.segment_id,
                result.confidence,
            )

        except Exception as e:
            logger.warning("Post-processing failed: %s", e)
        metrics.postprocess_ms = (time.monotonic() - start) * 1000

    # ------------------------------------------------------------------
    # Step 9: Persist
    # ------------------------------------------------------------------

    async def _persist_context(self, context: ResearchContext) -> None:
        await self._context_store.save(context)

    # ------------------------------------------------------------------
    # Public API: run (non-streaming)
    # ------------------------------------------------------------------

    async def run(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        property_context: dict[str, Any] | None = None,
        working_set_descriptor: str = "",
    ) -> TurnResult:
        """Execute the full 9-step pipeline for a non-streaming turn."""
        total_start = time.monotonic()
        metrics = TurnMetrics()

        # Step 1: Load context
        context = await self._load_context(user_id)

        # Step 2: Extract signals
        self._extract_signals(message, context, metrics)

        # Step 3: Classify segment
        self._classify_segment(context, metrics)

        # Step 4: Resolve jobs
        plan = self._resolve_jobs(message, context, metrics)

        # Step 5: Pre-execute
        pre_result = self._pre_execute(plan, property_context, metrics)

        # Step 6: Assemble prompt
        system_prompt = self._assemble_prompt(
            context=context,
            pre_result=pre_result,
            accumulated_facts=None,
            iteration_remaining=None,
            working_set_descriptor=working_set_descriptor,
            property_context=property_context,
            plan=plan,
            metrics=metrics,
        )

        # Step 7: LLM loop
        messages = list(history) + [{"role": "user", "content": message}]
        accumulator = AnalysisAccumulator()
        result = self._run_llm_loop(system_prompt, messages, accumulator, metrics)

        # Step 8: Post-process
        self._post_process(result, context, metrics)

        # Step 9: Persist
        await self._persist_context(context)

        metrics.total_ms = (time.monotonic() - total_start) * 1000
        result.metrics = metrics

        logger.info(
            "Turn completed: user=%s segment=%s request=%s tools=%d time=%.0fms",
            user_id,
            context.buyer.segment_id,
            plan.request_type.value,
            len(metrics.tools_used),
            metrics.total_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Public API: run_stream (SSE-compatible streaming)
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        user_id: str,
        message: str,
        history: list[dict],
        property_context: dict[str, Any] | None = None,
        working_set_descriptor: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute the 9-step pipeline with SSE streaming events.

        Yields events compatible with the existing SSE format:
        - {"event": "tool_start", "data": {"name": "..."}}
        - {"event": "tool_end", "data": {...}}
        - {"event": "tool_result", "data": {"name": "...", "block": ...}}
        - {"event": "text_delta", "data": {"text": "..."}}
        - {"event": "working_set", "data": {...}}
        - {"event": "discussed_property", "data": {"property_id": ...}}
        - {"event": "done", "data": {"reply": "...", "tool_calls": [...], "blocks": [...]}}
        - {"event": "error", "data": {"message": "..."}}
        """
        total_start = time.monotonic()
        metrics = TurnMetrics()

        # Steps 1-6: Same as non-streaming
        context = await self._load_context(user_id)
        self._extract_signals(message, context, metrics)
        self._classify_segment(context, metrics)
        plan = self._resolve_jobs(message, context, metrics)
        pre_result = self._pre_execute(plan, property_context, metrics)
        system_prompt = self._assemble_prompt(
            context=context,
            pre_result=pre_result,
            accumulated_facts=None,
            iteration_remaining=None,
            working_set_descriptor=working_set_descriptor,
            property_context=property_context,
            plan=plan,
            metrics=metrics,
        )

        # Step 7: Streaming LLM loop
        messages = list(history) + [{"role": "user", "content": message}]
        accumulator = AnalysisAccumulator()
        tool_schemas = self._registry.get_tool_schemas()
        tool_calls_log: list[dict] = []
        blocks: list[dict] = []
        all_text_parts: list[str] = []
        discussed_properties: list[int] = []

        llm_start = time.monotonic()

        for iteration in range(self._max_iterations):
            metrics.llm_iterations = iteration + 1

            try:
                with self._client.messages.stream(
                    model=self._model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                ) as stream:
                    response = stream.get_final_message()

                    # Stream text deltas
                    # Note: In a real implementation, we'd iterate over
                    # stream events for text_delta. For now we use the
                    # final message approach (matches existing pattern).

            except Exception as e:
                logger.error("Claude API stream error: %s", e)
                yield {"event": "error", "data": {"message": f"AI service error: {e}"}}
                return

            # Extract text from final message
            iteration_text = [b.text for b in response.content if b.type == "text"]

            # Check for tool use
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                all_text_parts.extend(iteration_text)
                break

            # Stream text from this iteration
            for text in iteration_text:
                if text.strip():
                    yield {"event": "text_delta", "data": {"text": text}}
                    all_text_parts.append(text)

            # Append assistant response
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools
            tool_results_for_api = []
            for tool_block in tool_use_blocks:
                yield {
                    "event": "tool_start",
                    "data": {
                        "name": tool_block.name,
                        "input": tool_block.input,
                    },
                }

                tool_result = self._tool_executor.execute(
                    tool_block.name, tool_block.input
                )
                metrics.tools_used.append(tool_block.name)
                tool_calls_log.append({
                    "name": tool_block.name,
                    "input": tool_block.input,
                })

                yield {
                    "event": "tool_end",
                    "data": {
                        "name": tool_block.name,
                    },
                }

                # Record facts
                if tool_result.has_facts:
                    accumulator.record(
                        tool_block.name, tool_block.input, tool_result.facts
                    )

                # Emit tool result with block
                block = tool_result.to_block()
                if block:
                    blocks.append(block)

                yield {
                    "event": "tool_result",
                    "data": {
                        "name": tool_block.name,
                        "block": block,
                    },
                }

                # Track discussed properties
                if tool_result.discussed_property_id:
                    discussed_properties.append(tool_result.discussed_property_id)
                    yield {
                        "event": "discussed_property",
                        "data": {
                            "property_id": tool_result.discussed_property_id,
                        },
                    }

                tool_results_for_api.append(
                    tool_result.to_anthropic_result(tool_block.id)
                )

            # Append tool results
            messages.append({"role": "user", "content": tool_results_for_api})

            # Update system prompt with facts
            summary = accumulator.get_summary()
            if summary:
                system_prompt = self._update_system_prompt_with_facts(
                    system_prompt, summary, iteration
                )

            if response.stop_reason == "end_turn":
                break

        metrics.llm_loop_ms = (time.monotonic() - llm_start) * 1000

        # Final text
        reply = "\n\n".join(all_text_parts) or _FALLBACK_REPLY

        # Stream the final text
        if reply != _FALLBACK_REPLY:
            yield {"event": "text_delta", "data": {"text": reply}}

        # Step 8: Post-process
        llm_result = TurnResult(
            reply=reply,
            tool_calls=tool_calls_log,
            blocks=blocks,
            discussed_properties=discussed_properties,
        )
        self._post_process(llm_result, context, metrics)

        # Step 9: Persist
        await self._persist_context(context)

        metrics.total_ms = (time.monotonic() - total_start) * 1000

        # Emit done event
        yield {
            "event": "done",
            "data": {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "blocks": blocks,
            },
        }

        logger.info(
            "Turn (stream) completed: user=%s segment=%s request=%s tools=%d time=%.0fms",
            user_id,
            context.buyer.segment_id,
            plan.request_type.value,
            len(metrics.tools_used),
            metrics.total_ms,
        )
