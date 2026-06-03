# Langfuse Tracing Best Practices

本文档介绍了如何在本项目中有效使用 Langfuse 进行 LLM 应用的可观测性追踪。

## 📋 目录

- [概述](#概述)
- [架构设计](#架构设计)
- [核心概念](#核心概念)
- [最佳实践](#最佳实践)
- [使用示例](#使用示例)
- [性能优化](#性能优化)
- [故障排查](#故障排查)

## 概述

Langfuse 是一个开源的 LLM 可观测性平台，帮助我们：
- 🔍 **追踪** LLM 调用的完整生命周期
- 📊 **监控** 性能和成本指标
- 🧪 **评估** 模型输出质量
- 🐛 **调试** 复杂的多步骤工作流

## 架构设计

本项目的 tracing 架构分为三层：

```
┌─────────────────────────────────────────┐
│         HTTP Request Layer              │
│  (middleware.py - 自动创建 trace)        │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│       API Endpoint Layer                │
│  (router.py - 更新 trace context)       │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Agent Workflow Layer               │
│  (workflow.py - 细粒度 spans)           │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      LLM & Tool Execution Layer         │
│  (record_llm_call, record_tool_exec)    │
└─────────────────────────────────────────┘
```

## 核心概念

### 1. Trace（追踪）
- 代表一个完整的用户请求生命周期
- 从 HTTP 请求开始到响应结束
- 包含所有相关的 spans、元数据和标签

### 2. Span（跨度）
- Trace 中的单个操作单元
- 可以嵌套形成层次结构
- 记录输入、输出、持续时间和元数据

### 3. Observation（观察）
- Span 的具体实例
- 可以是 LLM 调用、工具执行或自定义操作

### 4. Score（评分）
- 用于评估质量的数值指标
- 可以是用户反馈或自动化评估

## 最佳实践

### ✅ 1. Trace 命名规范

使用清晰、一致的命名约定：

```python
# HTTP 请求
"http {METHOD} {PATH}"  # e.g., "http POST /api/v1/chatbot/chat"

# API 端点
"chatbot.chat"
"chatbot.chat.stream"

# Agent 操作
"agent.get_response"
"agent.get_stream_response"

# LLM 调用
"llm.chat"
"llm.completion"

# 工具执行
"tool.{tool_name}"  # e.g., "tool.web_search"

# 记忆操作
"memory.search"
"memory.update"
```

### ✅ 2. 元数据标准化

为每个 span 添加一致的元数据：

```python
metadata = {
    "model": "gpt-4",
    "provider": "openai",
    "temperature": 0.7,
    "max_tokens": 2000,
    "duration_ms": 1234.56,
    "environment": "production",
}
```

### ✅ 3. 标签策略

使用标签进行分类和过滤：

```python
tags = [
    "http",           # HTTP 请求
    "chatbot",        # 聊天机器人功能
    "sync",           # 同步请求
    "stream",         # 流式请求
    "post",           # HTTP 方法
]
```

### ✅ 4. 错误处理

始终捕获和记录错误：

```python
try:
    result = await some_operation()
    update_current_span(output=result)
except Exception as e:
    update_current_span(
        level="ERROR",
        status_message=str(e),
    )
    raise
```

### ✅ 5. 上下文传播

确保 trace context 在异步操作中正确传播：

```python
# 捕获当前 context
trace_context = capture_current_trace_context()

# 传递给子操作
asyncio.create_task(
    background_task(trace_context=trace_context)
)
```

### ✅ 6. 输入/输出采样

对于大型 payload，考虑采样或截断：

```python
input_data = {
    "message_count": len(messages),
    "last_user_message": messages[-1].content[:200],  # 截断
}
```

### ✅ 7. 性能监控

记录关键性能指标：

```python
import time

start_time = time.time()
result = await operation()
duration_ms = (time.time() - start_time) * 1000

update_current_span(
    output=result,
    metadata={"duration_ms": round(duration_ms, 2)},
)
```

## 使用示例

### 示例 1: 基本的 Trace 创建

```python
from src.system.tracing import (
    start_trace_span,
    update_current_span,
    capture_current_trace_context,
)

async def process_request(data: dict):
    with start_trace_span(
        "process_request",
        input=data,
        metadata={"version": "1.0"},
    ):
        result = await do_something(data)
        update_current_span(output=result)
        return result
```

### 示例 2: LLM 调用追踪

```python
from src.system.tracing import record_llm_call

async def call_llm(messages: list, model: str):
    with record_llm_call(
        "llm.chat",
        model=model,
        provider="openai",
        input_messages=messages,
        metadata={"temperature": 0.7},
    ):
        response = await llm.invoke(messages)
        update_current_span(output=response)
        return response
```

### 示例 3: 工具执行追踪

```python
from src.system.tracing import record_tool_execution

async def execute_tool(tool_name: str, args: dict):
    with record_tool_execution(
        tool_name,
        tool_args=args,
    ):
        result = await tools[tool_name].invoke(args)
        update_current_span(output=result)
        return result
```

### 示例 4: 添加评分

```python
from src.system.tracing import add_score

# 用户反馈
add_score(
    name="user_rating",
    value=4.5,
    comment="Great response!",
)

# 自动化评估
add_score(
    name="quality_score",
    value=0.92,
    trace_id=trace_id,
)
```

### 示例 5: 异步任务中的 Trace

```python
import asyncio
from src.system.tracing import (
    capture_current_trace_context,
    start_trace_span,
)

async def background_task(data: dict, trace_context: dict):
    with start_trace_span(
        "background.task",
        trace_context=trace_context,
        input=data,
    ):
        result = await process(data)
        update_current_span(output=result)

# 在主流程中
trace_context = capture_current_trace_context()
asyncio.create_task(
    background_task(some_data, trace_context)
)
```

## 性能优化

### 1. 采样策略

在生产环境中，可以对非关键路径进行采样：

```python
# .env
LANGFUSE_SAMPLE_RATE=0.5  # 50% 采样率
```

### 2. 批量刷新

调整刷新设置以平衡实时性和性能：

```python
# .env
LANGFUSE_FLUSH_AT=20       # 每 20 个事件刷新
LANGFUSE_FLUSH_INTERVAL=1  # 或每秒刷新
```

### 3. 避免过度追踪

不要追踪低价值的操作：

```python
# 已自动排除的路径
UNTRACED_PATHS = {
    "/",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
}
```

### 4. 控制 Payload 大小

限制输入/输出的大小：

```python
def truncate_text(text: str, max_length: int = 1000) -> str:
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text
```

## 配置说明

### 环境变量

```bash
# 必需
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com

# 可选
LANGFUSE_TRACING_ENABLED=true      # 启用/禁用追踪
LANGFUSE_DEBUG=false               # 调试模式
LANGFUSE_SAMPLE_RATE=1.0           # 采样率 (0.0-1.0)
LANGFUSE_RELEASE=1.0.0             # 发布版本
LANGFUSE_FLUSH_AT=10               # 批量刷新阈值
LANGFUSE_FLUSH_INTERVAL=0.5        # 刷新间隔（秒）
```

### 本地开发

1. 使用 Langfuse Cloud（推荐）：
   ```bash
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

2. 自托管 Langfuse：
   ```bash
   LANGFUSE_BASE_URL=http://localhost:3000
   ```

3. 禁用追踪（测试环境）：
   ```bash
   LANGFUSE_TRACING_ENABLED=false
   ```

## 故障排查

### 问题 1: Trace 未出现在 Langfuse UI

**检查清单：**
- ✅ 验证 API keys 是否正确
- ✅ 确认 `LANGFUSE_TRACING_ENABLED=true`
- ✅ 检查网络连接
- ✅ 查看应用日志中的警告信息

**调试步骤：**
```python
from src.system.tracing import check_langfuse_auth

# 在应用启动时验证
auth_result = check_langfuse_auth()
print(f"Auth check: {auth_result}")
```

### 问题 2: Trace Context 丢失

**常见原因：**
- 异步任务未传递 `trace_context`
- 中间件顺序不正确

**解决方案：**
```python
# 始终捕获并传递 context
trace_context = capture_current_trace_context()
asyncio.create_task(
    my_async_task(trace_context=trace_context)
)
```

### 问题 3: 性能下降

**优化建议：**
- 降低采样率：`LANGFUSE_SAMPLE_RATE=0.5`
- 增加批量大小：`LANGFUSE_FLUSH_AT=50`
- 减少追踪的端点数量
- 限制 payload 大小

### 问题 4: Memory 泄漏

**预防措施：**
```python
# 确保在应用关闭时刷新
from src.system.tracing import shutdown_langfuse

@app.on_event("shutdown")
async def shutdown():
    shutdown_langfuse()
```

## 监控和告警

### 关键指标

在 Langfuse Dashboard 中监控：

1. **延迟指标**
   - P50, P95, P99 延迟
   - LLM 调用持续时间
   - 工具执行时间

2. **错误率**
   - HTTP 5xx 错误
   - LLM 调用失败
   - 工具执行错误

3. **成本指标**
   - Token 使用量
   - API 调用次数
   - 按模型/提供商分类的成本

4. **质量指标**
   - 用户评分
   - 自动化评估分数
   - 反馈趋势

### 设置告警

在 Langfuse 中设置告警规则：

- ❗ 错误率 > 5%
- ⚠️ P95 延迟 > 2秒
- 💰 每日成本 > $100
- 📉 平均评分 < 3.5

## 进阶用法

### 1. 自定义评估

```python
from src.system.tracing import add_score

# 基于规则的评估
def evaluate_response(response: str) -> float:
    score = 0.0
    if len(response) > 100:
        score += 0.3
    if "helpful" in response.lower():
        score += 0.2
    # ... 更多规则
    return min(score, 1.0)

add_score(
    name="automated_quality",
    value=evaluate_response(response),
)
```

### 2. A/B 测试

```python
# 在 metadata 中标记实验组
update_current_trace(
    metadata={
        "experiment": "prompt_v2",
        "variant": "B",
    }
)
```

### 3. 会话分析

```python
# 使用 session_id 关联相关请求
update_current_trace(
    session_id=user_session_id,
    user_id=user_id,
)
```

## 资源链接

- 📚 [Langfuse 官方文档](https://langfuse.com/docs)
- 🎯 [SDK 参考](https://langfuse.com/docs/sdk)
- 🔧 [自托管指南](https://langfuse.com/self-hosting)
- 💡 [最佳实践](https://langfuse.com/docs/tracing/best-practices)
- 🐛 [GitHub Issues](https://github.com/langfuse/langfuse/issues)

## 总结

遵循这些最佳实践可以确保：

✅ 完整的可观测性覆盖  
✅ 高效的性能监控  
✅ 快速的问题诊断  
✅ 数据驱动的质量改进  
✅ 可控的成本管理  

记住：**好的追踪应该是自动的、一致的、有价值的。**
