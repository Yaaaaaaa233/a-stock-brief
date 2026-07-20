# A 股财经早报

每天北京 8:00 自动抓取财经新闻 + 政策 + 行情,经 LLM 分析 + 防幻觉校验后,推送到家庭企业微信群。专为父母设计,零学习成本。

## 特性

- **零服务器**:GitHub Actions 免费定时,无需 VPS
- **零运维**:父母只需进企业微信群,无需关注任何公众号
- **七层防幻觉**:结构化任务、强制 evidence、程序校验、fact-check 门禁……
- **插件化数据源**:加新源改配置即可,80% 场景不动代码
- **降级兜底**:LLM 挂了推原始新闻,绝不会因故障沉默

## 数据流

```
GitHub Actions (北京 8:00)
    ↓
抓取(财联社 / 国务院 / 央行 / 东财 / akshare) → 去重聚类
    ↓
LLM 分析(每条独立分析,带 IRON RULE + evidence 校验)
    ↓
格式化为父母友好 markdown
    ↓
fact-check 事实校验门禁(规则引擎)
    ↓
推送到企业微信群机器人
```

## 目录结构

```
Toolbox/A/
├── .github/workflows/daily.yml   # GitHub Actions 定时
├── config.yaml                   # 主配置(板块、源、推送规则)
├── requirements.txt
├── prompts/
│   └── analyzer.md               # LLM 分析器 prompt(含 IRON RULE)
├── src/
│   ├── main.py                   # 主入口
│   ├── sources/                  # 数据源(每个源一个文件)
│   │   ├── base.py               # Item / Analysis / BaseSource 抽象
│   │   ├── cls.py                # 财联社电报
│   │   ├── rss.py                # 通用 RSS(国务院 / 央行)
│   │   ├── eastmoney.py          # 东方财富要闻
│   │   └── market.py             # akshare 行情/北向/龙虎榜
│   ├── analyzer/
│   │   ├── llm.py                # DeepSeek 调用 + 防幻觉校验
│   │   └── fact_check.py         # 事实校验门禁
│   ├── push/
│   │   ├── format.py             # 简报 markdown 生成
│   │   └── wecom.py              # 企业微信推送
│   └── utils/
│       └── dedupe.py             # 去重聚类
├── tests/
│   └── test_dry_run.py           # 本地测试(不真实推送)
└── state/                        # 运行状态(自动生成)
```

---

## 部署步骤(给你)

### 第 1 步:本地验证(必做,先确认能跑)

```bash
cd /Users/yea/Desktop/Life/Toolbox/A

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 测试 1:只抓数据,不调 LLM(快速看数据源是否正常)
python tests/test_dry_run.py --no-llm

# 测试 2:完整流程(需要先有 DEEPSEEK_API_KEY)
export DEEPSEEK_API_KEY="sk-xxx"
python tests/test_dry_run.py
```

生成的简报会保存到 `state/preview.md` 并打印到终端。**确认内容质量后再上 GitHub**。

### 第 2 步:获取推送配置 + LLM Key

| 密钥 | 获取方式 |
|---|---|
| **WxPusher 配置**(推荐) | 见下方"WxPusher 配置步骤" |
| **DeepSeek API Key** | https://platform.deepseek.com 注册 → 充值 ¥10 → 创建 API Key |
| **GitHub 账号** | 已有 |

> 钉钉 / 企业微信 配置方式见 README 末尾"推送渠道说明"。

#### 钉钉机器人创建步骤(3 分钟)

1. **建钉钉群**:打开钉钉 →右上角「+」→「发起群聊」→ 拉父母进群(至少 2 人)
2. **添加机器人**:
   - 进群 → 右上角 **「群设置」**(齿轮图标)
   - 找到 **「群助手」** → **「添加机器人」** → **「自定义」**(通过 webhook 接入自定义服务)
   - 注意:**不要选**「AI 助手」「智能机器人」(那些是对话型,不是 webhook)
3. **配置机器人**:
   - 机器人名字:随便(如「早报君」)
   - **安全设置**选 **「自定义关键词」**,关键词填 **「早报」**(简报标题里就含「早报」字样,自动满足)
4. **复制 webhook**:点击「完成」后会显示 webhook URL,形如:
   ```
   https://oapi.dingtalk.com/robot/send?access_token=xxxxxxxxxxxx
   ```
5. **测试**(可选):用 curl 立刻测一下
   ```bash
   curl 'https://oapi.dingtalk.com/robot/send?access_token=你的token' \
      -H 'Content-Type: application/json' \
      -d '{"msgtype":"text","text":{"content":"早报机器人已就绪 ✅"}}'
   ```
   群里出现消息说明 OK。

**关于安全模式**:
- **自定义关键词**(默认推荐):最简单,关键词设「早报」即可,本简报天然包含
- **加签**(更安全):创建机器人时选「加签」模式,会额外给一个 `SEC` 开头的 secret。
  把 secret 也填到 `DINGTALK_SECRET`,代码会自动加签。

### 第 3 步:推到 GitHub

```bash
cd /Users/yea/Desktop/Life/Toolbox/A
git init
git add .
git commit -m "init: A股财经早报"
git branch -M main

# 在 GitHub 网页创建一个【私有】仓库 a-stock-brief,然后:
git remote add origin git@github.com:<你的用户名>/a-stock-brief.git
git push -u origin main
```

