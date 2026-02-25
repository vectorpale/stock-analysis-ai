"""
API Key 安全管理器
- 运行时交互输入，不落盘
- 仅存活于进程内存，结束后自动清除
- 日志中自动脱敏
"""

import atexit
import getpass
import logging
import os
import ctypes
import sys

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = ["ANTHROPIC_API_KEY"]


def _mask(key: str) -> str:
    """脱敏显示: sk-ant-...xyzQ"""
    if not key or len(key) < 12:
        return "***"
    return f"{key[:7]}...{key[-4:]}"


def _secure_zero(s: str):
    """尽力从内存中擦除字符串内容 (CPython best-effort)"""
    try:
        # CPython 内部: str 对象的 buffer 在 ob_sval 偏移处
        # 这不是 100% 保证（GC 可能有副本），但大幅减少残留
        if sys.implementation.name == "cpython":
            buf = ctypes.cast(id(s), ctypes.POINTER(ctypes.c_char))
            # PyASCIIObject header 大约 48-72 bytes，取保守值
            header_size = sys.getsizeof("") - 1
            for i in range(header_size, header_size + len(s)):
                buf[i] = b'\x00'
    except Exception:
        pass  # 非 CPython 或权限不足，静默跳过


def ensure_api_key(env_var: str = "ANTHROPIC_API_KEY", prompt_if_missing: bool = True) -> bool:
    """
    确保 API Key 已设置。

    查找顺序:
    1. 环境变量已有值 → 直接使用
    2. .env 文件 (通过 dotenv 已加载)
    3. 交互式提示用户输入 (不回显)

    Returns:
        True if key is available, False if user skipped
    """
    existing = os.environ.get(env_var, "").strip()
    if existing:
        logger.debug(f"{env_var} 已设置 ({_mask(existing)})")
        return True

    if not prompt_if_missing:
        return False

    # 交互式输入
    print(f"\n{'='*50}")
    print(f"  需要 Anthropic API Key 才能运行分析")
    print(f"  (输入不会显示在屏幕上，也不会保存到文件)")
    print(f"{'='*50}")

    try:
        key = getpass.getpass(prompt="请输入 API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False

    if not key:
        print("未输入 Key，退出")
        return False

    # 仅设置到当前进程环境变量（不写文件）
    os.environ[env_var] = key
    print(f"  已设置 {env_var} ({_mask(key)})")
    print(f"  此 Key 仅在本次运行期间有效，进程结束后自动清除\n")

    # 注册退出时清理
    _register_cleanup(env_var, key)

    return True


def cleanup_api_keys():
    """
    主动清理所有敏感 Key:
    1. 从 os.environ 中删除
    2. 尝试从内存中擦零
    """
    for env_var in _SENSITIVE_KEYS:
        val = os.environ.pop(env_var, None)
        if val:
            _secure_zero(val)
            logger.debug(f"已清理 {env_var}")


def _register_cleanup(env_var: str, key_value: str):
    """注册 atexit 回调，进程退出时自动清理"""
    def _on_exit():
        val = os.environ.pop(env_var, None)
        if val:
            _secure_zero(val)
        _secure_zero(key_value)

    atexit.register(_on_exit)


class SensitiveFilter(logging.Filter):
    """日志过滤器: 自动脱敏 API Key"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for env_var in _SENSITIVE_KEYS:
            val = os.environ.get(env_var, "")
            if val and val in msg:
                record.msg = msg.replace(val, _mask(val))
                record.args = None
        return True
