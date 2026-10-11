"""Optional live integration smoke test for genuine Pi Coding Agent execution.

This test is SKIPPED by default. It executes only when the user explicitly provides:
    RUN_LIVE_PI_TEST=1
in the environment, and requires:
    1. Pi Coding Agent installed in agent_runtime/ (cd agent_runtime && npm install)
    2. Local Ollama service running on http://127.0.0.1:11434 with model qwen2.5:1.5b
"""

import asyncio
import os
import pytest

from backend.app.agent.pi_client import PiClient

RUN_LIVE = os.getenv("RUN_LIVE_PI_TEST", "").strip() in ("1", "true", "yes")


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="Live Pi integration test skipped by default. Run with RUN_LIVE_PI_TEST=1 after installing agent_runtime dependencies and starting Ollama.",
)
@pytest.mark.asyncio
async def test_live_pi_ollama_generation_smoke():
    """Execute a genuine generation turn through the live Pi Coding Agent subprocess."""
    client = PiClient()
    prompt = "In 2 sentences, what is the single most important metric for B2B SaaS retention?"

    result = await client.generate_response(
        prompt=prompt,
        provider="ollama",
        model="qwen2.5:1.5b",
        timeout_seconds=60,
    )

    assert result.text is not None
    assert len(result.text.strip()) > 0
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:1.5b"

    # Allow Windows Proactor event loop to settle residual I/O callbacks before test teardown
    await asyncio.sleep(0.01)
