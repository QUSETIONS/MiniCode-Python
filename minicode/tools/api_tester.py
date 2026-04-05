from __future__ import annotations

import json
import urllib.request
import urllib.error
import time
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# API Tester Helpers
# ---------------------------------------------------------------------------

def _format_headers(headers: dict[str, str]) -> str:
    """Format headers for display."""
    if not headers:
        return ""
    return "\n".join(f"  {k}: {v}" for k, v in headers.items())


def _format_body(body: Any, content_type: str = "") -> str:
    """Format request/response body for display."""
    if body is None:
        return ""
    
    if isinstance(body, (dict, list)):
        return json.dumps(body, indent=2, ensure_ascii=False)
    
    if isinstance(body, str):
        # Try to parse as JSON
        try:
            parsed = json.loads(body)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return body[:1000]
    
    return str(body)[:1000]


def _build_request(method: str, url: str, headers: dict, body: Any, auth: dict | None = None) -> urllib.request.Request:
    """Build HTTP request with all options."""
    # Prepare body
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
    else:
        data = None
    
    # Add authentication
    if auth:
        auth_type = auth.get("type", "bearer")
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {auth.get('token', '')}"
        elif auth_type == "basic":
            import base64
            credentials = f"{auth.get('username', '')}:{auth.get('password', '')}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif auth_type == "api_key":
            key_name = auth.get("key_name", "X-API-Key")
            headers[key_name] = auth.get("key", "")
    
    # Build request
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    return req


