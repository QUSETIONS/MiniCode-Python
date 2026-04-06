"""Interactive installer for MiniCode Python.

Configures model, API credentials, and installs launcher script.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from minicode.config import (
    MINI_CODE_DIR,
    MINI_CODE_SETTINGS_PATH,
    load_effective_settings,
    save_mini_code_settings,
)


def _read_input(prompt: str, default: str | None = None) -> str:
    """Read input from user with optional default value."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
        return value or default or ""
    except (EOFError, KeyboardInterrupt):
        print("\n\nInstallation cancelled.")
        sys.exit(0)


def _require_input(prompt: str, default: str | None = None) -> str:
    """Require non-empty input, with optional default."""
    while True:
        value = _read_input(prompt, default)
        if value:
            return value
        print("该项不能为空，请重新输入。")


def _mask_secret(secret: str | None) -> str:
    """Show masked secret status."""
    if not secret:
        return "[not set]"
    return "[saved]"


def _install_launcher_script() -> str | None:
    """Install launcher script to platform-specific bin directory.

    Returns the installation path, or None if skipped.
    """
    home = Path.home()

    # Determine target bin directory and script based on platform
    if sys.platform == "win32":
        # Windows: Use ~/.mini-code/bin with .bat script
        target_bin_dir = MINI_CODE_DIR / "bin"
        launcher_path = target_bin_dir / "minicode.bat"
        python_exe = sys.executable.replace("/", "\\")
        launcher_script = "\r\n".join([
            "@echo off",
            "REM MiniCode Python Launcher for Windows",
            f'"{python_exe}" -m minicode.main %*',
            "",
        ])
        launcher_command = "minicode.bat"
    elif sys.platform == "darwin":
        # macOS: Use ~/.local/bin with bash script (also works with zsh)
        target_bin_dir = home / ".local" / "bin"
        launcher_path = target_bin_dir / "minicode-py"
        python_exe = sys.executable
        launcher_script = "\n".join([
            "#!/usr/bin/env bash",
            "# MiniCode Python Launcher for macOS",
            "# Works with bash, zsh, and other shells",
            "set -euo pipefail",
            f'exec "{python_exe}" -m minicode.main "$@"',
            "",
        ])
        launcher_command = "minicode-py"
    else:
        # Linux: Use ~/.local/bin with bash script
        target_bin_dir = home / ".local" / "bin"
        launcher_path = target_bin_dir / "minicode-py"
        python_exe = sys.executable
        launcher_script = "\n".join([
            "#!/usr/bin/env bash",
            "# MiniCode Python Launcher for Linux",
            "set -euo pipefail",
            f'exec "{python_exe}" -m minicode.main "$@"',
            "",
        ])
        launcher_command = "minicode-py"

    try:
        target_bin_dir.mkdir(parents=True, exist_ok=True)
        launcher_path.write_text(launcher_script, encoding="utf-8")

        # Make executable on Unix-like systems
        if sys.platform != "win32":
            current_permissions = launcher_path.stat().st_mode
            launcher_path.chmod(current_permissions | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        return str(launcher_path), launcher_command, str(target_bin_dir)
    except OSError as e:
        print(f"\n⚠️  无法安装启动器脚本: {e}")
        print("你可以手动创建启动器脚本来调用 minicode。")
        return None


def _check_path_entry(target_dir: str) -> bool:
    """Check if target directory is in PATH."""
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    return target_dir in path_entries


def main() -> None:
    """Run the interactive installer."""
    print("=" * 60)
    print("  MiniCode Python 安装向导")
    print("=" * 60)
    print()
    print(f"配置会写入: {MINI_CODE_SETTINGS_PATH}")
    print("配置保存在独立目录中，不会影响其它本地工具配置。")
    print()
    
    # Load existing settings
    try:
        settings = load_effective_settings()
    except Exception:
        settings = {}
    
    current_env = settings.get("env", {})
    
    # Collect configuration
    print("📋 请输入配置信息：")
    print()
    
    model = _require_input(
        "Model name",
        settings.get("model") or current_env.get("ANTHROPIC_MODEL", ""),
    )
    
    base_url = _require_input(
        "ANTHROPIC_BASE_URL",
        current_env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    )
    
    saved_auth_token = current_env.get("ANTHROPIC_AUTH_TOKEN", "")
    token_input = _read_input(
        f"ANTHROPIC_AUTH_TOKEN",
        None,
    )
    auth_token = token_input or saved_auth_token
    
    if not auth_token and not saved_auth_token:
        print("\n❌ ANTHROPIC_AUTH_TOKEN 不能为空。")
        sys.exit(1)
    
    auth_token = auth_token or saved_auth_token
    
    # Save configuration
    print("\n💾 保存配置...")
    try:
        save_mini_code_settings({
            "model": model,
            "env": {
                "ANTHROPIC_BASE_URL": base_url,
                "ANTHROPIC_AUTH_TOKEN": auth_token,
                "ANTHROPIC_MODEL": model,
            },
        })
        print(f"✅ 配置已保存到: {MINI_CODE_SETTINGS_PATH}")
    except OSError as e:
        print(f"\n❌ 保存配置失败: {e}")
        sys.exit(1)
    
    # Install launcher script
    print("\n🚀 安装启动器...")
    launcher_result = _install_launcher_script()

    if launcher_result:
        launcher_path, launcher_command, target_bin_dir = launcher_result
        print(f"✅ 启动器已安装: {launcher_path}")

        # Check PATH and provide platform-specific instructions
        if not _check_path_entry(target_bin_dir):
            print()
            print("⚠️  你的 PATH 里还没有", target_bin_dir)
            print()
            if sys.platform == "win32":
                print("📋 请将以下路径添加到系统 PATH:")
                print(f"  {target_bin_dir}")
                print()
                print("Windows 添加 PATH 方法:")
                print("  1. 按 Win+R 输入 sysdm.cpl")
                print("  2. 高级 → 环境变量")
                print("  3. 在用户变量中找到 Path")
                print("  4. 添加:", target_bin_dir)
            elif sys.platform == "darwin":
                print("📋 可以把下面这行加入到 ~/.zshrc (macOS 默认 zsh):")
                print(f'  export PATH="{target_bin_dir}:$PATH"')
                print()
                print("macOS 快速添加:")
                print(f'  echo \'export PATH="{target_bin_dir}:$PATH"\' >> ~/.zshrc')
                print("  source ~/.zshrc")
            else:
                print("📋 可以把下面这行加入到 ~/.bashrc 或 ~/.zshrc:")
                print(f'  export PATH="{target_bin_dir}:$PATH"')
                print()
                print("Linux 快速添加 (bash):")
                print(f'  echo \'export PATH="{target_bin_dir}:$PATH"\' >> ~/.bashrc')
                print("  source ~/.bashrc")
        else:
            print()
            print(f"✅ 现在你可以在任意终端输入 `{launcher_command}` 启动。")

    # Final summary
    print()
    print("=" * 60)
    print("  安装完成！")
    print("=" * 60)
    print()
    print("📁 配置文件:", MINI_CODE_SETTINGS_PATH)
    if launcher_result:
        launcher_path, launcher_command, _ = launcher_result
        print("🚀 启动命令:", launcher_command)
    print()
    print("📋 各平台启动方式:")
    print()
    print("  Windows:")
    print("    minicode.bat               (如果已添加 PATH)")
    print("    python -m minicode.main    (通用方式)")
    print()
    print("  macOS:")
    print("    minicode-py                (如果已添加 PATH)")
    print("    python3 -m minicode.main   (通用方式)")
    print()
    print("  Linux:")
    print("    minicode-py                (如果已添加 PATH)")
    print("    python3 -m minicode.main   (通用方式)")
    print()
    print("感谢使用 MiniCode Python！🎉")
    print()


if __name__ == "__main__":
    main()
