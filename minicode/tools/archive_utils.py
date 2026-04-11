from __future__ import annotations

import gzip
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

from minicode.tooling import ToolDefinition, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# Gzip Compress
# ---------------------------------------------------------------------------

def _validate_gzip_compress(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip()}


def _run_gzip_compress(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        if source.is_file():
            with open(source, "rb") as f_in:
                with gzip.open(destination, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            return ToolResult(ok=True, output=f"Compressed to {input_data['destination']}")
        else:
            return ToolResult(ok=False, output="Use tar_archive for directories")
    except Exception as e:
        return ToolResult(ok=False, output=f"Compression error: {e}")


gzip_compress_tool = ToolDefinition(
    name="gzip_compress",
    description="Compress a file using gzip.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source file (relative to workspace)"},
            "destination": {"type": "string", "description": "Output .gz file path"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_gzip_compress,
    run=_run_gzip_compress,
)


# ---------------------------------------------------------------------------
# Gzip Decompress
# ---------------------------------------------------------------------------

def _validate_gzip_decompress(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip()}


def _run_gzip_decompress(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        with gzip.open(source, "rb") as f_in:
            with open(destination, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return ToolResult(ok=True, output=f"Decompressed to {input_data['destination']}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Decompression error: {e}")


gzip_decompress_tool = ToolDefinition(
    name="gzip_decompress",
    description="Decompress a .gz file.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source .gz file"},
            "destination": {"type": "string", "description": "Output file path"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_gzip_decompress,
    run=_run_gzip_decompress,
)


# ---------------------------------------------------------------------------
# Tar Archive
# ---------------------------------------------------------------------------

def _validate_tar_create(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    mode = input_data.get("mode", "gz")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip(), "mode": mode}


def _run_tar_create(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    mode = input_data.get("mode", "gz")
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        # Determine mode
        if mode == "gz":
            tar_mode = "w:gz"
            ext = ".tar.gz"
        elif mode == "bz2":
            tar_mode = "w:bz2"
            ext = ".tar.bz2"
        elif mode == "xz":
            tar_mode = "w:xz"
            ext = ".tar.xz"
        else:
            tar_mode = "w"
            ext = ".tar"
        
        # Ensure destination has correct extension
        if not str(destination).endswith(ext):
            destination = Path(str(destination) + ext)
        
        with tarfile.open(destination, tar_mode) as tar:
            tar.add(source, arcname=source.name)
        
        return ToolResult(ok=True, output=f"Created {destination.name}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Archive error: {e}")


tar_create_tool = ToolDefinition(
    name="tar_create",
    description="Create tar archive (optionally compressed with gz, bz2, or xz).",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "File or directory to archive"},
            "destination": {"type": "string", "description": "Output archive path"},
            "mode": {"type": "string", "description": "Compression: gz, bz2, xz, or none"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_tar_create,
    run=_run_tar_create,
)


# ---------------------------------------------------------------------------
# Tar Extract
# ---------------------------------------------------------------------------

def _validate_tar_extract(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    return {"source": source.strip(), "destination": destination.strip() if destination else ""}


def _run_tar_extract(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    dest_dir = input_data.get("destination", "")
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        if dest_dir:
            destination = Path(context.cwd) / dest_dir
        else:
            # Extract to same directory as archive
            destination = source.parent / source.stem
        
        destination.mkdir(parents=True, exist_ok=True)
        
        with tarfile.open(source, "r:*") as tar:
            tar.extractall(destination)
        
        return ToolResult(ok=True, output=f"Extracted to {destination}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Extract error: {e}")


tar_extract_tool = ToolDefinition(
    name="tar_extract",
    description="Extract tar archive.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Archive file to extract"},
            "destination": {"type": "string", "description": "Output directory (optional)"}
        },
        "required": ["source"]
    },
    validator=_validate_tar_extract,
    run=_run_tar_extract,
)


# ---------------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------------

def _validate_zip_create(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("destination is required")
    return {"source": source.strip(), "destination": destination.strip()}


def _run_zip_create(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    destination = Path(context.cwd) / input_data["destination"]
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        if not str(destination).endswith(".zip"):
            destination = Path(str(destination) + ".zip")
        
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
            if source.is_file():
                zf.write(source, source.name)
            else:
                for item in source.rglob("*"):
                    if item.is_file():
                        zf.write(item, item.relative_to(source.parent))
        
        return ToolResult(ok=True, output=f"Created {destination.name}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Zip error: {e}")


zip_create_tool = ToolDefinition(
    name="zip_create",
    description="Create ZIP archive.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "File or directory to archive"},
            "destination": {"type": "string", "description": "Output .zip path"}
        },
        "required": ["source", "destination"]
    },
    validator=_validate_zip_create,
    run=_run_zip_create,
)


# ---------------------------------------------------------------------------
# Zip Extract
# ---------------------------------------------------------------------------

def _validate_zip_extract(input_data: dict) -> dict:
    source = input_data.get("source", "")
    destination = input_data.get("destination", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source is required")
    return {"source": source.strip(), "destination": destination.strip() if destination else ""}


def _run_zip_extract(input_data: dict, context: ToolContext) -> ToolResult:
    source = Path(context.cwd) / input_data["source"]
    dest_dir = input_data.get("destination", "")
    
    if not source.exists():
        return ToolResult(ok=False, output=f"Source not found: {input_data['source']}")
    
    try:
        if dest_dir:
            destination = Path(context.cwd) / dest_dir
        else:
            destination = source.parent / source.stem
        
        destination.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(destination)
        
        return ToolResult(ok=True, output=f"Extracted to {destination}")
    except Exception as e:
        return ToolResult(ok=False, output=f"Extract error: {e}")


zip_extract_tool = ToolDefinition(
    name="zip_extract",
    description="Extract ZIP archive.",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Archive file to extract"},
            "destination": {"type": "string", "description": "Output directory (optional)"}
        },
        "required": ["source"]
    },
    validator=_validate_zip_extract,
    run=_run_zip_extract,
)