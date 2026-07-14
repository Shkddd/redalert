"""可观测性统一层:可选接入 LangSmith + AgentOps + OpenTelemetry

设计: 监控是 best-effort, **必须不影响主流程**
  - 没 key → 完全 no-op (零开销)
  - 有 key → 自动接入对应 SaaS
  - AgentOps / LangSmith 都失败也不能 raise

接入的库(都已装):
  - langsmith 0.10.1:  @traceable 装饰函数自动上报
  - agentops 0.4.21:  init() + record(event) + @agent/@tool
  - opentelemetry:  自动跟随 agentops 装上, 用于 OTLP export

启动时通过环境变量控制:
  LANGSMITH_API_KEY=xxx       - 启用 LangSmith
  LANGSMITH_ENDPOINT=xxx      - 自定义 endpoint (默认 api.smith.langchain.com)
  AGENTOPS_API_KEY=xxx        - 启用 AgentOps
  AGENTOPS_ENDPOINT=xxx       - 自定义 endpoint (默认 api.agentops.ai)
  OTEL_EXPORTER_OTLP_ENDPOINT - OpenTelemetry collector (本地或自托管)

用法:
  from app.core.observability import obs
  obs.setup()  # 在 server / cli 启动时调一次
  obs.trace(name="agent_run", run_type="chain")(func)
  obs.record_llm_call(model="...", latency=..., tokens=..., ok=True)
"""
import os
import time
import functools
from typing import Optional, Callable, Any
from app.core.config import LLM_MODEL


