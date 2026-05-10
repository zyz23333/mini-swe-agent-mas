


from .helpers import _child_metadata


def test_mas_command_result_formatter_owns_success_and_error_shapes():
    from minisweagent.mas.agent_interactions import ChildWaitResult
    from minisweagent.mas.commands import MasCommandResultFormatter

    formatter = MasCommandResultFormatter()
    children = [
        _child_metadata("mas-0123456789abcdef-c001", task="task A"),
        _child_metadata("mas-0123456789abcdef-c002", task="task B"),
    ]
    ready_snapshot = {
        "root_workflow_id": "mas-0123456789abcdef",
        "workflow_id": "mas-0123456789abcdef-c001",
        "lifecycle_state": "waiting_for_parent",
        "latest_submission": "ready",
        "run_directory": ".mini-mas/runs/mas-0123456789abcdef",
        "trajectory_artifact_path": (
            ".mini-mas/runs/mas-0123456789abcdef/trajectories/mas-0123456789abcdef-c001.traj.json"
        ),
    }

    spawn_result = formatter.spawn_waited(
        mas_command=["spawn", "task A", "task B"],
        children=children,
        wait_result=ChildWaitResult(
            children=children,
            ready_snapshots=[ready_snapshot],
            still_running_ids=["mas-0123456789abcdef-c002"],
            timed_out=True,
            wait_mode="all",
        ),
    )

    assert set(spawn_result) == {"output", "returncode", "exception_info", "extra"}
    assert spawn_result["returncode"] == 0
    assert spawn_result["exception_info"] == ""
    assert "Waited spawn timed out" in spawn_result["output"]
    assert "ready_agent_id: mas-0123456789abcdef-c001" in spawn_result["output"]
    assert "still_running_child_agent_ids: mas-0123456789abcdef-c002" in spawn_result["output"]
    assert spawn_result["extra"]["mas_command"] == ["spawn", "task A", "task B"]
    assert spawn_result["extra"]["spawned_child_count"] == 2
    assert spawn_result["extra"]["ready_children"] == [ready_snapshot]
    assert spawn_result["extra"]["child_agent_ids"] == [
        "mas-0123456789abcdef-c001",
        "mas-0123456789abcdef-c002",
    ]
    assert spawn_result["extra"]["still_running_child_agent_ids"] == ["mas-0123456789abcdef-c002"]

    signal = {
        "type": "continuation",
        "signal_type": "mas_continuation",
        "content": "please revise",
        "source_workflow_id": "mas-0123456789abcdef",
        "target_workflow_id": "mas-0123456789abcdef-c001",
    }
    continue_result = formatter.continuation_sent(
        mas_command=["continue", "mas-0123456789abcdef-c001", "please revise"],
        target_workflow_id="mas-0123456789abcdef-c001",
        content="please revise",
        target_status=ready_snapshot,
        signal=signal,
    )

    assert "Continuation signal sent" in continue_result["output"]
    assert "message: please revise" in continue_result["output"]
    assert "agent_id: mas-0123456789abcdef-c001" in continue_result["output"]
    assert continue_result["extra"]["continued_agent_id"] == "mas-0123456789abcdef-c001"
    assert continue_result["extra"]["target_status"] == ready_snapshot
    assert continue_result["extra"]["continuation_signal"] == signal

    close_result = formatter.close_sent(
        mas_command=["close", "mas-0123456789abcdef-c001"],
        target_workflow_id="mas-0123456789abcdef-c001",
        target_status=ready_snapshot,
        signal={
            "type": "close",
            "signal_type": "mas_close",
            "source_workflow_id": "mas-0123456789abcdef",
            "target_workflow_id": "mas-0123456789abcdef-c001",
        },
    )

    assert "Close signal sent" in close_result["output"]
    assert "latest_submission: ready" in close_result["output"]
    assert "agent_id: mas-0123456789abcdef-c001" in close_result["output"]
    assert close_result["extra"]["closed_agent_id"] == "mas-0123456789abcdef-c001"
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
