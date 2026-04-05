from minicode.mock_model import MockModelAdapter


def test_mock_model_turns_ls_into_tool_call() -> None:
    adapter = MockModelAdapter()
    step = adapter.next([{"role": "user", "content": "/ls src"}])

    assert step.type == "tool_calls"
    assert step.calls[0]["toolName"] == "list_files"
    assert step.calls[0]["input"] == {"path": "src"}


def test_mock_model_reacts_to_tool_result() -> None:
    adapter = MockModelAdapter()
    step = adapter.next(
        [
            {"role": "user", "content": "/read README.md"},
            {"role": "assistant_tool_call", "toolUseId": "1", "toolName": "read_file", "input": {"path": "README.md"}},
            {"role": "tool_result", "toolUseId": "1", "toolName": "read_file", "content": "FILE: README.md", "isError": False},
        ]
    )

    assert step.type == "assistant"
    assert "README.md" in step.content


def test_mock_model_default_message_is_readable() -> None:
    adapter = MockModelAdapter()
    step = adapter.next([{"role": "user", "content": "hello"}])

    assert step.type == "assistant"
    assert "minimal MiniCode Python shell" in step.content
