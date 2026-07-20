# 对话网页部署指引

3 个步骤,把「财经对话助手」上线。预计 30 分钟。

## 总览

```
父母点链接
    ↓
GitHub Pages (chat.html,前端)  ← 免费
    ↓
Cloudflare Worker (worker.js,后端)  ← 免费
    ├── 读 GitHub logs/ 拿今日早报
    └── 调 DeepSeek API
```

---

## 第 1 步:部署 Cloudflare Worker(后端)

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
- 粘贴到 Cloudflare 编辑器(覆盖默认的 hello world 代码)
- 右上角 **Save and deploy**

### 1.4 配置环境变量
- Worker 详情页 → **Settings** → **Variables**(环境变量)
- 添加 3 个:

| Name | Value |
|---|---|
| `DEEPSEEK_API_KEY` | `sk-xxx`(你的 DeepSeek Key,跟早报同一个) |
| `GITHUB_REPO` | `Yaaaaaaa233/a-stock-brief`(你的仓库,带斜杠) |
| `GITHUB_TOKEN` | (见下方,读私有仓库需要) |

**GITHUB_TOKEN 怎么拿**:
- 访问 https://github.com/settings/tokens → **Generate new token (classic)**
- Note 随便填,Expiration 选 `No expiration`(或 1 年)
- Scopes 勾选 `repo`(完整仓库读写)
- 生成后复制 token(只显示一次!),粘贴到 Worker 变量

> 如果你的仓库是 **公开** 的,可以不配 GITHUB_TOKEN

### 1.5 测试 Worker
浏览器访问:`https://<你的-worker-url>/api/skills`

应该返回:
```json
{"skills":[{"id":"brief","name":"早报解读",...}]}
```

如果返回这个,后端就 OK 了 ✅

---

## 第 2 步:部署 chat.html(前端,用 GitHub Pages)

### 2.1 开启 GitHub Pages
- 仓库 → **Settings** → 左侧 **Pages**
- **Source** 选 `Deploy from a branch`
- **Branch** 选 `main` / 文件夹选 `/web` → **Save**

### 2.2 等 1-2 分钟
- 状态栏会变绿,显示:
  ```
  Your site is live at https://Yaaaaaaa233.github.io/a-stock-brief/
  ```

### 2.3 测试访问
打开:
```
https://Yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://<你的-worker-url>
```

注意 URL 后面带 `?api=https://<你的-worker-url>`(首次访问会自动记住,以后不用带)

页面应该显示 5 个技能按钮,点【💬 早报解读】,输入"今天的早报讲了什么",应该能收到 AI 回复 ✅

---

## 第 3 步:在早报简报里加链接

编辑 `config.yaml`,填入 `chat_url`:

```yaml
brief:
  chat_url: "https://Yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://<你的-worker-url>"
```

**注意**:URL 里的 `?` 和 `=` 不需要转义,YAML 字符串直接写。

提交 + push,GitHub Actions 下次跑时,简报末尾会出现:

```
---
💬 进一步了解以上内容,可点此对话: 财经助手
```

(企业微信/钉钉里"财经助手"是可点击链接)

---

## 常见问题

### Q1: 父母打开网页是空白
- 检查 GitHub Pages 状态(仓库 Settings → Pages)
- 确认 URL 路径正确(`chat.html` 在 `/web/` 目录下)
- 检查浏览器控制台(F12)有无报错

### Q2: 父母打开能,但发问没回复
- 检查 Cloudflare Worker 状态(dashboard 看 Requests 有没有调用)
- 检查 Worker 变量是否配齐(尤其是 `DEEPSEEK_API_KEY`)
- 检查 Worker URL 是否正确(chat.html 的 `?api=` 参数)

### Q3: 父母反馈 AI 回答"读不到今天早报"
- 检查仓库 `logs/YYYY-MM.md` 是否存在
- 如果是私有仓库,确认 `GITHUB_TOKEN` 配置正确且未过期
- 测试:Worker URL 直接访问 `https://<worker-url>/api/chat`,看返回的错误信息

### Q4: Cloudflare Workers 国内访问慢
- 大部分时候国内可达(< 500ms)
- 偶尔慢可接受(对话场景不要求实时)
- 实在不稳:可换 Vercel/Netlify(同样免费)

### Q5: 想换/加 skill
- 编辑 `web/skills/*.md`(改提示词)
- 或加新文件,然后在 `web/worker.js` 的 `SKILLS_META` 加一项
- push 后 Worker 自动读到最新(无缓存)

### Q6: 想让父母清除对话历史
- 网页右上角有 🗑 按钮,点击即可清除当前模式的历史
- 或者让父母清浏览器缓存

---

## 后续可选优化

- **加访问口令**:Worker 加一个 `PASSWORD` 变量,前端首次访问要输入
- **限制访问频率**:Worker 用 KV 记录 IP,防止滥用
- **流式输出**:Worker 改用 SSE,前端逐字显示(体验更好,代码复杂度高)
- **语音输入**:chat.html 加 Web Speech API,父母可以说话提问
- **导出对话**:前端加导出按钮,把对话保存为图片/文本
