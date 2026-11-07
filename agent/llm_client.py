import os
import re
import json
import time
from threading import Lock
from typing import Callable, Optional, Iterator, AsyncIterator, Any

from dotenv import load_dotenv
from openai import (
    OpenAI,
    APITimeoutError,
    APIConnectionError,
)
from langchain_openai import ChatOpenAI
from langchain_core.runnables import Runnable, RunnableConfig

load_dotenv()

MAX_MODEL_ATTEMPTS = 3

# ============================================================
# 全局状态
# ============================================================

_CLIENT = None
_CLIENT_LOCK = Lock()

# 当前进程中已经熔断的模型
_DISABLED_MODELS = set()
_MODEL_STATE_LOCK = Lock()


def is_model_disabled(model: str) -> bool:
    """判断模型是否已经熔断。"""
    with _MODEL_STATE_LOCK:
        return model in _DISABLED_MODELS


def disable_model(model: str, reason: str):
    """将模型加入熔断名单。"""
    with _MODEL_STATE_LOCK:
        if model not in _DISABLED_MODELS:
            _DISABLED_MODELS.add(model)
            print(
                f"[LLM] 熔断模型 {model}: {reason}",
                flush=True,
            )


def clear_disabled_models():
    """手动清空熔断名单，恢复所有模型。"""
    with _MODEL_STATE_LOCK:
        _DISABLED_MODELS.clear()

    print("[LLM] 已清空模型熔断名单", flush=True)


def get_disabled_models() -> list[str]:
    """获取当前已经熔断的模型。"""
    with _MODEL_STATE_LOCK:
        return list(_DISABLED_MODELS)


def get_status_code(exc: Exception) -> Optional[int]:
    """提取 HTTP 状态码。"""
    return getattr(exc, "status_code", None)


def is_permanent_error(exc: Exception) -> bool:
    """
    判断是否属于确定性的模型不可用错误。

    401：认证失败
    403：权限、额度不足
    404：模型不存在或不可用
    """
    return get_status_code(exc) in (401, 403, 404)


def is_retryable_error(exc: Exception) -> bool:
    """
    判断是否属于适合重试的临时错误。

    网络错误、超时、429、5xx。
    """
    status_code = get_status_code(exc)

    return (
        isinstance(exc, (APITimeoutError, APIConnectionError))
        or status_code == 429
        or (status_code is not None and 500 <= status_code < 600)
    )


# ============================================================
# OpenAI Client
# ============================================================

def get_client() -> OpenAI:
    """创建并复用 OpenAI Client。"""
    global _CLIENT

    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                api_key = os.getenv("LLM_API_KEY")
                base_url = os.getenv("LLM_BASE_URL")

                if not api_key:
                    raise RuntimeError("缺少环境变量 LLM_API_KEY")

                if not base_url:
                    raise RuntimeError("缺少环境变量 LLM_BASE_URL")

                _CLIENT = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=180,
                    max_retries=0,
                )

    return _CLIENT


# ============================================================
# 模型配置
# ============================================================

def get_model_chain(
    primary_env: str,
    fallback_env: Optional[str] = None,
) -> list[str]:
    """读取主模型和备用模型，按顺序去重。"""

    primary = os.getenv(primary_env, "").strip()

    if not primary:
        raise RuntimeError(f"缺少环境变量 {primary_env}")

    fallbacks = []

    if fallback_env:
        fallbacks = [
            model.strip()
            for model in os.getenv(fallback_env, "").split(",")
            if model.strip()
        ]

    return list(dict.fromkeys([primary, *fallbacks]))


# ============================================================
# JSON 解析
# ============================================================

def parse_json(content: str) -> dict:
    """解析 JSON，兼容 Markdown 代码围栏。"""

    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM 返回内容为空")

    content = content.strip()

    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )

    content = re.sub(r"\s*```$", "", content)

    result = json.loads(content)

    if not isinstance(result, dict):
        raise ValueError("LLM 返回的 JSON 顶层必须是对象")

    return result


class LLMAllModelsFailed(RuntimeError):
    """所有模型均调用失败。"""


