"""
AI agent layer: query + control copilot for the home IoT devices.

Submodules:
    tuya_control — lifts the Tuya device-control mechanism (from the
        blink_led_example notebook) into a reusable, dry-run-safe function.
    tools         — the three tool functions exposed to the agent
        (query_iot_data, get_device_state, control_device).
    agent         — the orchestrator that wires tools + system prompt into
        the Anthropic Tool Runner.
"""
