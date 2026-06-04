# Phase 4 — 要做的事情

> **目标**：在 Phase 3 基础问答闭环之上，加入**缓存加速**、**多模型切换**、**文档上传前端**、**用量仪表盘**，让系统从"能用"变成"好用"。
>
> **开发原则**：前后端同步推进，每个功能模块完成后立即联调验证。

---

## 1. Phase 4 核心目标

- [x] 高频问题缓存加速，减少 LLM 调用成本和延迟
- [x] 用户可在前端切换模型，支持同步/流式模式下对比不同模型的回答
- [x] 前端支持直接上传文档（不再只能用 API 上传）
- [x] 管理员可查看基础用量统计（问答次数、Token 消耗、文档数量）
- [x] 代码仓库结构规范化（拆分大文件、常量化魔法数字）

---

## 2. 前端 — 新功能与改进

### 2.1 P0：文档上传功能（documents.html）

- [x] 上传按钮 + 文件选择弹窗（支持 PDF / DOCX / TXT / MD）
- [x] 拖拽上传区域（drag & drop）
- [x] 上传进度条
- [x] 上传成功后自动刷新文档列表
- [x] 文件大小和类型校验（前端预检 + 后端兜底）
- [x] 上传失败时的错误提示（文件过大、格式不支持等）

### 2.2 P0：模型选择器（chat.html）

- [x] 聊天页顶部模型下拉选择器
- [x] 列出可用模型名称（从 `GET /models` API 获取）
- [x] 切换模型后，下一次发送消息使用所选模型
- [x] 模型列表从后端 API 获取（`GET /models`）
- [x] 记住用户上次选择的模型（localStorage）
- [x] 流式模式下也能切换模型

### 2.3 P1：用量仪表盘（新页面 dashboard.html）

- [x] 今日/本周/本月问答总次数
- [x] Token 消耗统计（总 Token、日均 Token）
- [x] 文档总数 + 就绪/处理中/失败数量
- [x] 活跃会话数量
- [x] 最近 7 天问答趋势折线图（用 Chart.js 轻量实现）
- [x] 顶部导航栏新增"仪表盘"入口（四个页面统一导航）

### 2.4 P1：对话管理增强（chat.html）

- [x] 会话重命名（双击会话名 → 编辑 → Enter 保存）
- [x] 会话搜索/筛选（侧边栏搜索框）
- [x] 一键复制 AI 回答内容
- [x] 对 AI 回答点赞/点踩（反馈数据可用于后续评测）

### 2.5 P1：个人中心页增强（login.html 登录后）

- [x] 展示用户信息（用户名）
- [x] 修改密码
- [x] 仪表盘入口

---

## 3. 后端 — 新功能与改进

### 3.1 P0：Redis 热点问答缓存

- [x] 引入 Redis 依赖（`redis>=5.0.0`，加入 `pyproject.toml`）
- [x] 实现 `CacheService`（`src/services/cache.py`）
  - `get(query_embedding)` → 余弦相似度查找缓存的问答
  - `set(query, answer, sources)` → 存入缓存
  - `invalidate(document_id)` → 文档更新后清除相关缓存
- [x] 缓存策略：对用户 query 做 embedding → 与缓存条目逐一比较余弦相似度
  - 相似度 ≥ 0.95 → 命中缓存，跳过检索 + LLM 调用
  - 相似度 < 0.95 → 正常走 RAG 链路，结果存入缓存
- [x] 缓存 TTL：**24 小时**（热点问题当天有效）
- [x] `CacheService.stats()` 返回缓存状态
- [x] Redis 不可用时自动降级（不阻断问答），日志记录警告

### 3.2 P0：多模型切换

- [x] 新增 `GET /models` 接口（位于 chatbot router）
- [x] `ChatRequest` 新增可选字段 `model`
- [x] 流式/同步问答接口均支持 `model` 参数
- [x] `workflow.py` `get_response()` 和 `get_stream_response()` 接受 `model`
- [x] 缓存绕过：带 `model` 参数的请求不走缓存（确保不同模型独立回答）