# ============================================================
# OpenAI 原生 JSON 调用
# ============================================================

def chat_json(
    prompt: str,
    system_prompt: str = "",
    primary_env: str = "LLM_ANALYSE",
    fallback_env: Optional[str] = None,
    temperature: float = 0.2,
    timeout: int = 180,
    before_request: Optional[Callable] = None,
) -> dict:
    """
    OpenAI 原生 JSON 调用。

    规则：
    1. 按配置顺序调用模型。
    2. 401/403/404 立即熔断，不重试。
    3. 网络、超时、429、5xx 最多重试 3 次。
    4. 临时错误连续失败 3 次，熔断该模型。
    5. 后续请求跳过已经熔断的模型。
    """

    client = get_client()
    models = get_model_chain(primary_env, fallback_env)

    messages = []

    if system_prompt:
        messages.append({
            "role": "system",
            "content": system_prompt,
        })

    messages.append({
        "role": "user",
        "content": prompt,
    })

    last_error = None

    for model in models:

        if is_model_disabled(model):
            print(f"[LLM] 跳过已熔断模型: {model}", flush=True)
            continue

        for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):

            try:
                if before_request:
                    before_request()

                print(
                    f"[LLM] {model} 第 {attempt}/{MAX_MODEL_ATTEMPTS} 次调用",
                    flush=True,
                )

                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    timeout=timeout,
                )

                if not response.choices:
                    raise ValueError("LLM 返回空 choices")

                result = parse_json(
                    response.choices[0].message.content
                )

                print(f"[LLM] {model} 调用成功", flush=True)

                return result

            except Exception as exc:
                last_error = exc

                print(
                    f"[LLM] {model} 第 {attempt} 次失败: {exc}",
                    flush=True,
                )

                # 永久性错误：立即熔断
                if is_permanent_error(exc):
                    disable_model(model, f"HTTP {get_status_code(exc)}")
                    break

                # 临时错误：有限重试
                if is_retryable_error(exc):

                    if attempt < MAX_MODEL_ATTEMPTS:
                        time.sleep(2 ** (attempt - 1))
                        continue

                    disable_model(
                        model,
                        f"连续 {MAX_MODEL_ATTEMPTS} 次临时错误",
                    )
                    break

                # 其他错误：当前请求切换模型，不进行重试
                print(
                    f"[LLM] {model} 非重试错误，切换下一个模型",
                    flush=True,
                )
                break

    raise LLMAllModelsFailed(
        f"所有模型均不可用，最后错误: {last_error}"
    ) from last_error


# ============================================================
# LangChain 模型调用与动态 Fallback
# ============================================================

