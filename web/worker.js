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

  return `你是一名财经分析助手。以下是今日资讯汇总,基于此回答问题。

## 今日早报

${brief}

## 板块信息

${sectors}

## 规则

1. 先结论后原因,每轮不超过 250 字
2. 不给买卖建议
3. 不确定的事说"根据现有信息无法判断"
4. 提股票时加"投资有风险,仅供参考"

## 政策判断

只有国务院/央行/部委/地方政府正式发文才算政策。新闻报道、分析师观点、公司公告不算政策。

## 禁止

禁止"建议买入/卖出"、禁止编造股票、禁止把新闻当政策、禁止使用哄人或迎合的语气`;
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
      if (url.pathname === '/' || url.pathname === '/chat.html' || url.pathname === '/index.html') {
        const html = await getChatHtml(env);
        return new Response(html, {
          headers: {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'public, max-age=300',
          },
        });
      }
      if (url.pathname === '/api/chat' && request.method === 'POST') {
        return await handleChat(request, env);
      }
      if (url.pathname === '/api/health' || url.pathname === '/health') {
        return json({
          ok: true,
          service: 'a-stock-chat',
          has_kv: !!env.KV,
          has_deepseek: !!env.DEEPSEEK_API_KEY,
          time: bjNow().toISOString(),
        });
      }
      return json({ error: 'Not Found' }, 404);
    } catch (e) {
      return json({ error: 'Internal: ' + e.message }, 500);
    }
  },
};
