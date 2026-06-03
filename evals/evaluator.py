"""Evaluator for evals."""

import json
import os
import re
import sys
import time
from datetime import (
    datetime,
    timedelta,
)
from time import sleep
from typing import (
    Any,
    Optional,
)

import openai
from langfuse import Langfuse
from langfuse.api.resources.commons.types.trace_with_details import TraceWithDetails
from tqdm import tqdm

# Fix import path for app module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config.settings import settings
from src.system.logs import logger
from evals.helpers import (
    calculate_avg_scores,
    generate_report,
    get_input_output,
    initialize_metrics_summary,
    initialize_report,
    process_trace_results,
    update_failure_metrics,
    update_success_metrics,
)
from evals.metrics import metrics
from evals.schemas import ScoreSchema


class Evaluator:
    """Evaluates model outputs using predefined metrics.

    This class handles fetching traces from Langfuse, evaluating them against
    metrics, and uploading scores back to Langfuse.

    Attributes:
        client: OpenAI-compatible client for API calls.
        langfuse: Langfuse client for trace management.
    """

    def __init__(self):
        """Initialize Evaluator with an OpenAI-compatible model client and Langfuse."""
        self.client = openai.AsyncOpenAI(api_key=settings.EVALUATION_API_KEY, base_url=settings.EVALUATION_BASE_URL)
        self.langfuse = Langfuse(public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY)
        # Initialize report data structure
        self.report = initialize_report(settings.EVALUATION_LLM)
        initialize_metrics_summary(self.report, metrics)

    async def run(self, generate_report_file=True):
        """Main execution function that fetches and evaluates traces.

        Retrieves traces from Langfuse, evaluates each one against all metrics,
        and uploads the scores back to Langfuse.

        Args:
            generate_report_file: Whether to generate a JSON report after evaluation. Defaults to True.
        """
        start_time = time.time()
        traces = self.__fetch_traces()  # Fetch traces from Langfuse
        self.report["total_traces"] = len(traces)

        trace_results = {}

        # Iterate through each trace and evaluate it
        for trace in tqdm(traces, desc="Evaluating traces"):
            trace_id = trace.id
            trace_results[trace_id] = {
                "success": False,
                "metrics_evaluated": 0,
                "metrics_succeeded": 0,
                "metrics_results": {},
            }

            # Apply each metric to the trace
            for metric in tqdm(metrics, desc=f"Applying metrics to trace {trace_id[:8]}...", leave=False):
                metric_name = metric["name"]
                input, output = get_input_output(trace)  # Extract input and output from the trace
                score = await self._run_metric_evaluation(metric, input, output)  # Evaluate the trace

                if score:
                    self._push_to_langfuse(trace, score, metric)  # Push the score to Langfuse
                    update_success_metrics(self.report, trace_id, metric_name, score, trace_results)
                else:
                    update_failure_metrics(self.report, trace_id, metric_name, trace_results)

                trace_results[trace_id]["metrics_evaluated"] += 1

            # Process results for the current trace
            process_trace_results(self.report, trace_id, trace_results, len(metrics))
            sleep(settings.EVALUATION_SLEEP_TIME)  # Sleep to avoid rate limits

        # Calculate evaluation duration and average scores
        self.report["duration_seconds"] = round(time.time() - start_time, 2)
        calculate_avg_scores(self.report)

        # Generate a report file if required
        if generate_report_file:
            generate_report(self.report)

        # Log the evaluation summary
        logger.info(
            "Evaluation completed",
            total_traces=self.report["total_traces"],
            successful_traces=self.report["successful_traces"],
            failed_traces=self.report["failed_traces"],
            duration_seconds=self.report["duration_seconds"],
        )

    def _push_to_langfuse(self, trace: TraceWithDetails, score: ScoreSchema, metric: dict):
        """Push evaluation score to Langfuse.

        Args:
            trace: The trace to score.
            score: The evaluation score.
            metric: The metric used for evaluation.
        """
        self.langfuse.create_score(
            trace_id=trace.id,
            name=metric["name"],
            data_type="NUMERIC",
            value=score.score,
            comment=score.reasoning,
        )

    @staticmethod
    def _extract_json_object(content: str) -> Optional[dict[str, Any]]:
        """Extract a JSON object from a model response."""
        if not content:
            return None

        content = content.strip()
        candidates = [content]

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            candidates.append(content[first_brace : last_brace + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        return None

    @staticmethod
    def _parse_score_response(content: str) -> ScoreSchema | None:
        """Parse a score object returned by the evaluation model."""
        parsed = Evaluator._extract_json_object(content)
        if not parsed:
            logger.error("Failed to parse evaluation response as JSON", content=content)
            return None

        try:
            return ScoreSchema.model_validate(parsed)
        except Exception as e:
            logger.error("Failed to validate evaluation score schema", error=str(e), parsed=parsed)
            return None

    async def _run_metric_evaluation(
        self, metric: dict, input: Optional[str], output: Optional[str]
    ) -> ScoreSchema | None:
        """Evaluate a single trace against a specific metric.

        Args:
            metric: The metric definition to use for evaluation.
            input: The input to evaluate.
            output: The output to evaluate.

        Returns:
            ScoreSchema with evaluation results or None if evaluation failed.
        """
        metric_name = metric["name"]
        if not metric:
            logger.error(f"Metric {metric_name} not found")
            return None
        system_metric_prompt = metric["prompt"]

        # Validate input and output
        if not input or not output:
            logger.error(f"Metric {metric_name} evaluation failed", input=input, output=output)
            return None

        # Call the evaluation model API to evaluate the trace
        score = await self._call_evaluation_llm(system_metric_prompt, input, output)
        if score:
            logger.info(f"Metric {metric_name} evaluation completed successfully", score=score)
        else:
            logger.error(f"Metric {metric_name} evaluation failed")
        return score

    async def _call_evaluation_llm(self, metric_system_prompt: str, input: str, output: str) -> ScoreSchema | None:
        """Call the evaluation model API to evaluate a trace.

        Args:
            metric_system_prompt: System prompt defining the evaluation metric.
            input: Formatted input messages.
            output: Formatted output message.

        Returns:
            ScoreSchema with evaluation results or None if API call failed.
        """
        num_retries = 3  # Number of retries for API call
        for _ in range(num_retries):
            try:
                # Call the configured evaluation API with the provided prompt, input, and output
                evaluation_messages: Any = [
                    {
                        "role": "system",
                        "content": (
                            f"{metric_system_prompt}\n\n"
                            "Return strictly valid JSON with this shape: "
                            '{"score": <float between 0 and 1>, "reasoning": "<one sentence>"}. '
                            "Do not include markdown fences or any extra text."
                        ),
                    },
                    {"role": "user", "content": f"Input: {input}\nGeneration: {output}"},
                ]
                response = await self.client.chat.completions.create(
                    model=settings.EVALUATION_LLM,
                    messages=evaluation_messages,
                    temperature=0,
                )
                message_content = response.choices[0].message.content or ""
                parsed_score = self._parse_score_response(message_content)
                if parsed_score:
                    return parsed_score
            except Exception as e:
                SLEEP_TIME = 10
                logger.error("Error calling evaluation llm", error=str(e), sleep_time=SLEEP_TIME)
                sleep(SLEEP_TIME)  # Sleep before retrying
                continue
        return None

    def __fetch_traces(self) -> list[TraceWithDetails]:
        """Fetch traces from the past 24 hours without scores.

        Returns:
            List of traces that haven't been scored yet.
        """
        last_24_hours = datetime.now() - timedelta(hours=24)  # Get timestamp for the last 24 hours
        try:
            # Fetch traces from Langfuse API
            traces = self.langfuse.api.trace.list(
                from_timestamp=last_24_hours, order_by="timestamp.asc", limit=100
            ).data
            # Filter traces without scores
            traces_without_scores = [trace for trace in traces if not trace.scores]
            return traces_without_scores
        except Exception as e:
            logger.error("Error fetching traces", error=str(e))
            return []
