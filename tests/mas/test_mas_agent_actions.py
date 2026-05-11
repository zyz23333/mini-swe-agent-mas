import asyncio
from unittest.mock import Mock

import pytest

from minisweagent.mas.signals import (
    PARENT_DIRECTION_TOPIC,
)
from minisweagent.models.test_models import (
    DeterministicModel,
    DeterministicResponseAPIToolcallModel,
    DeterministicToolcallModel,
    make_output,
    make_response_api_output,
    make_toolcall_output,
)

from .helpers import (
    _mock_single_direct_child_status,
    _observation_text,
    _set_agent_workflow_context,
)


def test_workflow_action_execution_dispatches_standalone_mas_commands():
    from minisweagent.mas.mas_agent import execute_agent_workflow_actions

    message = make_output("dispatch", [{"command": "mini-mas wait --any"}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert len(observations) == 1
    assert "mini-mas wait requires Agent context" in _observation_text(observations[0])

def test_workflow_action_execution_keeps_ordinary_bash_on_bash_path():
    from minisweagent.mas.mas_agent import execute_agent_workflow_actions

    message = make_output("bash", [{"command": "echo hello"}])
    env = Mock()
    env.execute.return_value = {"output": "hello\n", "returncode": 0, "exception_info": ""}
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_called_once_with({"command": "echo hello"})
    assert "<returncode>0</returncode>" in _observation_text(observations[0])
    assert "hello" in _observation_text(observations[0])

@pytest.mark.parametrize(
    "command",
    [
        "echo before && mini-mas status",
        "mini-mas status | cat",
        "DEBUG=1 mini-mas status",
        "for x in 1; do mini-mas status; done",
    ],
)
def test_workflow_action_execution_rejects_shell_compositions_without_executing_bash(command):
    from minisweagent.mas.mas_agent import execute_agent_workflow_actions

    message = make_output("reject", [{"command": command}])
    env = Mock()
    model = DeterministicModel(outputs=[])

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    text = _observation_text(observations[0])
    assert "<returncode>2</returncode>" in text
    assert "mini-mas must be issued as a standalone command" in text

@pytest.mark.parametrize(
    ("model", "message", "expected_marker"),
    [
        (
            DeterministicModel(outputs=[]),
            make_output("text", [{"command": "mini-mas status && echo no"}]),
            "role",
        ),
        (
            DeterministicToolcallModel(outputs=[]),
            make_toolcall_output(
                "tool",
                [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "mini-mas status && echo no"}'},
                    }
                ],
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_0"}],
            ),
            "tool_call_id",
        ),
        (
            DeterministicResponseAPIToolcallModel(outputs=[]),
            make_response_api_output(
                "responses",
                [{"command": "mini-mas status && echo no", "tool_call_id": "call_resp_0"}],
            ),
            "call_id",
        ),
    ],
)
def test_mas_rejections_use_existing_model_specific_observation_formatters(model, message, expected_marker):
    from minisweagent.mas.mas_agent import execute_agent_workflow_actions

    env = Mock()

    observations = asyncio.run(execute_agent_workflow_actions(message=message, model=model, env=env, template_vars={}))

    env.execute.assert_not_called()
    assert expected_marker in observations[0]
    assert "mini-mas must be issued as a standalone command" in _observation_text(observations[0])

@pytest.mark.parametrize(
    ("model", "message", "expected_marker"),
    [
        (
            DeterministicModel(outputs=[]),
            make_output("continue", [{"command": 'mini-mas continue mas-1111111111111111 "go on"'}]),
            "role",
        ),
        (
            DeterministicToolcallModel(outputs=[]),
            make_toolcall_output(
                "tool",
                [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": '{"command": "mini-mas continue mas-1111111111111111 \\"go on\\""}',
                        },
                    }
                ],
                [{"command": 'mini-mas continue mas-1111111111111111 "go on"', "tool_call_id": "call_0"}],
            ),
            "tool_call_id",
        ),
        (
            DeterministicResponseAPIToolcallModel(outputs=[]),
            make_response_api_output(
                "responses",
                [{"command": 'mini-mas continue mas-1111111111111111 "go on"', "tool_call_id": "call_resp_0"}],
            ),
            "call_id",
        ),
    ],
)
def test_mas_continue_uses_existing_model_specific_observation_formatters(monkeypatch, model, message, expected_marker):
    import minisweagent.mas.mas_agent as workflows

    _set_agent_workflow_context(monkeypatch, workflows, "mas-0123456789abcdef")
    _mock_single_direct_child_status(
        monkeypatch,
        workflows,
        "mas-0123456789abcdef",
        {
            "agent_id": "mas-1111111111111111",
            "parent_agent_id": "mas-0123456789abcdef",
            "lifecycle_state": "waiting_for_parent",
            "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
            "trajectory_artifact_path": (
                ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
            ),
        },
    )

    async def send_async(_destination_id, _message, topic=None):
        assert topic == PARENT_DIRECTION_TOPIC

    monkeypatch.setattr(workflows._dbos.DBOS, "send_async", Mock(side_effect=send_async))

    observations = asyncio.run(
        workflows.execute_agent_workflow_actions(
            message=message,
            model=model,
            env=Mock(),
            template_vars={
                "parent_agent_id": "mas-0123456789abcdef",
                "agent_id": "mas-0123456789abcdef",
            },
        )
    )

    assert expected_marker in observations[0]
    assert "Continuation signal sent" in _observation_text(observations[0])
