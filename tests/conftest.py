# -*- coding: utf-8 -*-
import os
import socket

import pytest

from ableton_agent import core


MANAGED_VARS = ("OPENAI_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "GPT_MODEL",
                "ABLETON_BRIDGE_HOST", "ABLETON_BRIDGE_PORT")


@pytest.fixture(autouse=True)
def isolate_env():
    """Never hit a real LLM or a real Live from the test suite."""
    saved = {var: os.environ.pop(var, None) for var in MANAGED_VARS}
    original_port = core.UDP_PORT
    try:
        yield
    finally:
        core.UDP_PORT = original_port
        for var, value in saved.items():
            os.environ.pop(var, None)
            if value is not None:
                os.environ[var] = value


@pytest.fixture
def unused_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def live(unused_udp_port):
    """A fake Ableton Live running the real remote script, wired to core."""
    from ableton_agent.simulator import LiveSimulator

    sim = LiveSimulator(port=unused_udp_port).start()
    core.UDP_PORT = unused_udp_port
    try:
        yield sim
    finally:
        sim.stop()
