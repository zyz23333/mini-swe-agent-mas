from minisweagent.mas.signals import (
    continuation_user_message,
    is_close_signal,
    is_continuation_signal,
    make_continuation_signal,
)


def test_remote_interactive_lifecycle_behavior_is_owned_by_mas_agent():
    import minisweagent.mas.mas_agent as workflows

    try:
        import minisweagent.mas.remote_lifecycle as remote_lifecycle
    except ModuleNotFoundError:
        remote_lifecycle = None

    agent = workflows.MasAgent(
        root_workflow_id="mas-0123456789abcdef",
        workflow_id="mas-0123456789abcdef-c001",
        model=None,
        env=None,
        step_limit=3,
    )

    signal = make_continuation_signal(
        source_workflow_id="mas-0123456789abcdef",
        target_workflow_id="mas-0123456789abcdef-c001",
        content="continue",
    )

    assert not hasattr(agent, "remote_lifecycle")
    assert callable(agent._should_wait_for_parent_after_submission)
    assert callable(agent._wait_for_parent_after_submission)
    assert callable(agent._close_after_parent_signal)
    if remote_lifecycle is not None:
        assert not hasattr(remote_lifecycle, "RemoteInteractiveAgentLifecycle")
    assert signal["target_workflow_id"] == "mas-0123456789abcdef-c001"
    assert is_continuation_signal({"signal_type": "mas_continuation"})
    assert is_close_signal({"signal_type": "mas_close"})

    class MessageFormattingModel:
        def format_message(self, *, role, content, extra):
            return {"role": role, "content": content, "extra": extra}

    assert continuation_user_message(
        MessageFormattingModel(),
        {"signal_type": "mas_continuation", "content": "continue"},
    ) == {
        "role": "user",
        "content": "continue",
        "extra": {
            "mas": {
                "signal_type": "mas_continuation",
                "source_workflow_id": "",
                "target_workflow_id": "",
            }
        },
    }
