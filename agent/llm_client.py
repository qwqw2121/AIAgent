
import os
import re
import json
import time
from threading import Lock
from typing import Callable, Optional

from dotenv import load_dotenv
from openai import OpenAI
from langchain_openai import ChatOpenAI

load_dotenv()

MAX_MODEL_ATTEMPTS = 3

_CLIENT = None
_CLIENT_LOCK = Lock()


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
    """所有模型均连续调用失败。"""


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

    每个模型最多尝试 3 次，连续失败后切换下一个模型。
    before_request 用于接入外部限流器。
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

        for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):

            try:
                if before_request:
                    before_request()

                print(
                    f"[LLM] {model} "
                    f"第 {attempt}/{MAX_MODEL_ATTEMPTS} 次调用",
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
                    f"[LLM] {model} "
                    f"第 {attempt}/{MAX_MODEL_ATTEMPTS} 次失败: {exc}",
                    flush=True,
                )

                if attempt < MAX_MODEL_ATTEMPTS:
                    time.sleep(2 ** (attempt - 1))

        print(
            f"[LLM] {model} 连续失败 3 次，切换下一个模型",
            flush=True,
        )

    raise LLMAllModelsFailed(
        f"所有模型均调用失败，最后错误: {last_error}"
    ) from last_error

# get_chat_model() 特别注意了工具绑定顺序：先对每个 ChatOpenAI 模型执行 bind_tools()，
# 再进行重试和 fallback 包装。这样备用模型也能使用相同的 MCP 工具。
def get_chat_model(
    primary_env: str,
    fallback_env: Optional[str] = None,
    timeout: int = 40,
    streaming: bool = True,
    enable_thinking: bool = False,
    tools: Optional[list] = None,
):
    """
    LangChain ChatOpenAI 模型链。

    每个模型独立重试 3 次，失败后自动切换。
    先绑定工具，再包装重试和 fallback，
    保证备用模型同样具备工具调用能力。
    """

    models = get_model_chain(primary_env, fallback_env)

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")

    if not api_key or not base_url:
        raise RuntimeError("缺少 LLM_API_KEY 或 LLM_BASE_URL")

    model_chain = []

    for model_name in models:

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

        # 当前模型连续失败 3 次后才进入 fallback
        model = model.with_retry(
            retry_if_exception_type=(Exception,),
            stop_after_attempt=MAX_MODEL_ATTEMPTS,
            wait_exponential_jitter=True,
        )

        model_chain.append(model)

    primary = model_chain[0]

    if len(model_chain) == 1:
        return primary

    return primary.with_fallbacks(model_chain[1:])
