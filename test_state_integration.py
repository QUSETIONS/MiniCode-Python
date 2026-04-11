"""Test script for Store state management integration."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minicode.state import create_app_store, AppState, increment_tool_calls, add_cost, set_busy, set_idle
from minicode.state_integration import get_global_store, set_global_store, track_api_call, track_tool_call, track_tool_completion


def test_store_basic():
    """Test basic Store functionality."""
    print("Testing Store basic functionality...")
    
    # Create a store
    store = create_app_store(initial={"session_id": "test-123", "model": "claude-sonnet-4"})
    state = store.get_state()
    
    print(f"Initial state: session_id={state.session_id}, model={state.model}")
    assert state.session_id == "test-123"
    assert state.model == "claude-sonnet-4"
    assert state.tool_call_count == 0
    assert state.total_cost_usd == 0.0
    
    # Update state with tool call
    store.set_state(increment_tool_calls())
    state = store.get_state()
    print(f"After tool call: tool_call_count={state.tool_call_count}")
    assert state.tool_call_count == 1
    
    # Update state with cost
    store.set_state(add_cost(0.05))
    state = store.get_state()
    print(f"After cost addition: total_cost_usd={state.total_cost_usd:.4f}")
    assert abs(state.total_cost_usd - 0.05) < 0.001
    
    # Test busy/idle states
    store.set_state(set_busy("test_tool"))
    state = store.get_state()
    print(f"Busy state: is_busy={state.is_busy}, active_tool={state.active_tool}")
    assert state.is_busy is True
    assert state.active_tool == "test_tool"
    
    store.set_state(set_idle())
    state = store.get_state()
    print(f"Idle state: is_busy={state.is_busy}, active_tool={state.active_tool}")
    assert state.is_busy is False
    assert state.active_tool is None
    
    print("[OK] Basic Store tests passed\n")


def test_global_store():
    """Test global store singleton."""
    print("Testing global store singleton...")
    
    # Get global store (should create one)
    store1 = get_global_store()
    print(f"Store1 update count: {store1.update_count}")
    
    # Create a new store and set it as global
    new_store = create_app_store(initial={"session_id": "global-test"})
    set_global_store(new_store)
    
    # Get global store again (should be the new one)
    store2 = get_global_store()
    state = store2.get_state()
    print(f"Store2 session_id: {state.session_id}")
    assert state.session_id == "global-test"
    
    print("[OK] Global store tests passed\n")


def test_tracking_functions():
    """Test tracking helper functions."""
    print("Testing tracking helper functions...")
    
    # Reset global store
    from minicode.state_integration import reset_state
    reset_state()
    store = get_global_store()
    
    # Track API call
    cost = track_api_call("claude-sonnet-4", 1000, 500)
    state = store.get_state()
    print(f"API tracking: cost=${cost:.4f}, total_cost=${state.total_cost_usd:.4f}, tokens={state.token_usage}")
    assert state.total_cost_usd > 0
    assert state.token_usage == 1500
    
    # Track tool call
    track_tool_call("test_tool")
    state = store.get_state()
    print(f"Tool call tracking: is_busy={state.is_busy}, active_tool={state.active_tool}")
    assert state.is_busy is True
    assert state.active_tool == "test_tool"
    assert state.tool_call_count == 1
    
    # Track tool completion
    track_tool_completion()
    state = store.get_state()
    print(f"Tool completion: is_busy={state.is_busy}, active_tool={state.active_tool}")
    assert state.is_busy is False
    assert state.active_tool is None
    
    print("[OK] Tracking functions tests passed\n")


def test_state_summary():
    """Test state summary formatting."""
    print("Testing state summary formatting...")
    
    from minicode.state_integration import get_state_summary, get_cost_summary, reset_state
    
    # Reset and setup test state
    reset_state()
    store = get_global_store()
    
    # Add some data
    store.set_state(lambda s: AppState(
        session_id="summary-test",
        workspace=s.workspace,
        model="claude-sonnet-4",
        message_count=s.message_count,
        tool_call_count=5,
        token_usage=1500,
        context_window_size=s.context_window_size,
        context_usage_percentage=s.context_usage_percentage,
        total_cost_usd=0.1234,
        api_calls=3,
        api_errors=1,
        active_tasks=s.active_tasks,
        completed_tasks=s.completed_tasks,
        is_busy=s.is_busy,
        active_tool=s.active_tool,
        status_message=s.status_message,
        verbose=s.verbose,
        skills_enabled=s.skills_enabled,
        mcp_enabled=s.mcp_enabled,
        created_at=s.created_at,
        last_updated=s.last_updated,
        metadata=s.metadata.copy(),
    ))
    
    # Get summaries
    state_summary = get_state_summary()
    cost_summary = get_cost_summary()
    
    print("State Summary:")
    print(state_summary)
    print("\nCost Summary:")
    print(cost_summary)
    
    # Check that summaries contain expected data
    assert "summary-" in state_summary  # Only first 8 chars of session_id are shown
    assert "claude-sonnet-4" in state_summary
    assert "$0.1234" in cost_summary
    assert "1,500" in cost_summary
    
    print("[OK] State summary tests passed\n")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Store State Management Integration")
    print("=" * 60)
    
    try:
        test_store_basic()
        test_global_store()
        test_tracking_functions()
        test_state_summary()
        
        print("=" * 60)
        print("All tests passed! [OK]")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())