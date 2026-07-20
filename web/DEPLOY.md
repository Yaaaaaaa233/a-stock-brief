# 对话网页部署指引(私有仓库 + KV 全缓存版)

支持**私有仓库**,父母访问最快(Worker 只读 KV,完全不依赖 GitHub)。

## 总览

```
GitHub Actions 跑完早报
    ↓ 自动同步 logs/skills/config 到 Cloudflare KV
    
父母点链接 → Cloudflare Worker(国内可达)
              ↓ 只读 KV(50ms)
              ↓ 调用 DeepSeek API
              (完全不接触 GitHub)
```

**优势**:仓库私有 + 父母访问最快 + 不受 GitHub 网络影响。

---

## 第 1 步:Cloudflare 准备

### 1.1 注册 Cloudflare
访问 https://dash.cloudflare.com/sign-up 注册(免费,不需要信用卡)。

### 1.2 创建 KV namespace(数据存储)
- Dashboard 左侧 → **Workers & Pages** → **KV** → **Create a namespace**
- Name 填 `ASTOCK_CACHE` → **Add**
- 创建后,**记录 Namespace ID**(后面要用)

### 1.3 创建 Worker
- Dashboard → **Workers & Pages** → **Create application** → **Create Worker**
- Name 填 `astock-chat` → **Deploy**
- **Edit code** → 把本仓库 `web/worker.js` 全选复制粘贴进去 → **Save and deploy**
- 记录 Worker URL,如 `https://astock-chat.<你的子域>.workers.dev`

### 1.4 绑定 KV 到 Worker
- Worker 详情页 → **Settings** → **Variables** → **KV Namespace Bindings** → **Add binding**:
  - Variable name: **`KV`**(必须叫这个)
  - KV namespace: 选 `ASTOCK_CACHE`
- **Save and deploy**

### 1.5 配置环境变量
Worker 详情页 → **Settings** → **Variables** → **Environment Variables**,添加:

| Name | Value |
|---|---|
| `DEEPSEEK_API_KEY` | `sk-xxx`(同早报用的 Key) |
| `GITHUB_REPO` | `Yaaaaaaa233/a-stock-brief` |

(不需要配 `GITHUB_TOKEN`,因为 KV 全缓存,Worker 不直接访问 GitHub)

### 1.6 获取 Cloudflare API Token(GitHub Actions 用)
- 访问 https://dash.cloudflare.com/profile/api-tokens → **Create Token**
- 选 **"Edit Cloudflare Workers"** 模板 → Continue to summary
- **Create Token** → 复制 token(只显示一次!)
- 同时记录 **Account ID**(dashboard 右侧栏,或在 Worker 页面能看到)

### 1.7 测试 Worker
浏览器访问:`https://<worker-url>/api/skills`,应该返回 JSON。

---

## 第 2 步:GitHub Secrets 配置

仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**,添加:

| Secret | 来源 |
|---|---|
| `WECOM_WEBHOOK` | 早报推送 webhook |
| `DEEPSEEK_API_KEY` | DeepSeek Key |
| `CF_API_TOKEN` | 上一步 1.6 创建的 Cloudflare Token |
| `CF_ACCOUNT_ID` | 上一步 1.6 看到的 Account ID |
| `KV_NAMESPACE_ID` | 上一步 1.2 创建 KV 时的 Namespace ID |

---

## 第 3 步:GitHub Pages(部署 chat.html)

- 仓库 → **Settings** → **Pages**
- Source:`Deploy from a branch`
- Branch:`main` / 文件夹 `/web` → **Save**
- 等 1-2 分钟,访问 `https://Yaaaaaaa233.github.io/a-stock-brief/`

---

## 第 4 步:配 chat_url

编辑 `config.yaml`:

```yaml
brief:
  chat_url: "https://Yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://<worker-url>"
```

push 后,下次早报推送末尾出现对话链接。

---

## 工作流(全自动)

每次 GitHub Actions 跑(每天 8:00 或手动触发):

1. 抓数据 → LLM 分析 → 生成简报 ✅
2. 推送到企业微信群 ✅
3. 归档到 `logs/YYYY-MM.md`,commit 到仓库 ✅
4. **同步 logs/skills/config 到 Cloudflare KV** ✅

之后父母访问 Worker 时,Worker 只从 KV 读(50ms),完全不依赖 GitHub,访问速度跟仓库公开/私有无关。

---

## 常见问题

### Q1: 父母打开网页是空白
- F12 看控制台报错
- 确认 GitHub Pages 已开启,URL 路径正确

### Q2: 父母发的消息没回复
- 测试 `https://<worker-url>/api/skills` 是否返回 JSON
- 检查 `DEEPSEEK_API_KEY` 是否配
- Worker 详情页 → **Real-time Logs** 看错误

### Q3: KV 同步失败
- GitHub Actions 日志看 `同步到 Cloudflare KV` 步骤
- 检查 `CF_API_TOKEN` / `CF_ACCOUNT_ID` / `KV_NAMESPACE_ID` 是否都配了
- Cloudflare API Token 是否有 KV Edit 权限(必须用 "Edit Cloudflare Workers" 模板)

### Q4: 改了 skill 但 Worker 没读到最新
- 因为 KV 有缓存,改 skill 后下一次 GitHub Actions 跑完会自动同步
- 想立刻生效:Cloudflare dashboard → KV → 手动删 `skills:<id>` 键
- 或在 GitHub Actions 手动触发 workflow

### Q5: 父母不挂 VPN 能用吗
**能**。父母只访问 Cloudflare Worker,Worker 只读 Cloudflare KV,**全程不接触 GitHub**。

---

## 备选:仓库公开(更简单)

如果你不在乎公开(代码无敏感信息):
1. 仓库改 Public
2. Worker 配 `PUBLIC_REPO=true`(可选,不用 KV 也能跑,只是慢一点)
3. 完全省略本指引的 KV 配置步骤

但**强烈推荐用 KV 全缓存方案**,因为父母访问最快,且不依赖 GitHub 网络稳定性。