### 3.3 P0：文档上传流程完善

- [x] MD5 去重：上传时计算文件 MD5 → 与已有文档比对 → 重复则返回 409
- [x] `Document` 模型新增 `md5_hash` 字段
- [x] 上传后自动触发后台处理（已有 BackgroundTasks 机制）
- [ ] 分片上传大文件（留待 Phase 5）

### 3.4 P1：用量统计 API

- [x] `GET /stats/overview` — 总览（文档数、缓存状态等）
- [x] `GET /stats/daily?days=7` — 每日统计（趋势图数据）
- [x] `GET /stats/models` — 各模型使用占比
- [x] `GET /stats/cache` — 缓存状态
- [x] 新增 `src/services/stats_service.py` 汇总统计逻辑
- [x] 新增 `src/interface/stats.py` 统计路由

### 3.5 P2：代码结构规范化

- [x] 硬编码值提取到 `src/config/constants.py`
  - `RRF_K=60`、`PARENT_WINDOW=2`、`DEFAULT_TOP_K=5`
  - `CACHE_MAX_ENTRIES=500`、`CACHE_SIMILARITY_THRESHOLD=0.95`、`CACHE_TTL_SECONDS=86400`
- [x] `hybrid.py` 和 `cache.py` 引用常量
- [ ] workflow.py 拆分为独立节点文件（留待后续迭代）

---

## 4. 单元测试

### 4.1 Redis 缓存测试

- [x] 余弦相似度：相同向量 / 正交向量 / 相反向量 / 空向量 / 相似但不相同
- [x] 相似度低于阈值不匹配
- [x] Redis 不可用时 `get()` 返回 None
- [x] Redis 不可用时 `set()` 不抛异常
- [x] Redis 不可用时 `invalidate()` 不抛异常
- [x] Redis 不可用时 `stats()` 返回 `ready: false`

### 4.2 模型切换测试

- [x] `ChatRequest` 携带 `model` 参数
- [x] `ChatRequest` 不携带 `model` 时 `model is None`
- [x] 无效模型名不会触发 Pydantic 校验失败

### 4.3 文档上传测试

- [x] MD5 相同内容产生相同哈希
- [x] MD5 不同内容产生不同哈希

### 4.4 用量统计测试

- [x] `get_overview()` 返回字典含必要字段
- [x] `get_daily_trend()` 返回正确天数
- [x] `get_model_usage()` 返回列表非空

### 4.5 前端页面测试

- [x] chat.html 含模型选择器
- [x] documetns.html 含上传区域
- [x] 导航栏四页面一致性（含仪表盘入口）

---

## 5. 交付物清单

- [x] 前端：文档上传功能（drag & drop + 进度条）
- [x] 前端：模型选择器（chat.html）
- [x] 前端：用量仪表盘（dashboard.html，新页面）
- [x] 前端：会话管理增强（重命名、搜索、复制回答、点赞/点踩）
- [x] 前端：个人中心增强（修改密码）
- [x] 后端：Redis 缓存服务（相似查询匹配、降级、过期、失效）
- [x] 后端：`GET /models` + `GET /stats/*` 系列 API（5 个新端点）
- [x] 后端：文档上传 MD5 去重
- [x] 后端：代码结构规范化（`constants.py`、常量引用）
- [x] 单元测试：137 passed, 0 failures（新增 22 个测试）
- [x] `phase 4/what2do-phase4.md` 全部打勾

---

## 6. Phase 4 明确不做的事情

- [x] 不做 OCR 图片文字提取（Phase 5）
- [x] 不做表格结构化提取（Phase 5）
- [x] 不做 Rerank 重排序（Phase 5）
- [x] 不做自动文档分类和摘要（Phase 5）
- [x] 不做相似文档推荐（Phase 5）
- [x] 不做 RBAC 权限控制（Phase 5）
- [x] 不做管理后台和知识图谱（Phase 6）
- [x] 不做多租户隔离（Phase 6）
- [x] 不做多轮对话中的意图澄清和追问（Phase 5）
