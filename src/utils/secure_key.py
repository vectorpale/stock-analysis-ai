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

_SENSITIVE_KEYS = ["DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FMP_API_KEY"]


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


def ensure_api_key(env_var: str = "DASHSCOPE_API_KEY", prompt_if_missing: bool = True) -> bool:
    """
    确保 LLM API Key 已设置。

    检查顺序:
    1. DASHSCOPE_API_KEY (通义千问，默认推荐)
    2. ANTHROPIC_API_KEY (Claude)
    3. OPENAI_API_KEY (通用 OpenAI 兼容)
    4. 交互式提示输入

    Returns:
        True if key is available, False if user skipped
    """
    # 检查是否已有任意一个 LLM Key
    for key_name in ("DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        existing = os.environ.get(key_name, "").strip()
        if existing:
            logger.debug(f"{key_name} 已设置 ({_mask(existing)})")
            return True

    if not prompt_if_missing:
        return False

    # 交互式输入 — 默认通义千问，只需输入 API Key
    print(f"\n{'='*56}")
    print(f"  未检测到 API Key，请选择 LLM 服务商:")
    print(f"  [1] 通义千问 Qwen (推荐，注册即送免费额度)")
    print(f"  [2] 其他 OpenAI 兼容 (DeepSeek/GPT/Ollama)")
    print(f"  [3] Anthropic Claude")
    print(f"{'='*56}")

    try:
        choice = input("请选择 [1/2/3] (默认1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False

    if choice == "3":
        return _prompt_anthropic()
    elif choice == "2":
        return _prompt_openai_compatible()
    else:
        return _prompt_qwen()


def _prompt_qwen() -> bool:
    """交互式输入通义千问 API Key"""
    print()
    print("  通义千问 API Key 获取: https://dashscope.console.aliyun.com/apiKey")
    print("  输入不会显示在屏幕上，也不会保存到文件")
    try:
        key = getpass.getpass(prompt="通义千问 API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False

    if not key:
        print("未输入 Key")
        return False

    os.environ["DASHSCOPE_API_KEY"] = key
    print(f"  已设置 通义千问 ({_mask(key)})")
    print(f"  此 Key 仅在本次运行期间有效，进程结束后自动清除\n")
    _register_cleanup("DASHSCOPE_API_KEY", key)
    return True


def _prompt_anthropic() -> bool:
    """交互式输入 Anthropic API Key"""
    print("  输入不会显示在屏幕上，也不会保存到文件")
    try:
        key = getpass.getpass(prompt="Anthropic API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False

    if not key:
        print("未输入 Key")
        return False

    os.environ["ANTHROPIC_API_KEY"] = key
    print(f"  已设置 ANTHROPIC_API_KEY ({_mask(key)})")
    print(f"  此 Key 仅在本次运行期间有效，进程结束后自动清除\n")
    _register_cleanup("ANTHROPIC_API_KEY", key)
    return True


def _prompt_openai_compatible() -> bool:
    """交互式输入 OpenAI 兼容配置"""
    print("  输入不会显示在屏幕上，也不会保存到文件")
    print()

    # Base URL
    print("  常见 Base URL:")
    print("    DeepSeek:  https://api.deepseek.com")
    print("    Ollama:    http://localhost:11434/v1")
    print("    OpenAI:    (留空即可)")
    print()

    try:
        base_url = input("Base URL (留空=OpenAI官方): ").strip()
        key = getpass.getpass(prompt="API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False

    if not key:
        print("未输入 Key")
        return False

    os.environ["OPENAI_API_KEY"] = key
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url

    # 让用户指定模型
    print()
    model = input("模型名称 (如 deepseek-chat, gpt-4o, 留空=自动): ").strip()
    if model:
        os.environ["LLM_MODEL_OVERRIDE"] = model

    provider_name = base_url or "OpenAI"
    print(f"  已设置: {provider_name} ({_mask(key)})")
    print(f"  此配置仅在本次运行期间有效，进程结束后自动清除\n")
    _register_cleanup("OPENAI_API_KEY", key)
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
