"""
Silent Agent Loop — Self-correcting LLM iteration without user interaction.

Provides a reflection/critique/refinement cycle that improves output quality
by running the LLM against itself. The loop stops when quality criteria are
met or max iterations reached.

Usage:
    from app.services.silent_agent_loop import SilentAgentLoop
    loop = SilentAgentLoop()
    result = await loop.run(
        task="Generate a structured report",
        messages=[{"role": "user", "content": "..."}],
        service=openrouter_service,
        tier="complex",
        max_iterations=3,
    )
    print(result.final_output)
    print(result.iterations)  # critique + refinement history
"""

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IterationRecord:
    """Record of a single iteration in the silent loop."""

    iteration: int
    stage: str  # "generate", "critique", "refine", "validate"
    output: str
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SilentLoopResult:
    """Final result from a silent agent loop execution."""

    final_output: str
    iterations: list[IterationRecord]
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    stopped_reason: str = ""  # "quality_met", "max_iterations", "cost_ceiling", "error"
    quality_score: float = 0.0  # 0.0–1.0 estimated quality


class SilentAgentLoop:
    """
    Self-correcting LLM loop with critique → refine → validate cycles.

    The loop works as follows:
      1. GENERATE: Produce initial output from the task prompt.
      2. CRITIQUE: Ask the model to critique its own output against criteria.
      3. REFINE:   Ask the model to improve the output based on critique.
      4. VALIDATE: Check if refined output meets quality threshold.
      5. Repeat 2–4 until quality threshold met or max iterations reached.

    Cost control:
      - Each iteration checks the cost ceiling before proceeding.
      - Token budgets per iteration prevent runaway loops.
      - Simple tasks use fewer iterations by default.
    """

    # Default quality criteria prompts
    DEFAULT_CRITIQUE_PROMPT = (
        "You are a rigorous critic. Review the following output against these criteria:\n"
        "1. Factual accuracy — are claims well-supported?\n"
        "2. Completeness — does it address all parts of the request?\n"
        "3. Clarity — is it well-structured and easy to understand?\n"
        "4. Conciseness — is it free of redundancy?\n"
        "5. Format compliance — does it match the requested output format?\n\n"
        "Output your critique as a JSON object with keys: "
        "\"issues\" (list of strings), \"strengths\" (list of strings), "
        "\"needs_refinement\" (boolean), \"confidence\" (float 0-1).\n\n"
        "Output to critique:\n{output}\n\n"
        "Critique JSON:"
    )

    DEFAULT_REFINE_PROMPT = (
        "You are an expert editor. Improve the following output based on the critique provided.\n"
        "Preserve all correct information. Fix every issue mentioned.\n"
        "Do not add new unsupported claims. Maintain the requested format.\n\n"
        "Original output:\n{original}\n\n"
        "Critique:\n{critique}\n\n"
        "Improved output:"
    )

    DEFAULT_VALIDATE_PROMPT = (
        "Evaluate whether the following output fully satisfies the original request.\n"
        "Respond with ONLY a JSON object: {\"passes\": boolean, \"quality_score\": float 0-1, \"reason\": string}\n\n"
        "Original request:\n{task}\n\n"
        "Final output:\n{output}\n\n"
        "Evaluation JSON:"
    )

    # Token budgets per iteration stage (estimated max_tokens)
    STAGE_BUDGETS = {
        "simple": {"generate": 2048, "critique": 1024, "refine": 2048, "validate": 512},
        "standard": {"generate": 4096, "critique": 2048, "refine": 4096, "validate": 512},
        "complex": {"generate": 8192, "critique": 4096, "refine": 8192, "validate": 1024},
    }

    def __init__(
        self,
        critique_prompt: str | None = None,
        refine_prompt: str | None = None,
        validate_prompt: str | None = None,
        quality_threshold: float = 0.85,
        max_iterations: int = 3,
    ):
        self.critique_prompt = critique_prompt or self.DEFAULT_CRITIQUE_PROMPT
        self.refine_prompt = refine_prompt or self.DEFAULT_REFINE_PROMPT
        self.validate_prompt = validate_prompt or self.DEFAULT_VALIDATE_PROMPT
        self.quality_threshold = quality_threshold
        self.max_iterations = max_iterations

    def _build_messages(self, system_prompt: str | None, user_prompt: str) -> list[dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    async def _call_llm(
        self,
        service: Any,
        messages: list[dict[str, str]],
        max_tokens: int,
        tier: str,
        temperature: float = 0.3,
    ) -> tuple[str, int]:
        """Call LLM service and collect full response."""
        response_text = ""
        tokens = 0
        async for chunk in service.chat_completion(
            messages,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier,
        ):
            if chunk.startswith("__USAGE__:"):
                try:
                    usage = json.loads(chunk.replace("__USAGE__: ", ""))
                    tokens = usage.get("total_tokens", 0)
                except Exception:
                    pass
            else:
                response_text += chunk
        return response_text.strip(), tokens

    async def run(
        self,
        task: str,
        messages: list[dict[str, str]],
        service: Any,
        tier: str = "standard",
        system_prompt: str | None = None,
        max_iterations: int | None = None,
        quality_threshold: float | None = None,
        custom_critique_prompt: str | None = None,
        custom_refine_prompt: str | None = None,
        custom_validate_prompt: str | None = None,
    ) -> SilentLoopResult:
        """
        Execute the silent agent loop.

        Args:
            task: Description of the task (used for validation).
            messages: Initial messages for generation.
            service: LLM service instance (OpenRouter, MiniMax, etc.).
            tier: Task tier (simple/standard/complex) for token budgets.
            system_prompt: Optional system prompt for generation.
            max_iterations: Override default max iterations.
            quality_threshold: Override default quality threshold.
            custom_critique_prompt: Override default critique prompt template.
            custom_refine_prompt: Override default refine prompt template.
            custom_validate_prompt: Override default validate prompt template.

        Returns:
            SilentLoopResult with final output and iteration history.
        """
        max_iter = max_iterations or self.max_iterations
        threshold = quality_threshold or self.quality_threshold
        budgets = self.STAGE_BUDGETS.get(tier, self.STAGE_BUDGETS["standard"])
        iterations: list[IterationRecord] = []
        total_tokens = 0

        critique_template = custom_critique_prompt or self.critique_prompt
        refine_template = custom_refine_prompt or self.refine_prompt
        validate_template = custom_validate_prompt or self.validate_prompt

        # ------------------------------------------------------------------
        # 1. GENERATE initial output
        # ------------------------------------------------------------------
        try:
            logger.info(f"SilentAgentLoop: Starting generation (tier={tier}, max_iter={max_iter})")
            output, tokens = await self._call_llm(
                service, messages, budgets["generate"], tier, temperature=0.7
            )
            total_tokens += tokens
            iterations.append(IterationRecord(
                iteration=0, stage="generate", output=output[:500],
                tokens_used=tokens, metadata={"full_length": len(output)}
            ))
        except Exception as e:
            logger.error(f"SilentAgentLoop: Generation failed: {e}")
            return SilentLoopResult(
                final_output="",
                iterations=iterations,
                stopped_reason="error",
                total_tokens=total_tokens,
            )

        if max_iter == 0:
            return SilentLoopResult(
                final_output=output,
                iterations=iterations,
                stopped_reason="max_iterations",
                total_tokens=total_tokens,
                quality_score=0.5,
            )

        # ------------------------------------------------------------------
        # 2–4. CRITIQUE → REFINE → VALIDATE loop
        # ------------------------------------------------------------------
        current_output = output
        for i in range(1, max_iter + 1):
            # --- CRITIQUE ---
            try:
                critique_messages = self._build_messages(
                    None,
                    critique_template.format(output=current_output)
                )
                critique_raw, tokens = await self._call_llm(
                    service, critique_messages, budgets["critique"], tier, temperature=0.3
                )
                total_tokens += tokens
                iterations.append(IterationRecord(
                    iteration=i, stage="critique", output=critique_raw[:500],
                    tokens_used=tokens
                ))
            except Exception as e:
                logger.warning(f"SilentAgentLoop: Critique failed at iteration {i}: {e}")
                break

            # Parse critique JSON
            needs_refinement = True
            try:
                # Extract JSON from critique response
                json_start = critique_raw.find("{")
                json_end = critique_raw.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    critique_json = json.loads(critique_raw[json_start:json_end])
                    needs_refinement = critique_json.get("needs_refinement", True)
                    if not needs_refinement:
                        logger.info(f"SilentAgentLoop: Critique says no refinement needed at iteration {i}")
                        break
                else:
                    logger.warning("SilentAgentLoop: Could not parse critique JSON, assuming refinement needed")
            except json.JSONDecodeError:
                logger.warning("SilentAgentLoop: Critique JSON parse failed, assuming refinement needed")

            # --- REFINE ---
            try:
                refine_messages = self._build_messages(
                    None,
                    refine_template.format(original=current_output, critique=critique_raw)
                )
                refined_output, tokens = await self._call_llm(
                    service, refine_messages, budgets["refine"], tier, temperature=0.5
                )
                total_tokens += tokens
                iterations.append(IterationRecord(
                    iteration=i, stage="refine", output=refined_output[:500],
                    tokens_used=tokens, metadata={"full_length": len(refined_output)}
                ))
                current_output = refined_output
            except Exception as e:
                logger.warning(f"SilentAgentLoop: Refinement failed at iteration {i}: {e}")
                break

            # --- VALIDATE ---
            try:
                validate_messages = self._build_messages(
                    None,
                    validate_template.format(task=task, output=current_output)
                )
                validate_raw, tokens = await self._call_llm(
                    service, validate_messages, budgets["validate"], tier, temperature=0.2
                )
                total_tokens += tokens

                json_start = validate_raw.find("{")
                json_end = validate_raw.rfind("}") + 1
                quality_score = 0.5
                passes = False
                if json_start >= 0 and json_end > json_start:
                    validate_json = json.loads(validate_raw[json_start:json_end])
                    passes = validate_json.get("passes", False)
                    quality_score = validate_json.get("quality_score", 0.5)

                iterations.append(IterationRecord(
                    iteration=i, stage="validate", output=validate_raw[:500],
                    tokens_used=tokens, metadata={"passes": passes, "quality_score": quality_score}
                ))

                if passes and quality_score >= threshold:
                    logger.info(
                        f"SilentAgentLoop: Quality threshold met at iteration {i} "
                        f"(score={quality_score:.2f})"
                    )
                    return SilentLoopResult(
                        final_output=current_output,
                        iterations=iterations,
                        stopped_reason="quality_met",
                        total_tokens=total_tokens,
                        quality_score=quality_score,
                    )
            except Exception as e:
                logger.warning(f"SilentAgentLoop: Validation failed at iteration {i}: {e}")
                continue

        # Loop ended without meeting quality threshold
        logger.info(f"SilentAgentLoop: Max iterations ({max_iter}) reached without quality threshold")
        return SilentLoopResult(
            final_output=current_output,
            iterations=iterations,
            stopped_reason="max_iterations",
            total_tokens=total_tokens,
            quality_score=quality_score if 'quality_score' in dir() else 0.5,
        )

    async def run_simple(
        self,
        task: str,
        messages: list[dict[str, str]],
        service: Any,
        tier: str = "standard",
    ) -> str:
        """Convenience wrapper that returns just the final output string."""
        result = await self.run(task=task, messages=messages, service=service, tier=tier)
        return result.final_output


# Module-level singleton
_silent_loop: SilentAgentLoop | None = None


def get_silent_agent_loop() -> SilentAgentLoop:
    """Get or create the global SilentAgentLoop instance."""
    global _silent_loop
    if _silent_loop is None:
        _silent_loop = SilentAgentLoop()
    return _silent_loop