class Observability:
    """统一的 observability facade"""

    def __init__(self):
        self.langsmith_enabled = False
        self.agentops_enabled = False
        self.otel_enabled = False
        self._ls_client = None
        self._ao_client = None

    def setup(self, tags: Optional[list] = None):
        """启动时调一次: 检测环境变量, 启用对应的 backend

        都失败也不抛错 —— 不能因为监控挂掉影响主流程
        """
        print("[OBS] initializing observability...")

        # ----- LangSmith -----
        ls_key = os.getenv("LANGSMITH_API_KEY")
        if ls_key and ls_key != "your-key-here":
            try:
                from langsmith import Client as LSClient
                project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "default"
                self._ls_client = LSClient(api_key=ls_key)
                # 全局配置, 让 @traceable 自动用此 project (configure() 不接 api_key, 自动从 env 读)
                import langsmith as _ls
                _ls.configure(
                    client=self._ls_client,
                    enabled=True,
                    project_name=project,
                )
                self.langsmith_project = project
                self.langsmith_enabled = True
                print(f"[OBS] ✓ LangSmith enabled → project={project}")
            except Exception as e:
                print(f"[OBS] ✗ LangSmith init failed: {e}")
        else:
            print("[OBS] - LangSmith: no API key (skip)")

        # ----- AgentOps -----
        ao_key = os.getenv("AGENTOPS_API_KEY")
        if ao_key and ao_key != "your-key-here":
            try:
                import agentops
                agentops.init(
                    api_key=ao_key,
                    tags=tags or ["local-agent"],
                    auto_start_session=False,  # 我们手动管理 session
                    instrument_llm_calls=False,  # 我们自己 record
                    fail_safe=True,
                )
                self.agentops_enabled = True
                print("[OBS] ✓ AgentOps enabled (api.agentops.ai)")
            except Exception as e:
                print(f"[OBS] ✗ AgentOps init failed: {e}")
        else:
            print("[OBS] - AgentOps: no API key (skip)")

        # ----- OpenTelemetry (本地方案, 不需要 SaaS key) -----
        otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otel_endpoint:
            try:
                from opentelemetry import trace as otel_trace
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                provider = TracerProvider()
                exporter = OTLPSpanExporter(endpoint=otel_endpoint + "/v1/traces")
                provider.add_span_processor(BatchSpanProcessor(exporter))
                otel_trace.set_tracer_provider(provider)
                self.otel_enabled = True
                print(f"[OBS] ✓ OpenTelemetry enabled ({otel_endpoint})")
            except Exception as e:
                print(f"[OBS] ✗ OpenTelemetry init failed: {e}")
        else:
            print("[OBS] - OpenTelemetry: no OTLP endpoint (skip)")

    def patch_chat_function(self):
        """setup() 后调, 把 chat() 函数动态加上 traceable 装饰"""
        if not self.langsmith_enabled:
            return
        try:
            from langsmith import traceable
            import app.llm.client as _c
            if not getattr(_c.chat, "_ls_patched", False):
                _c.chat = traceable(name="llm_chat", run_type="llm")(_c.chat)
                _c.chat._ls_patched = True
                print("[OBS] ✓ patched app.llm.client.chat with @traceable")
        except Exception as e:
            print(f"[OBS] ✗ patch chat failed: {e}")

    def trace(self, name: str = "agent", run_type: str = "chain"):
        """装饰器: 自动 trace 到 LangSmith / OTel

        用法:
            @obs.trace(name="my_func")
            def my_func(...): ...

        注意: 装饰器在 import 时执行, 但 setup() 在 server 启动时才执行,
        所以这里用 lazy check —— 每次调用时再判断是否启用

        重要: 如果 setup() 在装饰之后才执行, 装饰器返回的 wrapper 是 no-op;
        请在 setup() 之后调用 patch_module() 来重新装饰已装饰的函数
        """
        def decorator(func: Callable) -> Callable:
            import functools as _ft
            # LangSmith @traceable - 准备 (如果 enabled 后期变 True, 下次调用时再加 traceable 不太现实,
            # 所以在 setup() 里直接 patch 已装饰的函数)
            traceable_fn = None
            if self.langsmith_enabled:
                try:
                    from langsmith import traceable
                    traceable_fn = traceable(name=name, run_type=run_type)
                except Exception:
                    pass

            # OpenTelemetry - lazy 创建 tracer
            def _get_otel_tracer():
                if self.otel_enabled:
                    try:
                        from opentelemetry import trace as otel_trace
                        return otel_trace.get_tracer(name)
                    except Exception:
                        pass
                return None

            @_ft.wraps(func)
            def wrapper(*args, **kwargs):
                tracer = _get_otel_tracer()
                if tracer:
                    with tracer.start_as_current_span(name):
                        return func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)

            # 如果 LangSmith enabled 在装饰时, 直接套 traceable
            if traceable_fn:
                wrapper = traceable_fn(wrapper)

            return wrapper
        return decorator

    def record_llm(self, model: str, latency: float, ok: bool,
                   prompt_tokens: int = 0, completion_tokens: int = 0,
                   error: str = ""):
        """记录一次 LLM 调用"""
        if self.agentops_enabled:
            try:
                import agentops
                agentops.record(agentops.LLMEvent(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency=latency * 1000,  # ms
                ))
            except Exception:
                pass

        # 自家 metrics 也记录 (无论 observability 是否开)
        from app.core.metrics import metrics as _m
        _m.record_llm(latency=latency, model=model, ok=ok,
                      prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                      error=error)

    def record_tool(self, name: str, latency: float, ok: bool,
                    args: Optional[dict] = None, error: str = ""):
        """记录一次 tool 调用"""
        if self.agentops_enabled:
            try:
                import agentops
                agentops.record(agentops.ToolEvent(
                    name=name,
                    arguments=args or {},
                    latency=latency * 1000,  # ms
                ))
            except Exception:
                pass

        from app.core.metrics import metrics as _m
        _m.record_tool(name, latency=latency, ok=ok, error=error)

    def start_session(self, name: str = "agent_run", tags: Optional[list] = None):
        """开始一个 session (跨多个 LLM/tool 调用的容器)"""
        if self.agentops_enabled:
            try:
                import agentops
                agentops.start_session(name=name, tags=tags or [])
            except Exception:
                pass

    def end_session(self, **kwargs):
        """结束 session"""
        if self.agentops_enabled:
            try:
                import agentops
                agentops.end_session(**kwargs)
            except Exception:
                pass


# 单例
obs = Observability()
