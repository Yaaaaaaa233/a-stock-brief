/**
 * A股财经对话助手 - Cloudflare Worker(极简单一对话版)
 *
 * 架构:
 *   GET  /          → serve chat.html(从 KV,~50ms)
 *   POST /api/chat  → 单一 LLM 对话(综合 prompt,自动判断问题类型)
 *   GET  /api/health → 健康检查
 *
 * 不再依赖 GitHub Pages,父母只用一个 Worker URL。
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function cors(body, init = {}) {
  return new Response(body, {
    ...init,
    headers: { ...CORS_HEADERS, ...(init.headers || {}) },
  });
}

function json(obj, status = 200) {
  return cors(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

function bjNow() {
  return new Date(Date.now() + 8 * 3600 * 1000);
}

function monthStr() {
  const d = bjNow();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

let cachedHtml = null;

async function getChatHtml(env) {
  if (cachedHtml) return cachedHtml;

  if (env.KV) {
    try {
      const html = await env.KV.get('chat:html');
      if (html) {
        cachedHtml = html;
        return html;
      }
    } catch (e) {
      console.log('KV chat:html read failed:', e.message);
    }
  }

  // KV 没有 → 兜底 GitHub(慢,但保证可用)
  const base = env.PUBLIC_REPO === 'true'
    ? `https://cdn.jsdelivr.net/gh/${env.GITHUB_REPO}@main/`
    : `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/`;
  const headers = {};
  if (env.GITHUB_TOKEN) headers['Authorization'] = `token ${env.GITHUB_TOKEN}`;
  const r = await fetch(base + 'web/chat.html', { headers });
  if (!r.ok) {
    return '<html><body><h1>网页加载失败</h1><p>请稍后重试,或联系管理员同步 chat.html 到 KV。</p></body></html>';
  }
  const html = await r.text();

  // 回写 KV(1 小时 TTL)
  if (env.KV) {
    try { await env.KV.put('chat:html', html, { expirationTtl: 3600 }); } catch (e) {}
  }
  return html;
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

用户问"政策"时,**严格按以下准则判断**:

✅ **是政策**:
- 国务院 / 央行 / 各部委 / 地方政府正式发文
- 有明确发文单位(如"央行决定""财政部公告""证监会通知")
- 有具体执行措施(降准 0.5% / 补贴延长至 X 年 / 减税 X%)
- 通常能找到官方文件号(如"国发〔2024〕X 号")

❌ **不是政策**(应明确告诉用户):
- 新闻媒体报道"国家可能..."、"据传..."、"传闻..."
- 分析师/机构的预测或建议(如"高盛预计央行将降息")
- 公司公告(这是企业行为,不是政策)
- 普通时事新闻(如"某领导人会见..."没有具体措施)

**当用户问"今天有什么政策"时**:
- 只从今日早报里找符合"政策"严格定义的内容
- 如果早报里没有真正的政策(只有新闻),诚实说"今天早报里没有重大政策,主要新闻有..."
- 不要把新闻当政策解读

## 你能做什么

1. **解读早报**:解释今日早报里的事件、对哪些板块有影响
2. **政策解读**:严格按上述定义,只解读真正的政策文件
3. **概念科普**:解释财经名词(PE/PB/北向资金/LPR 等),用比喻
4. **板块查询**:告诉用户某板块的龙头股(从配置读,严禁编造)
5. **历史回顾**:基于今日早报内容总结(不要编造历史)

## 禁止行为

- ❌ "建议买入/卖出 XX 股票"
- ❌ "会涨/跌 X%"
- ❌ 编造不在配置里的股票
- ❌ 把新闻/传闻说成政策
- ❌ 用更多专业词解释专业词

遇到这些请求时,礼貌拒绝并解释风险。`;
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

async function handleChat(request, env) {
  let body;
  try { body = await request.json(); } catch { return json({ error: '请求格式错误' }, 400); }
  const { message, history } = body;
  if (!message) return json({ error: '缺少 message' }, 400);
  if (!env.DEEPSEEK_API_KEY) return json({ error: '服务器未配置 DEEPSEEK_API_KEY' }, 500);

  try {
    const systemPrompt = await buildSystemPrompt(env);
    const reply = await callDeepSeek(systemPrompt, history, message, env);
    return json({ reply });
  } catch (e) {
    return json({ error: e.message }, 502);
  }
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }
    const url = new URL(request.url);
    try {
      // API 路由
      if (url.pathname === '/api/chat' && request.method === 'POST') {
        return await handleChat(request, env);
      }
      if (url.pathname === '/api/health' || url.pathname === '/health') {
        return json({
          ok: true,
          service: 'a-stock-pages',
          has_kv: !!env.KV,
          has_deepseek: !!env.DEEPSEEK_API_KEY,
          time: bjNow().toISOString(),
        });
      }
      // 静态资源交给 Pages 自动处理
      if (env.ASSETS) {
        return env.ASSETS.fetch(request);
      }
      // 没有 ASSETS binding(纯 Worker 模式)→ 从 KV 拉 chat.html
      if (url.pathname === '/' || url.pathname === '/chat.html' || url.pathname === '/index.html') {
        const html = await getChatHtml(env);
        return new Response(html, {
          headers: {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'public, max-age=300',
          },
        });
      }
      return json({ error: 'Not Found' }, 404);
    } catch (e) {
      return json({ error: 'Internal: ' + e.message }, 500);
    }
  },
};