def _validate_response(response_text: str, expected_schema: dict | None = None) -> dict[str, Any]:
    """Validate response against expected schema."""
    validation_result = {"valid": True, "errors": []}
    
    # Check if response is valid JSON
    try:
        parsed = json.loads(response_text)
        validation_result["is_json"] = True
        validation_result["parsed"] = parsed
    except (json.JSONDecodeError, TypeError):
        validation_result["is_json"] = False
        validation_result["errors"].append("Response is not valid JSON")
        return validation_result
    
    # Validate against schema if provided
    if expected_schema:
        for key, expected_type in expected_schema.items():
            if key not in parsed:
                validation_result["errors"].append(f"Missing required field: {key}")
                validation_result["valid"] = False
            else:
                actual_type = type(parsed[key]).__name__
                if actual_type != expected_type:
                    validation_result["errors"].append(
                        f"Field '{key}': expected {expected_type}, got {actual_type}"
                    )
                    validation_result["valid"] = False
    
    return validation_result


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    method = input_data.get("method", "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        raise ValueError(f"method must be one of: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
    
    url = input_data.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("url is required")
    
    headers = input_data.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError("headers must be a dictionary")
    
    body = input_data.get("body")
    auth = input_data.get("auth")
    if auth and not isinstance(auth, dict):
        raise ValueError("auth must be a dictionary")
    
    expected_status = int(input_data.get("expected_status", 200))
    expected_schema = input_data.get("expected_schema")
    timeout = int(input_data.get("timeout", 30))
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be between 1 and 120 seconds")
    
    return {
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
        "auth": auth,
        "expected_status": expected_status,
        "expected_schema": expected_schema,
        "timeout": timeout,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Test API endpoint."""
    method = input_data["method"]
    url = input_data["url"]
    headers = input_data["headers"]
    body = input_data["body"]
    auth = input_data["auth"]
    expected_status = input_data["expected_status"]
    expected_schema = input_data.get("expected_schema")
    timeout = input_data["timeout"]
    
    lines = [
        "🔌 API Tester",
        "=" * 60,
        "",
        f"Request:",
        f"  Method: {method}",
        f"  URL: {url}",
    ]
    
    if headers:
        lines.append(f"  Headers:")
        lines.append(_format_headers(headers))
    
    if auth:
        lines.append(f"  Auth: {auth.get('type', 'unknown')}")
    
    if body:
        lines.append(f"  Body:")
        lines.append(_format_body(body))
    
    lines.append("")
    lines.append("-" * 60)
    lines.append("")
    
    # Build and send request
    start_time = time.time()
    
    try:
        req = _build_request(method, url, headers.copy(), body, auth)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.status
            response_headers = dict(response.headers)
            response_body = response.read().decode("utf-8", errors="replace")
            
    except urllib.error.HTTPError as e:
        status_code = e.code
        response_headers = dict(e.headers) if hasattr(e, 'headers') else {}
        try:
            response_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            response_body = str(e.reason)
    except urllib.error.URLError as e:
        return ToolResult(
            ok=False,
            output="\n".join(lines) + f"❌ Request failed: {e.reason}\n\nURL: {url}",
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            output="\n".join(lines) + f"❌ Error: {e}\n\nURL: {url}",
        )
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    
    # Format response
    lines.append(f"Response:")
    lines.append(f"  Status: {status_code} {'✓' if status_code == expected_status else '✗ (expected ' + str(expected_status) + ')'}")
    lines.append(f"  Time: {elapsed_ms}ms")
    lines.append("")
    
    if response_headers:
        content_type = response_headers.get("Content-Type", "")
        content_length = response_headers.get("Content-Length", "")
        lines.append(f"  Headers:")
        if content_type:
            lines.append(f"    Content-Type: {content_type}")
        if content_length:
            lines.append(f"    Content-Length: {content_length}")
    
    # Parse and validate response body
    if response_body:
        validation = _validate_response(response_body, expected_schema)
        
        if validation.get("is_json"):
            lines.append("")
            lines.append(f"  Response Body (JSON):")
            lines.append(_format_body(validation.get("parsed", response_body)))
            
            if expected_schema:
                lines.append("")
                if validation["valid"]:
                    lines.append(f"  ✓ Schema validation passed")
                else:
                    lines.append(f"  ✗ Schema validation failed:")
                    for error in validation["errors"]:
                        lines.append(f"    - {error}")
        else:
            lines.append("")
            lines.append(f"  Response Body:")
            lines.append(response_body[:2000])
            if len(response_body) > 2000:
                lines.append(f"\n  ... (truncated)")
    
    # Final verdict
    lines.append("")
    lines.append("-" * 60)
    lines.append("")
    
    status_ok = status_code == expected_status
    schema_ok = not expected_schema or validation.get("valid", True)
    
    if status_ok and schema_ok:
        lines.append("✅ API test passed!")
    else:
        lines.append("❌ API test failed:")
        if not status_ok:
            lines.append(f"  - Expected status {expected_status}, got {status_code}")
        if not schema_ok:
            lines.append(f"  - Schema validation failed")
    
    return ToolResult(
        ok=status_ok and schema_ok,
        output="\n".join(lines),
    )


api_tester_tool = ToolDefinition(
    name="api_tester",
    description="Test HTTP API endpoints with full request/response inspection. Supports all HTTP methods, authentication, body validation, and schema checking.",
    input_schema={
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], "description": "HTTP method (default: GET)"},
            "url": {"type": "string", "description": "API endpoint URL"},
            "headers": {"type": "object", "description": "Request headers"},
            "body": {"description": "Request body (dict, list, or string)"},
            "auth": {
                "type": "object",
                "description": "Authentication config: {type: 'bearer'|'basic'|'api_key', ...}",
                "properties": {
                    "type": {"type": "string"},
                    "token": {"type": "string"},
                    "username": {"type": "string"},
                    "password": {"type": "string"},
                    "key": {"type": "string"},
                    "key_name": {"type": "string"},
                },
            },
            "expected_status": {"type": "number", "description": "Expected HTTP status code (default: 200)"},
            "expected_schema": {"type": "object", "description": "Expected response schema as {field: type} map"},
            "timeout": {"type": "number", "description": "Request timeout in seconds (default: 30)"},
        },
        "required": ["url"],
    },
    validator=_validate,
    run=_run,
)
