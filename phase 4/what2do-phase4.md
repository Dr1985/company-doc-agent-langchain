# Phase 4 — 要做的事情

> **目标**：在 Phase 3 基础问答闭环之上，加入**缓存加速**、**多模型切换**、**文档上传前端**、**用量仪表盘**，让系统从"能用"变成"好用"。
>
> **开发原则**：前后端同步推进，每个功能模块完成后立即联调验证。

---

## 1. Phase 4 核心目标

- [ ] 高频问题缓存加速，减少 LLM 调用成本和延迟
- [ ] 用户可在前端切换模型，支持同步/流式模式下对比不同模型的回答
- [ ] 前端支持直接上传文档（不再只能用 API 上传）
- [ ] 管理员可查看基础用量统计（问答次数、Token 消耗、文档数量）
- [ ] 代码仓库结构规范化（拆分大文件、常量化魔法数字）

---

## 2. 前端 — 新功能与改进

### 2.1 P0：文档上传功能（documents.html）

> 当前只能在 Swagger 里调 API 上传，Phase 4 要把上传做到文档管理页面里。

- [ ] 上传按钮 + 文件选择弹窗（支持 PDF / DOCX / TXT / MD）
- [ ] 拖拽上传区域（drag & drop）
- [ ] 上传进度条
- [ ] 上传成功后自动刷新文档列表
- [ ] 文件大小和类型校验（前端预检 + 后端兜底）
- [ ] 上传失败时的错误提示（文件过大、格式不支持等）

### 2.2 P0：模型选择器（chat.html）

> 当前后台自动选择模型，用户无法干预。Phase 4 允许用户在聊天页手动切换模型。

- [ ] 聊天页顶部模型下拉选择器
- [ ] 列出可用模型名称（如 `deepseek-chat`、`nvidia/nemotron-3-super-120b-a12b:free` 等）
- [ ] 切换模型后，下一次发送消息使用所选模型
- [ ] 模型列表从后端 API 获取（`GET /models`）
- [ ] 记住用户上次选择的模型（localStorage）
- [ ] 流式模式下也能切换模型

### 2.3 P1：用量仪表盘（新页面 dashboard.html）

> 面向管理员的简单用量看板，帮助了解系统使用情况。

- [ ] 今日/本周/本月问答总次数
- [ ] Token 消耗统计（总 Token、日均 Token）
- [ ] 文档总数 + 就绪/处理中/失败数量
- [ ] 活跃会话数量
- [ ] 最近 7 天问答趋势折线图（用 Chart.js 轻量实现）
- [ ] 顶部导航栏新增"仪表盘"入口

### 2.4 P1：对话管理增强（chat.html）

- [ ] 会话重命名（双击或右键 → 重命名）
- [ ] 会话搜索/筛选（侧边栏会话列表太多了怎么办）
- [ ] 一键复制 AI 回答内容
- [ ] 对 AI 回答点赞/点踩（反馈数据可用于后续评测）

### 2.5 P1：个人中心页增强（login.html 登录后）

- [ ] 展示用户信息（用户名、注册时间）
- [ ] 修改密码
- [ ] 个人 Token 用量统计
- [ ] 登出其他设备会话

---

## 3. 后端 — 新功能与改进

### 3.1 P0：Redis 热点问答缓存

> 当多个用户问相同或高度相似的问题时，直接返回缓存结果，减少 LLM 调用。

- [ ] 引入 Redis 依赖（`redis` + `redis[hiredis]`，加入 `pyproject.toml`）
- [ ] 实现 `CacheService`（`src/services/cache.py`）
  - `get(query_embedding)` → 查找相似缓存的问答
  - `set(query, answer, sources)` → 存入缓存
  - `invalidate(document_id)` → 文档更新后清除相关缓存
- [ ] 缓存 Key 策略：对用户 query 做 embedding，以最近的已缓存 query 的 embedding 做余弦相似度匹配
  - 相似度 ≥ 0.95 → 命中缓存，跳过检索 + LLM 调用
  - 相似度 < 0.95 → 正常走 RAG 链路，结果存入缓存
- [ ] 缓存 TTL：**24 小时**（热点问题当天有效）
- [ ] `/cache/stats` 接口返回缓存命中率统计
- [ ] 缓存命中/未命中指标接入 Prometheus
- [ ] Docker Compose 添加 Redis 服务

### 3.2 P0：多模型切换

- [ ] 新增 `GET /models` 接口，返回可用模型列表（名称 + 提供商 + 上下文长度 + 价格信息）
- [ ] `ChatRequest` 新增可选字段 `model`（不传则使用 `DEFAULT_LLM_MODEL`）
- [ ] 流式/同步问答接口均支持 `model` 参数
- [ ] 前端切换模型后，后续消息全部使用所选模型
- [ ] 模型切换事件记录到 Langfuse

### 3.3 P0：文档上传流程完善

- [ ] 大文件上传支持（当前 50MB 上限，考虑分片上传以支持更大文件）
- [ ] 上传进度回调 → SSE 推送给前端
- [ ] 重复文件检测（相同 MD5 的文件拒绝重复上传）
- [ ] 批量上传（一次选多个文件）
- [ ] 上传后自动触发处理，不需要手动点"同步"

