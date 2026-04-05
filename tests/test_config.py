from minicode.config import merge_settings


def test_merge_settings_merges_env_and_mcp_servers() -> None:
    merged = merge_settings(
        {
            "env": {"A": "1"},
            "mcpServers": {
                "fs": {"command": "npx", "args": ["a"], "env": {"X": "1"}}
            },
        },
        {
            "env": {"B": "2"},
            "mcpServers": {
                "fs": {"command": "uvx", "env": {"Y": "2"}},
                "search": {"command": "python"},
            },
        },
    )

    assert merged["env"] == {"A": "1", "B": "2"}
    assert merged["mcpServers"]["fs"]["command"] == "uvx"
    assert merged["mcpServers"]["fs"]["args"] == ["a"]
    assert merged["mcpServers"]["fs"]["env"] == {"X": "1", "Y": "2"}
    assert merged["mcpServers"]["search"]["command"] == "python"

