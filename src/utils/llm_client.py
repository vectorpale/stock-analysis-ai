"""
统一 LLM 客户端 - 支持 Anthropic + OpenAI 兼容格式
可接入: Claude, GPT, DeepSeek, Qwen, Ollama, vLLM, LiteLLM 等
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMProvider:
    """LLM 提供商配置"""
    provider: str = "anthropic"       # "anthropic" | "openai_compatible"
    api_key: str = ""
    base_url: str = ""                # OpenAI 兼容接口的 base URL
    # 模型映射: 角色 → 实际模型ID
    model_cio: str = ""
    model_analyst: str = ""
    model_data: str = ""

    # Anthropic 默认模型
    ANTHROPIC_DEFAULTS = {
        "cio": "claude-opus-4-20250514",
        "analyst": "claude-sonnet-4-20250514",
        "data": "claude-haiku-4-5-20251001",
    }

    # OpenAI 兼容默认模型 (可被用户覆盖)
    OPENAI_DEFAULTS = {
        "cio": "gpt-4o",
        "analyst": "gpt-4o-mini",
        "data": "gpt-4o-mini",
    }

    def get_model(self, role: str) -> str:
        """根据角色获取模型ID"""
        explicit = {
            "cio": self.model_cio,
            "analyst": self.model_analyst,
            "data": self.model_data,
        }.get(role, "")
        if explicit:
            return explicit

        defaults = self.ANTHROPIC_DEFAULTS if self.provider == "anthropic" else self.OPENAI_DEFAULTS
        return defaults.get(role, "")


class LLMClient:
    """
    统一 LLM 调用接口

    支持:
    - Anthropic (原生 SDK)
    - OpenAI 兼容格式 (openai SDK，可指定 base_url)
    """

    def __init__(self, provider_config: LLMProvider):
        self.config = provider_config
        self._token_usage = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "by_model": {},
        }

        if provider_config.provider == "anthropic":
            self._init_anthropic(provider_config.api_key)
        elif provider_config.provider == "openai_compatible":
            self._init_openai(provider_config.api_key, provider_config.base_url)
        else:
            raise ValueError(f"不支持的 provider: {provider_config.provider}")

    def _init_anthropic(self, api_key: str):
        from anthropic import Anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ValueError(
                "未设置 Anthropic API Key。\n"
                "请通过以下方式之一设置:\n"
                "  1. 在配置中指定 api_key\n"
                "  2. 设置环境变量 ANTHROPIC_API_KEY\n"
                "  3. 运行时交互输入"
            )
        self._anthropic_client = Anthropic(api_key=key)
        self._call_fn = self._call_anthropic
        logger.info("LLM provider: Anthropic")

    def _init_openai(self, api_key: str, base_url: str):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "使用 OpenAI 兼容模式需要安装 openai 包:\n"
                "  pip install openai"
            )
        key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise ValueError(
                "未设置 API Key。\n"
                "请在配置中指定 api_key 或设置环境变量 OPENAI_API_KEY"
            )
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self._openai_client = OpenAI(**kwargs)
        self._call_fn = self._call_openai
        provider_name = base_url or "OpenAI"
        logger.info(f"LLM provider: OpenAI Compatible ({provider_name})")

    # ==================================================================
    # 统一调用入口
    # ==================================================================
    def call(self, model: str, system: str, user_message: str) -> str:
        """统一的 LLM 调用接口"""
        return self._call_fn(model, system, user_message)

    # ==================================================================
    # Anthropic 实现
    # ==================================================================
    def _call_anthropic(self, model: str, system: str, user_message: str) -> str:
        try:
            response = self._anthropic_client.messages.create(
                model=model,
                max_tokens=8192,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            self._track_usage(model, input_tokens, output_tokens)
            return response.content[0].text
        except Exception as e:
            self._log_error(model, e)
            return ""

    # ==================================================================
    # OpenAI 兼容实现
    # ==================================================================
    def _call_openai(self, model: str, system: str, user_message: str) -> str:
        try:
            response = self._openai_client.chat.completions.create(
                model=model,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )
            usage = response.usage
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            self._track_usage(model, input_tokens, output_tokens)
            return response.choices[0].message.content or ""
        except Exception as e:
            self._log_error(model, e)
            return ""

    # ==================================================================
    # 用量统计
    # ==================================================================
    def _track_usage(self, model: str, input_tokens: int, output_tokens: int):
        self._token_usage["calls"] += 1
        self._token_usage["input_tokens"] += input_tokens
        self._token_usage["output_tokens"] += output_tokens
        if model not in self._token_usage["by_model"]:
            self._token_usage["by_model"][model] = {
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
            }
        self._token_usage["by_model"][model]["calls"] += 1
        self._token_usage["by_model"][model]["input_tokens"] += input_tokens
        self._token_usage["by_model"][model]["output_tokens"] += output_tokens
        logger.debug(f"Token: +{input_tokens}in/{output_tokens}out ({model})")

    def _log_error(self, model: str, error: Exception):
        error_msg = str(error).lower()
        if any(kw in error_msg for kw in ("authentication", "api_key", "auth_token", "unauthorized", "401")):
            logger.error(f"API 认证失败: {error}\n请检查 API Key 是否正确")
        else:
            logger.error(f"LLM 调用失败 ({model}): {error}")

    def get_token_usage(self) -> dict:
        return self._token_usage


def build_provider_from_config(config: dict) -> LLMProvider:
    """
    从 config.yaml 构建 LLMProvider

    优先级: 环境变量 > config.yaml > 默认值
    这样用户交互输入的 Key 能正确覆盖配置文件
    """
    models_cfg = config.get("models", {})
    provider_cfg = config.get("llm_provider", {})

    # 环境变量优先 (交互输入的 key 存在环境变量中)
    env_provider = _detect_provider_from_env()
    if env_provider:
        # 环境变量指定了 provider，但模型名仍从 config 读取
        model_override = os.environ.get("LLM_MODEL_OVERRIDE", "").strip()
        if env_provider.provider == "openai_compatible" and model_override:
            env_provider.model_cio = model_override
            env_provider.model_analyst = model_override
            env_provider.model_data = model_override
        elif not env_provider.model_cio:
            env_provider.model_cio = models_cfg.get("cio", "")
            env_provider.model_analyst = models_cfg.get("analyst", "")
            env_provider.model_data = models_cfg.get("data_extract", "")
        return env_provider

    # 从 config 读取
    provider = provider_cfg.get("provider", "anthropic")
    api_key = provider_cfg.get("api_key", "")
    base_url = provider_cfg.get("base_url", "")

    return LLMProvider(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model_cio=models_cfg.get("cio", ""),
        model_analyst=models_cfg.get("analyst", ""),
        model_data=models_cfg.get("data_extract", ""),
    )


def _detect_provider_from_env() -> Optional[LLMProvider]:
    """从环境变量检测 provider"""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return LLMProvider(provider="anthropic", api_key=anthropic_key)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        model_override = os.environ.get("LLM_MODEL_OVERRIDE", "").strip()
        return LLMProvider(
            provider="openai_compatible",
            api_key=openai_key,
            base_url=base_url,
            model_cio=model_override or "",
            model_analyst=model_override or "",
            model_data=model_override or "",
        )

    return None