### 3.4 P1：用量统计 API

- [ ] `GET /stats/overview` — 总览（问答次数、Token 消耗、活跃用户、文档数）
- [ ] `GET /stats/daily?days=7` — 每日统计（趋势图数据）
- [ ] `GET /stats/models` — 各模型使用占比
- [ ] `GET /stats/cache` — 缓存命中率
- [ ] 统计数据来自 Langfuse + Prometheus + 数据库查询
- [ ] 新增 `src/services/stats_service.py` 汇总统计逻辑

### 3.5 P2：代码结构规范化

- [ ] 拆分 `src/agent/workflow.py`（当前 ~600 行，过大）：
  - `src/agent/graph_builder.py` — StateGraph 构建逻辑
  - `src/agent/nodes/retrieve.py` — 检索节点
  - `src/agent/nodes/chat.py` — 聊天节点
  - `src/agent/nodes/tool_call.py` — 工具调用节点
  - `src/agent/memory.py` — 长期记忆逻辑
- [ ] 部分硬编码值提取到 `src/config/constants.py`（如 `RRF_K=60`、`PARENT_WINDOW=2`、`DEFAULT_TOP_K=5`）
- [ ] `src/utils/graph.py` 中的 token 估算逻辑提取为 `src/utils/tokens.py`

---

## 4. 单元测试

### 4.1 Redis 缓存测试

- [ ] 测试 `CacheService.set` / `CacheService.get` 基本存取
- [ ] 测试相似查询（相似度 ≥ 0.95）命中缓存
- [ ] 测试不相似查询未命中缓存
- [ ] 测试 `invalidate` 清除指定文档相关缓存
- [ ] 测试缓存过期（TTL）
- [ ] 测试 Redis 不可用时的降级（不阻断问答）
- [ ] 测试缓存命中/未命中指标正确

### 4.2 模型切换测试

- [ ] 测试 `GET /models` 返回可用模型列表
- [ ] 测试 `ChatRequest` 携带 `model` 参数时使用正确模型
- [ ] 测试 `ChatRequest` 不携带 `model` 时使用默认模型
- [ ] 测试流式模式下模型切换正常
- [ ] 测试不存在的模型名返回 400

### 4.3 文档上传测试

- [ ] 测试前端上传 → 后端接收 → MinIO 存储 → 数据库记录 → 后台处理的完整链路
- [ ] 测试重复文件检测（MD5）
- [ ] 测试文件大小超限返回 413
- [ ] 测试不支持的文件类型返回 400
- [ ] 测试空文件上传返回 400

### 4.4 用量统计测试

- [ ] 测试 `GET /stats/overview` 返回数据结构正确
- [ ] 测试 `GET /stats/daily` 返回正确天数的数据
- [ ] 测试 `GET /stats/models` 返回各模型占比
- [ ] 测试 `GET /stats/cache` 返回命中率

### 4.5 前端页面测试

- [ ] 测试 documents.html 包含上传按钮和拖拽区域
- [ ] 测试 chat.html 包含模型选择器
- [ ] 测试 dashboard.html 可正常加载
- [ ] 测试导航栏在三个主要页面间的一致性

---

## 5. 交付物清单

- [ ] 前端：文档上传功能（drag & drop + 进度条）
- [ ] 前端：模型选择器（chat.html）
- [ ] 前端：用量仪表盘（dashboard.html，新页面）
- [ ] 前端：会话管理增强（重命名、搜索、复制回答）
- [ ] 后端：Redis 缓存服务 + 相似查询匹配
- [ ] 后端：`GET /models` + `GET /stats/*` 系列 API
- [ ] 后端：文档上传流程完善（MD5 去重、批量上传）
- [ ] 后端：代码结构规范化（workflow 拆分、常量提取）
- [ ] Docker Compose：新增 Redis 服务
- [ ] 单元测试全部通过
- [ ] `phase 4/what2do-phase4.md` 全部打勾

---

## 6. Phase 4 明确不做的事情

- [ ] 不做 OCR 图片文字提取（Phase 5）
- [ ] 不做表格结构化提取（Phase 5）
- [ ] 不做 Rerank 重排序（Phase 5）
- [ ] 不做自动文档分类和摘要（Phase 5）
- [ ] 不做相似文档推荐（Phase 5）
- [ ] 不做 RBAC 权限控制（Phase 5）
- [ ] 不做管理后台和知识图谱（Phase 6）
- [ ] 不做多租户隔离（Phase 6）
- [ ] 不做多轮对话中的意图澄清和追问（Phase 5）

---

## 7. 推荐实施顺序

1. **第一步**：后端 Redis 缓存服务（核心性能提升）
2. **第二步**：后端 `GET /models` + 多模型切换链路
3. **第三步**：前端模型选择器（chat.html）
4. **第四步**：前端文档上传（documents.html）
5. **第五步**：后端文档上传流程完善（MD5 去重、批量）
6. **第六步**：后端用量统计 API（`GET /stats/*`）
7. **第七步**：前端用量仪表盘（dashboard.html）
8. **第八步**：前端会话管理增强（重命名、复制、反馈）
9. **第九步**：代码结构规范化（workflow 拆分）
10. **第十步**：单元测试 + 全链路回归