class ModelFallbackRunnable(Runnable):
    """
    支持全局熔断的 LangChain 模型调度器。

    不使用 with_fallbacks()，而是每次调用时检查全局熔断名单。
    同时支持 invoke、ainvoke、stream、astream。
    """

    def __init__(self, models: list[tuple[str, Any]]):
        self.models = models

    def _invoke_model(self, model, input, config, kwargs):
        """调用单个模型，处理重试。"""

        for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):

            try:
                print(
                    f"[LLM] {model.model_name} "
                    f"第 {attempt}/{MAX_MODEL_ATTEMPTS} 次调用",
                    flush=True,
                )

                result = model.invoke(
                    input,
                    config=config,
                    **kwargs,
                )

                print(
                    f"[LLM] {model.model_name} 调用成功",
                    flush=True,
                )

                return result

            except Exception as exc:
                print(
                    f"[LLM] {model.model_name} "
                    f"第 {attempt} 次失败: {exc}",
                    flush=True,
                )

                if is_permanent_error(exc):
                    disable_model(
                        model.model_name,
                        f"HTTP {get_status_code(exc)}",
                    )
                    raise

                if is_retryable_error(exc):

                    if attempt < MAX_MODEL_ATTEMPTS:
                        time.sleep(2 ** (attempt - 1))
                        continue

                    disable_model(
                        model.model_name,
                        f"连续 {MAX_MODEL_ATTEMPTS} 次临时错误",
                    )
                    raise

                raise

    def invoke(self, input, config=None, **kwargs):
        last_error = None

        for name, model in self.models:

            if is_model_disabled(name):
                print(f"[LLM] 跳过已熔断模型: {name}", flush=True)
                continue

            try:
                return self._invoke_model(
                    model,
                    input,
                    config,
                    kwargs,
                )

            except Exception as exc:
                last_error = exc
                print(f"[LLM] 切换下一个模型", flush=True)

        raise LLMAllModelsFailed(
            f"所有模型均不可用，最后错误: {last_error}"
        ) from last_error

    async def ainvoke(self, input, config=None, **kwargs):
        import asyncio

        return await asyncio.to_thread(
            self.invoke,
            input,
            config,
            **kwargs,
        )

    def stream(self, input, config=None, **kwargs) -> Iterator:
        """
        流式调用。

        如果模型在输出任何内容前失败，可以切换备用模型。
        如果已经输出部分内容后发生异常，则直接抛出异常，
        避免备用模型重新输出造成内容重复。
        """

        last_error = None

        for name, model in self.models:

            if is_model_disabled(name):
                print(f"[LLM] 跳过已熔断模型: {name}", flush=True)
                continue

            for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):

                emitted = False

                try:
                    print(
                        f"[LLM] {name} 第 {attempt}/{MAX_MODEL_ATTEMPTS} 次流式调用",
                        flush=True,
                    )

                    for chunk in model.stream(
                        input,
                        config=config,
                        **kwargs,
                    ):
                        emitted = True
                        yield chunk

                    return

                except Exception as exc:
                    last_error = exc

                    if emitted:
                        raise

                    if is_permanent_error(exc):
                        disable_model(
                            name,
                            f"HTTP {get_status_code(exc)}",
                        )
                        break

                    if is_retryable_error(exc):

                        if attempt < MAX_MODEL_ATTEMPTS:
                            time.sleep(2 ** (attempt - 1))
                            continue

                        disable_model(
                            name,
                            f"连续 {MAX_MODEL_ATTEMPTS} 次临时错误",
                        )
                        break

                    break

        raise LLMAllModelsFailed(
            f"所有模型均不可用，最后错误: {last_error}"
        ) from last_error

    async def astream(
        self,
        input,
        config=None,
        **kwargs,
    ) -> AsyncIterator:
        import asyncio

        # 异步场景通过同步流式生成器在线程中执行并转发。
        # 如项目需要高并发原生异步流式调用，可进一步单独实现。
        queue = __import__("queue").Queue()
        sentinel = object()

        def producer():
            try:
                for chunk in self.stream(input, config, **kwargs):
                    queue.put(("data", chunk))
            except Exception as exc:
                queue.put(("error", exc))
            finally:
                queue.put(("end", sentinel))

        task = asyncio.create_task(
            asyncio.to_thread(producer)
        )

        while True:
            kind, value = await asyncio.to_thread(queue.get)

            if kind == "data":
                yield value
            elif kind == "error":
                raise value
            else:
                break

        await task


def get_chat_model(
    primary_env: str,
    fallback_env: Optional[str] = None,
    timeout: int = 40,
    streaming: bool = True,
    enable_thinking: bool = False,
    tools: Optional[list] = None,
):
    """
    创建支持全局熔断的 LangChain 模型调度器。

    所有模型都按配置顺序调用。
    已熔断模型不会再次尝试。
    """

    model_names = get_model_chain(primary_env, fallback_env)

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")

    if not api_key or not base_url:
        raise RuntimeError("缺少 LLM_API_KEY 或 LLM_BASE_URL")

    model_chain = []

    for model_name in model_names:

        model = ChatOpenAI(
            model=model_name,
            openai_api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            streaming=streaming,
            extra_body={
                "enable_thinking": enable_thinking,
            },
        )

        # 每个模型都绑定相同工具
        if tools:
            model = model.bind_tools(tools)

        model_chain.append((model_name, model))

    return ModelFallbackRunnable(model_chain)