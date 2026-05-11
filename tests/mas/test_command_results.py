


from .helpers import _child_metadata


def test_mas_command_result_formatter_owns_success_and_error_shapes():
    from minisweagent.mas.agent_interactions import ChildWaitResult
    from minisweagent.mas.commands import MasCommandResultFormatter

    formatter = MasCommandResultFormatter()
    children = [
        _child_metadata("mas-1111111111111111", task="task A"),
        _child_metadata("mas-2222222222222222", task="task B"),
    ]
    ready_snapshot = {
        "agent_id": "mas-1111111111111111",
        "parent_agent_id": "mas-0123456789abcdef",
        "lifecycle_state": "waiting_for_parent",
        "latest_submission": "ready",
        "agent_artifact_directory": ".mini-mas/agents/mas-1111111111111111",
        "trajectory_artifact_path": (
            ".mini-mas/agents/mas-1111111111111111/trajectory.traj.json"
        ),
    }

    spawn_result = formatter.spawn_waited(
        mas_command=["spawn", "task A", "task B"],
        children=children,
        wait_result=ChildWaitResult(
            children=children,
            ready_snapshots=[ready_snapshot],
            still_running_ids=["mas-2222222222222222"],
            timed_out=True,
            wait_mode="all",
        ),
    )

    assert set(spawn_result) == {"output", "returncode", "exception_info", "extra"}
    assert spawn_result["returncode"] == 0
    assert spawn_result["exception_info"] == ""
    assert "Waited spawn timed out" in spawn_result["output"]
    assert "ready_agent_id: mas-1111111111111111" in spawn_result["output"]
    assert "still_running_child_agent_ids: mas-2222222222222222" in spawn_result["output"]
    assert spawn_result["extra"]["mas_command"] == ["spawn", "task A", "task B"]
    assert spawn_result["extra"]["spawned_child_count"] == 2
    assert spawn_result["extra"]["ready_children"] == [ready_snapshot]
    assert spawn_result["extra"]["child_agent_ids"] == [
        "mas-1111111111111111",
        "mas-2222222222222222",
    ]
    assert spawn_result["extra"]["still_running_child_agent_ids"] == ["mas-2222222222222222"]

    signal = {
        "type": "continuation",
        "signal_type": "mas_continuation",
        "content": "please revise",
        "source_workflow_id": "mas-0123456789abcdef",
        "target_workflow_id": "mas-1111111111111111",
    }
    continue_result = formatter.continuation_sent(
        mas_command=["continue", "mas-1111111111111111", "please revise"],
        target_workflow_id="mas-1111111111111111",
        content="please revise",
        target_status=ready_snapshot,
        signal=signal,
    )

    assert "Continuation signal sent" in continue_result["output"]
    assert "message: please revise" in continue_result["output"]
    assert "agent_id: mas-1111111111111111" in continue_result["output"]
    assert continue_result["extra"]["continued_agent_id"] == "mas-1111111111111111"
    assert continue_result["extra"]["target_status"] == ready_snapshot
    assert continue_result["extra"]["continuation_signal"] == signal

    close_result = formatter.close_sent(
        mas_command=["close", "mas-1111111111111111"],
        target_workflow_id="mas-1111111111111111",
        target_status=ready_snapshot,
        signal={
            "type": "close",
            "signal_type": "mas_close",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-1111111111111111",
        },
    )

    assert "Close signal sent" in close_result["output"]
    assert "latest_submission: ready" in close_result["output"]
    assert "agent_id: mas-1111111111111111" in close_result["output"]
    assert close_result["extra"]["closed_agent_id"] == "mas-1111111111111111"
    assert close_result["extra"]["target_status"] == ready_snapshot

    error_result = formatter.error(
        output="mini-mas wait requires Agent context.\n",
        returncode=2,
        exception_info="missing_agent_context",
        mas_command_error="missing_agent_context",
        mas_command=["wait"],
    )

    assert error_result == {
        "output": "mini-mas wait requires Agent context.\n",
        "returncode": 2,
        "exception_info": "missing_agent_context",
        "extra": {
            "mas_command": ["wait"],
            "mas_command_error": "missing_agent_context",
        },
    }
