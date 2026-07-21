# 腾讯云函数 SCF 部署指南

## 总览

```
父母手机 → GitHub Pages(网页,可达)
               ↓ fetch API
            腾讯云 SCF(国内,极快)
               ↓
            DeepSeek API
               ↓
            GitHub/jiDelivr(读今日早报)
```

**网页放 GitHub Pages** + **API 放腾讯云 SCF** = 国内全部可达,零成本。

---

## 第 1 步:注册腾讯云 + 实名认证(5 分钟)

1. 打开 https://cloud.tencent.com/register
2. 微信扫码注册(最方便)
3. 进控制台 → 右上角头像 → **账号信息** → **实名认证**
4. 选 **个人认证** → 身份证 + 人脸识别 → 几分钟完成

> 不实名无法用云函数。实名免费,无风险。

---

## 第 2 步:创建云函数(5 分钟)

### 2.1 进入云函数控制台

打开 https://console.tencent.com/scf/index

左侧菜单 → **函数服务**

> 如果是第一次用,会提示"开通云函数",点同意即可。

### 2.2 新建函数

点 **新建** → 选 **从头开始**:

| 字段 | 填什么 |
|---|---|
| **函数名称** | `a-stock` |
| **运行环境** | `Python 3.11` |
| **函数类型** | `Web 函数` |
| **地域** | `广州` 或 `上海`(选离你近的) |

点 **完成**。

### 2.3 配置入口

进入函数 → **函数代码** tab → 右上角选 **"在线编辑"**

**清空**默认代码,粘贴本仓库 `scf/index.py` 的全部内容。

下方有 **"依赖安装"** 或 **requirements.txt** 输入框:

```
requests>=2.31.0
```

点 **"安装依赖"** 或 **"保存"**。

### 2.4 配置环境变量

函数详情页 → **函数配置** tab → **编辑** → **环境变量** → **添加**:

| Key | Value |
|---|---|
| `DEEPSEEK_API_KEY` | `sk-58f7d63754884e13b85d4c33e9ae8403` |
| `GITHUB_REPO` | `Yaaaaaaa233/a-stock-brief` |
| `PUBLIC_REPO` | `true` |

**保存**。

### 2.5 获取访问 URL

函数详情页 → **触发管理** tab:

你应该看到一个 **API 网关触发器**,URL 形如:
```
https://service-xxxx.gz.apigw.tencentcs.com/release/
```

**记下这个 URL**。

> 如果没有触发器:点 **创建触发器** → 触发方式选 **API 网关触发** → 确认

### 2.6 测试

浏览器直接访问:
```
https://service-xxxx.gz.apigw.tencentcs.com/release/api/health
```

应返回:
```json
{"ok":true,"service":"a-stock-scf","has_deepseek":true,...}
```

再用 curl 测试 POST:
```bash
curl -X POST "https://service-xxxx.gz.apigw.tencentcs.com/release/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","history":[]}'
```

应返回 `{"reply":"..."}`

---

## 第 3 步:把 SCF URL 告诉我

把你的 SCF URL 发我(类似 `https://service-xxxx.gz.apigw.tencentcs.com/release/`):

我会帮你:
1. 改 `config.yaml` 的 `chat_url`
2. push 触发推送
3. 简报末尾的链接自动指向 SCF URL

---

## 第 4 步:测试完整链路

打开:
```
https://yaaaaaaa233.github.io/a-stock-brief/chat.html?api=https://service-xxxx.gz.apigw.tencentcs.com/release/
```

- 网页秒开(GitHub Pages)
- 输入"你好",2-3 秒回复(腾讯云 SCF,国内极快)
- 不卡在"思考中"

---

## 常见问题

### Q1:首次调用慢
SCF 首次调用有冷启动(1-3 秒),之后快。可以通过"预置并发"优化,但免费额度不需要。

### Q2:调用次数超了
免费额度 100 万次/月,每天 1 万次也才 30 万次,完全够。

### Q3:网络超时
检查 SCF 的 VPC 配置(默认无 VPC,可以访问公网)。如果有问题,删函数重建。

### Q4:代码更新后要重新部署吗
在线编辑 → 修改 → 点"部署"。如果用 ZIP 包,重新上传。

### Q5:SCF URL 末尾的 `/release/` 是什么
是 API 网关的发布环境。实际请求时,SCF handler 收到的 path 是去掉这个前缀的。`/release/api/chat` → handler 收到 `/api/chat`。不用管它。

---

## 成本

| 资源 | 每月免费额度 | 你的用量 | 实际开销 |
|---|---|---|---|
| 调用次数 | 100 万次 | ~1500 | ¥0 |
| 资源时长 | 40 万 GB-秒 | ~1875 | ¥0 |
| 出流量 | 5 GB | ~1.5 MB | ¥0 |
| API 网关 | 100 万次/月 | ~1500 | ¥0 |
| **总** | | | **¥0** |
