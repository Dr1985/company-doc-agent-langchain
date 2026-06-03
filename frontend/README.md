# Vue 3 小前端（Phase 3）

这是 `company-agent` 的一个最小可用前端页面，放在 `frontend/` 目录下，用来演示 Phase 3 的基础问答闭环：

1. 登录并创建会话
2. 选择要参与检索的文档
3. 先调用 `retrieve` 找到相关 chunk
4. 把检索结果拼成上下文，再调用 `chat` 做单轮问答
5. 显示回答和引用来源

## 本地运行

```powershell
Set-Location D:\Projects\company-agent\frontend
npm install
npm run dev
```

默认会访问：

- 后端 API：`http://127.0.0.1:8000/api/v1`
- 前端开发服务器：`http://localhost:5173`

如果你的后端 API 地址不同，可以直接在页面里修改 Base URL，或者创建 `.env` 文件覆盖默认值。

## 环境变量

复制 `.env.example` 为 `.env`：

```powershell
Copy-Item .env.example .env
```

然后修改其中的 `VITE_API_BASE_URL`。

## 页面做了什么

- 支持登录和创建会话 token
- 支持文档列表浏览与选择
- 支持检索并问答
- 支持显示检索结果与最近 5 条本地历史
- 支持清空当前会话历史