**必须私有仓库**(避免 webhook URL 泄露)。

### 第 4 步:配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret,添加:

**必填**:
- `DINGTALK_WEBHOOK` = 你的钉钉 webhook URL
- `DEEPSEEK_API_KEY` = 你的 DeepSeek API Key

**选填**(加签模式才需要):
- `DINGTALK_SECRET` = 钉钉机器人加签 secret(SEC 开头)

### 第 5 步:手动触发测试

仓库 → Actions → "每日财经早报" → Run workflow → 等几分钟看钉钉群是否收到。

成功后,以后每天北京 8:00 自动推送(周末除外)。

### 第 6 步:拉父母进群

在钉钉群里把父母拉进来(或让他们用微信扫码进钉钉群的"互通群")。完成。

---

## 推送渠道说明

支持三种推送渠道,代码自动识别(优先级从高到低):

| 渠道 | 父母体验 | 环境变量 |
|---|---|---|
| **WxPusher**(强烈推荐) | 微信公众号推送,扫一次码即可 | `WXPUSHER_TOKEN` + `WXPUSHER_UIDS` |
| 钉钉机器人 | 装钉钉或互通群 | `DINGTALK_WEBHOOK` [+ `DINGTALK_SECRET`] |
| 企业微信群 | 内部群才支持,外部群不可用 | `WECOM_WEBHOOK` |

### WxPusher 配置步骤(推荐)

1. **打开后台**(浏览器):https://wxpusher.zjiecode.com/admin/
2. 微信扫码登录 → **「应用管理」** → **「新建应用」** → 拿到 `appToken`(AT_xxx)
3. **「二维码管理」** → 创建二维码 → 关联应用 → 把二维码发给父母扫码
4. 父母扫码后**关注「WxPusher 消息服务」公众号**(在微信里)
5. 在 **「用户管理」** 里拿到父母的 UID(UID_xxx)
6. 在 GitHub Secrets 配置:
   - `WXPUSHER_TOKEN` = appToken
   - `WXPUSHER_UIDS` = UID 列表,逗号分隔(如 `UID_aaa,UID_bbb`)

完成后,推送会从「WxPusher 消息服务」公众号发给父母微信,无需她们做任何额外操作。

---

## 配置说明

`config.yaml` 是日常调整的唯一入口:

### 增减关注的板块

```yaml
sectors:
  大金融:
    keywords: [央行, 降准, ...]
  # 加新板块:
  农业:
    keywords: [种业, 玉米, 大豆, 农药, 化肥]
```

### 关闭某个数据源

```yaml
sources:
  eastmoney_news:
    enabled: false    # 改成 false 即可,无需删代码
```

### 调整推送阈值

```yaml
push:
  min_importance: 4   # 提高到 4 星,减少信息量
  max_items: 8        # 一天最多 8 条
```

### 加节假日

```yaml
holidays:
  - 2026-01-01
  - 2026-02-17
```

---

## 防幻觉机制(已内置)

| 层级 | 机制 | 文件 |
|---|---|---|
| 1 | 单条独立分析,不让 LLM 自由发挥 | `analyzer/llm.py` |
| 2 | 强制 JSON 输出,带 evidence 字段 | `prompts/analyzer.md` |
| 3 | 程序校验 evidence 是否在原文 | `sources/base.py:Analysis.validate` |
| 4 | 数字/行情绕开 LLM 走结构化通道 | `sources/market.py` |
| 5 | IRON RULE prompt 硬约束 | `prompts/analyzer.md` |
| 6 | fact-check 规则引擎门禁 | `analyzer/fact_check.py` |
| 7 | 校验失败降级,绝不带病推送 | `main.py` |

校验结果三档:
- **PASS**: 正常推送
- **WARN**: 推送但末尾标注「⚠️ 待确认项」
- **REJECT**: 推送但末尾标注「AI 分析存在问题,已降级」

---

## 故障排查

| 现象 | 排查 |
|---|---|
| 推送没到 | 看 Actions 页面的运行日志;确认 webhook URL 没失效(企业微信机器人可能被删) |
| 新闻很少 | 数据源接口可能变更,本地跑 `python tests/test_dry_run.py --no-llm` 看哪个源空了 |
| LLM 报错 | 确认 DeepSeek 余额;`DEEPSEEK_API_KEY` 是否正确配置在 Secrets |
| 内容有幻觉 | 看 fact-check 日志的 issues;调整 prompt 强约束 |
| 推送很晚 | GitHub Actions 定时不准,延迟 5-15 分钟正常;严重时迁腾讯云函数 |

---

## 后续可扩展

- 接入更多源(券商研报、雪球情绪、华尔街见闻)
- 加 ETF/指数估值表(akshare 有数据)
- 加"政策影响追踪"(同一政策 3/7/30 日后市场表现)
- 迁移到腾讯云函数(国内速度更快,定时更准)
- 反馈闭环:统计父母点赞的简报类型,优化权重

---

## 合规声明

本项目仅做公开信息聚合与整理,不构成任何投资建议。
输出末尾固定标注免责声明,严禁出现"建议买入/卖出"等指令性表述。
