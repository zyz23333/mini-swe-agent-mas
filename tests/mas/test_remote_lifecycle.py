from unittest.mock import Mock

from minisweagent.mas.signals import (
    continuation_user_message,
    is_close_signal,
    is_continuation_signal,
    make_continuation_signal,
)


def test_remote_interactive_lifecycle_is_isolated_from_mas_agent_loop():
    import minisweagent.mas.mas_agent as workflows
    import minisweagent.mas.remote_lifecycle as remote_lifecycle

    lifecycle = remote_lifecycle.RemoteInteractiveAgentLifecycle(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef-c001",
    )
    agent = workflows.MasAgent(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef-c001",
        model=Mock(),
        env=Mock(),
        step_limit=3,
    )

    signal = make_continuation_signal(
        source_workflow_id="mas-0123456789abcdef",
        target_workflow_id="mas-0123456789abcdef-c001",
        content="continue",
    )

    assert agent.remote_lifecycle.root_workflow_id == "mas-0123456789abcdef"
    assert agent.remote_lifecycle.workflow_id == "mas-0123456789abcdef-c001"
    assert signal["target_workflow_id"] == "mas-0123456789abcdef-c001"
    assert is_continuation_signal({"signal_type": "mas_continuation"})
    assert is_close_signal({"signal_type": "mas_close"})
    assert callable(lifecycle.wait_after_submission)
    assert callable(lifecycle.close_after_parent_signal)
    assert continuation_user_message(
        Mock(format_message=Mock(return_value={"role": "user"})),
        {"signal_type": "mas_continuation"},
    ) == {"role": "user"}
