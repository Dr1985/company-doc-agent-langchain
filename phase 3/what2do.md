# Phase 3 要做的事情

> 目标：把现有 `src/agent` 的对话能力接上"文档检索 + 引用来源"，做成可用的基础问答闭环。
>
> **开发原则：先做 Vue 3 页面原型，确认后再做后端 API**，前后端视为同一阶段的整体交付。

## 1. Phase 3 的核心目标

- [x] 用户提问后，系统能返回基于知识库的答案
- [x] 答案必须来自检索到的文档片段，不能凭空编造
- [x] 回答结果里要带上引用来源（文档名 / chunk / 相似度）
- [x] 当知识库没有足够相关内容时，系统要明确拒答或说明"未检索到足够资料"

## 2. 前端 — Vue 3 页面原型

> **原则：先产出页面原型 / 交互稿，确认后再实现对应的后端 API。**

### 2.1 P0：登录 / 会话页

- [x] 登录表单（用户名 + 密码）
- [x] 注册表单
- [x] 登录后展示用户 token 信息、过期时间
- [x] 会话列表（创建 / 切换 / 删除会话）
- [x] 当前会话高亮标识

### 2.2 P0：问答页（聊天框 + 引用来源 + 历史区）

- [x] 聊天消息列表（区分用户消息 / AI 消息）
- [x] 消息输入框 + 发送按钮（支持 Enter 快捷发送）
- [x] 同步回答模式
- [x] 流式回答模式（SSE 逐字输出）
- [x] AI 回答底部展示引用来源（文档名、chunk 摘要、相似度）
- [x] 点击引用来源可展开查看详细 chunk 内容
- [x] 历史消息回看（当前会话内）
- [x] 清空当前会话按钮
- [x] 拒答提示样式（当知识库无相关内容时）
- [x] Markdown 渲染（标题、粗体、列表、代码块、表格等）

### 2.3 P1：文档选择侧栏 / 结果预览区

- [x] 已入库文档列表（展示文档状态、chunk 数、更新时间）
- [x] 文档就绪 / 处理中 / 失败 状态标识
- [x] 可勾选文档以限定检索范围
- [x] 未就绪文档灰显不可选
- [x] 选中文档后问答仅检索所选文档（通过 localStorage 传递 document_ids）
- [x] 刷新列表自动同步 MinIO，清理已删除文件的数据库记录

## 3. 需要补的后端能力

### 3.1 RAG 主流程

- [x] 在现有 `src/agent/workflow.py` 流程中接入文档检索结果
- [x] 用户提问时，先检索相关 chunk，再把检索结果送给 LLM
- [x] 保留现有 LangGraph / tool-call / long-term memory 机制，不重写整套 agent

### 3.2 检索能力

- [x] 接入 `src/retrieval/retriever.py` 到问答主流程
- [x] 实现向量相似度检索结果的整理与排序
- [x] 补上 BM25 关键词检索
- [x] 实现混合检索融合策略（向量 + BM25，RRF 融合）
- [x] 支持元数据过滤（document_ids 限定检索范围）
- [x] 支持 chunk 命中后回溯父文档上下文（parent document recall，window=2）

### 3.3 回答与引用

- [x] 设计 RAG prompt，让模型只根据检索资料回答
- [x] 设计引用编号规则（`【1】`、`【2】`）
- [x] 返回 `sources` / `citations` 给前端展示
- [x] 在结果中保留文档名、chunk 序号、内容摘要、score 等信息

### 3.4 接口层

- [x] 让 `src/interface/interaction.py` 支持基础问答的完整输出
- [x] 保持 `/chat` 作为主入口
- [x] 补充统一的响应结构（检索结果 + 答案 + 引用来源）
- [x] `POST /auth/login` — 用户登录
- [x] `POST /auth/session` — 创建会话
- [x] `GET /auth/sessions` — 获取会话列表
- [x] `GET /documents/documents` — 文档列表
- [x] `GET /documents/documents/{doc_id}` — 文档详情（状态、chunk 数、更新时间）
- [x] `POST /documents/retrieve` — 文档检索
- [x] `POST /chatbot/chat` — 同步问答
- [x] `POST /chatbot/chat/stream` — 流式问答
- [x] `GET /chatbot/messages` — 获取会话消息历史
- [x] `DELETE /chatbot/messages` — 清空会话消息
- [x] `POST /documents/sync-minio` — MinIO 同步（补充接口）

## 4. 单元测试

### 4.1 检索模块测试

- [x] 测试 `src/retrieval/retriever.py` 向量检索：正常返回 Top-K 结果
- [x] 测试向量检索：空查询 / 无匹配结果时返回空列表
- [x] 测试 BM25 关键词检索：基本查询返回结果
- [x] 测试混合检索融合策略：向量 + BM25 结果合并排序
- [x] 测试元数据过滤：document_ids 筛选生效
- [x] 测试父文档回溯：chunk 命中后能获取完整父文档上下文

### 4.2 RAG 问答链路测试

- [x] 测试 `src/agent/workflow.py`：检索结果正确拼入 prompt 送给 LLM
- [x] 测试正常问答：返回带引用来源的答案
- [x] 测试拒答机制：知识库无相关内容时返回拒答提示
- [x] 测试引用提取：sources / citations 字段格式正确
- [x] 测试多 chunk 命中：多个相关片段都出现在引用中
- [x] 测试 document_ids 通过 ChatRequest → GraphState 完整传递

### 4.3 接口层测试

- [x] 测试 `POST /chatbot/chat`：正常问答返回 200
- [x] 测试 `POST /chatbot/chat/stream`：SSE 流式输出正常
- [x] 测试 `POST /documents/retrieve`：检索接口返回正确格式
- [x] 测试 `GET /documents/documents`：文档列表返回正确
- [x] 测试 `GET /documents/documents/{doc_id}`：文档详情返回正确
- [x] 测试 `GET /chatbot/messages`：历史消息返回正确
- [x] 测试 `DELETE /chatbot/messages`：清空会话生效
- [x] 测试 Schema 层边界（空内容、超长、XSS、null byte 等）

### 4.4 边界与异常测试

- [x] 测试空问题（空字符串 / 仅空白）的处理
- [x] 测试超长问题的截断处理
- [x] 测试检索返回大量结果时的截断与排序
- [x] 测试 LLM 调用超时 / 失败时的 fallback 处理
- [x] 测试 BM25 边界（单 token、长文档、空语料库、空查询）
- [x] 测试 SourceCitation 边界（大 ID、特殊字符）
- [x] 测试 Schema 验证（XSS script 标签、null byte）

## 5. Phase 3 的交付物

- [x] Vue 3 登录 / 会话页原型（P0）— `frontend/login.html`
- [x] Vue 3 问答页原型（P0）— `frontend/chat.html`
- [x] Vue 3 文档选择侧栏原型（P1）— `frontend/documents.html`
- [x] 单轮问答可用
- [x] 文档检索可用
- [x] 回答带来源可追溯
- [x] 无相关资料时可拒答
- [x] 后端链路可稳定跑通
- [x] 单元测试全部通过（103 tests, 0 failures）

## 6. Phase 3 明确不做的事情

- [x] 不做 Redis 热点问答缓存（Phase 4）
- [x] 不做多模型路由配置与对比（Phase 4）
- [x] 不做 OCR、表格提取、Rerank、自动分类、摘要、相似文档推荐（Phase 5）
- [x] 不做 RBAC 权限控制（Phase 5）
- [x] 不做管理后台和知识图谱（Phase 6）
