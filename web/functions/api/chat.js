// Pages Function:POST /api/chat
// 单一对话接口

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export async function onRequestOptions() {
  return new Response(null, { headers: CORS_HEADERS });
}

export async function onRequestPost({ request, env }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: '请求格式错误' }, { status: 400, headers: CORS_HEADERS });
  }
  const { message, history } = body;
  if (!message) {
    return Response.json({ error: '缺少 message' }, { status: 400, headers: CORS_HEADERS });
  }
  if (!env.DEEPSEEK_API_KEY) {
    return Response.json({ error: '服务器未配置 DEEPSEEK_API_KEY' }, { status: 500, headers: CORS_HEADERS });
  }

  try {
    const systemPrompt = await buildSystemPrompt(env);
    const reply = await callDeepSeek(systemPrompt, history, message, env);
    return Response.json({ reply }, { headers: CORS_HEADERS });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 502, headers: CORS_HEADERS });
  }
}

function bjNow() {
  return new Date(Date.now() + 8 * 3600 * 1000);
}

function monthStr() {
  const d = bjNow();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function pathToKvKey(path) {
  if (path.startsWith('logs/')) return `logs:${path.split('/').pop().replace('.md', '')}`;
  if (path === 'config.yaml') return 'config:yaml';
  return null;
}

async function fetchFromGitHub(path, env) {
  if (env.KV) {
    const kvKey = pathToKvKey(path);
    if (kvKey) {
      try {
        const v = await env.KV.get(kvKey);
        if (v) return v;
      } catch (e) {}
    }
  }
  const base = env.PUBLIC_REPO === 'true' && !env.GITHUB_TOKEN
    ? `https://cdn.jsdelivr.net/gh/${env.GITHUB_REPO}@main/`
    : `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/`;
  const headers = {};
  if (env.GITHUB_TOKEN) headers['Authorization'] = `token ${env.GITHUB_TOKEN}`;
  const r = await fetch(base + path, { headers });
  if (!r.ok) throw new Error(`GitHub ${path} ${r.status}`);
  return await r.text();
}

async function loadTodayBrief(env) {
  if (env.KV) {
    try {
      const v = await env.KV.get('logs:latest');
      if (v) return v;
    } catch (e) {}
  }
  try {
    const logs = await fetchFromGitHub(`logs/${monthStr()}.md`, env);
    return logs.slice(-3000);
  } catch (e) {
    return '(今日早报暂未生成)';
  }
}

async function loadSectorsConfig(env) {
  try {
    return await fetchFromGitHub('config.yaml', env);
  } catch (e) {
    return '(板块配置加载失败)';
  }
}

async function buildSystemPrompt(env) {
  const [brief, sectors] = await Promise.all([
    loadTodayBrief(env),
    loadSectorsConfig(env),
  ]);

  return `你是财经助手,服务对象是 55-70 岁的中老年 A 股投资者(只用微信,不熟悉专业术语)。

## 今日早报内容(已自动加载)

${brief}

## 板块配置(查询龙头股时严格按此)

${sectors}

## 回答准则

1. **通俗**:遇到专业词用 1 个生活化比喻解释(降准=银行少交保证金)
2. **简洁**:回答不超过 250 字,先结论后原因
3. **客观**:不给具体买卖建议(如"应该买 XX"),但可以解释影响方向
4. **诚实**:早报里没讲到的,直接说"今天早报没提到",再按通用知识回答
5. **风险提示**:提到具体股票时,自动加"投资有风险,仅供参考"
6. **不预测涨跌**:严禁"会涨""必涨""必跌",改为"通常被认为是利好/利空"

## 关于"政策"的严格定义(重要)

✅ **是政策**:
- 国务院 / 央行 / 各部委 / 地方政府正式发文
- 有明确发文单位(如"央行决定""财政部公告")
- 有具体执行措施(降准 0.5% / 补贴延长至 X 年)

❌ **不是政策**:
- 新闻媒体报道"国家可能..."、"据传..."
- 分析师/机构的预测或建议
- 公司公告(这是企业行为)
- 普通时事新闻

**用户问"今天有什么政策"时**,只从今日早报里找符合严格定义的内容,不要把新闻当政策。

## 禁止行为

- ❌ "建议买入/卖出 XX 股票"
- ❌ "会涨/跌 X%"
- ❌ 编造不在配置里的股票
- ❌ 把新闻/传闻说成政策
`;
}

async function callDeepSeek(systemPrompt, history, message, env) {
  const messages = [
    { role: 'system', content: systemPrompt },
    ...(history || []).slice(-10),
    { role: 'user', content: message },
  ];
  const r = await fetch('https://api.deepseek.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.DEEPSEEK_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages,
      max_tokens: 800,
      temperature: 0.5,
      stream: false,
    }),
  });
  if (!r.ok) {
    throw new Error(`DeepSeek ${r.status}: ${(await r.text()).slice(0, 200)}`);
  }
  const data = await r.json();
  return data.choices?.[0]?.message?.content || '(空回复)';
}
