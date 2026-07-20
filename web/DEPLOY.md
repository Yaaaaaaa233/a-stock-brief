# 对话网页部署指引

3 个步骤,把「财经对话助手」上线。预计 30 分钟。

## 总览

```
父母点链接
    ↓
Cloudflare Worker (国内可达)
    ├── 读 KV 缓存(50ms,优先)         ← 推荐
    ├── 读 jsDelivr CDN(公开仓库)
    ├── 读 GitHub raw(私有仓库,需 token)
    └── 调 DeepSeek API
```

**关键**:父母只访问 Cloudflare Worker,**不直接访问 GitHub**。所以父母不挂 VPN 也能用。

## 仓库公开还是私有?

**强烈建议改成公开仓库**,原因:
1. jsDelivr CDN 国内可达性好(免费加速)
2. 代码无敏感信息(API key 都在 GitHub Secrets)
3. 早报内容本身就是给父母看的,公开无妨
4. 省去配置 GITHUB_TOKEN 的麻烦

设置:仓库 → Settings → 最底部 Danger Zone → Change visibility → Public

如果想保持私有:也可以,但要配置 `GITHUB_TOKEN`,且不能用 jsDelivr(国内访问会慢一些)。

---

## 第 1 步:部署 Cloudflare Worker

### 1.1 注册 Cloudflare
- 访问 https://dash.cloudflare.com/sign-up
- 邮箱 + 密码注册(免费,不需要信用卡)

### 1.2 创建 Worker
- 登录后进入 dashboard
- 左侧 **Workers & Pages** → **Create application** → **Create Worker**
- 名字随便填(如 `astock-chat`)→ **Deploy**
- 部署后会有 URL,如 `https://astock-chat.<你的子域>.workers.dev`
- 点 **Edit code**(编辑代码)

### 1.3 粘贴代码
- 打开本仓库的 `web/worker.js`,**全选复制**
- 粘贴到 Cloudflare 编辑器(覆盖默认代码)
- 右上角 **Save and deploy**

### 1.4 配置环境变量
Worker 详情页 → **Settings** → **Variables**

**必填**:

| Name | Value |
|---|---|
| `DEEPSEEK_API_KEY` | `sk-xxx`(同早报用的 DeepSeek Key) |
| `GITHUB_REPO` | `Yaaaaaaa233/a-stock-brief` |

**公开仓库选填**(启用 jsDelivr 加速):

| Name | Value |
|---|---|
| `PUBLIC_REPO` | `true` |

**私有仓库必填**:

| Name | Value |
|---|---|
| `GITHUB_TOKEN` | GitHub PAT(https://github.com/settings/tokens,勾 `repo` scope) |

### 1.5(可选,推荐)启用 KV 加速

KV 让 Worker 在边缘节点缓存内容,首次访问后只用 50ms 拿数据。

- Cloudflare dashboard → **Workers & Pages** → **KV** → **Create a namespace**
- Namespace name 填 `ASTOCK_CACHE** → **Add**
- 回到 Worker → **Settings** → **Variables** → **KV Namespace Bindings** → **Add binding**:
  - Variable name: `KV`
  - KV namespace: 选 `ASTOCK_CACHE`
- **Save and deploy**

代码里已经写好了 KV 逻辑(自动),启用后立即生效。

### 1.6 测试 Worker
浏览器访问:`https://<你的-worker-url>/api/skills`

应该返回:`{"skills":[{"id":"brief",...}]}` ✅

---

## 第 2 步:部署 chat.html(前端)

### 2.1 开启 GitHub Pages
- 仓库 → **Settings** → **Pages**
- Source 选 `Deploy from a branch`
- Branch 选 `main` / 文件夹选 `/web` → **Save**

### 2.2 等 1-2 分钟,访问:
```
https://Yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://<你的-worker-url>
```

注意 URL 后面带 `?api=https://<你的-worker-url>`(首次访问会自动记住,以后不用带)

---

## 第 3 步:在简报里加链接

编辑 `config.yaml`:

```yaml
brief:
  chat_url: "https://Yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://<你的-worker-url>"
```

push 后,下次早报推送末尾会出现:

```
💬 进一步了解以上内容,可点此对话: 财经助手
```

---

## 常见问题

### Q1: 父母打开网页是空白
- 检查 GitHub Pages 状态
- 检查 URL 路径(应在 `/web/` 目录下)
- F12 看控制台报错

### Q2: 父母不挂 VPN 能用吗?
**能**。父母只访问 Cloudflare Worker(国内可达),Worker 内部从 Cloudflare 数据中心访问 GitHub,不受父母网络影响。

### Q3: 觉得慢怎么优化?
1. 启用 KV 缓存(见 1.5)
2. 仓库改公开(用 jsDelivr CDN)
3. 仍然慢:可能是 DeepSeek API 慢(主要瓶颈)

### Q4: 想换/加 skill
- 编辑 `web/skills/*.md`
- push 后 Worker 自动读到(skill 缓存 1 小时,可等也可在 Cloudflare 手动清 KV)
- 加新 skill:新建 md 文件 + 在 `web/worker.js` 的 `SKILLS_META` 加一项

### Q5: 对话日志存哪里?
当前不存(对话是临时会话,关掉就消失)。
如需存储,推荐 Cloudflare D1(免费 SQLite),不建议存 GitHub(commit 太慢)。
