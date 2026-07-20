/**
 * A股财经对话助手 - Cloudflare Workers 后端
 *
 * 部署:
 *   1. 注册 Cloudflare 账号 → Workers → Create
 *   2. 复制本文件内容到编辑器
 *   3. Settings → Variables → 添加:
 *        DEEPSEEK_API_KEY
 *        GITHUB_REPO  (例如 Yaaaaaaa233/a-stock-brief)
 *        GITHUB_TOKEN (PAT,读私有 repo;公开 repo 可不填)
 *   4. 部署,记录 URL(https://xxx.workers.dev)
 *   5. 在 chat.html 里把 API_BASE 改成这个 URL
 */

const SKILLS_META = {
  brief: {
    name: '早报解读',
    icon: '💬',
    description: '基于今日早报回答,父母友好',
    default: true,
    greeting: '👋 你好!我已经读取了今天的早报,有什么想了解的吗?比如某条新闻的意思、对哪些板块有影响。',
    quickReplies: [
      '今天的早报讲了什么?',
      '今天最值得关注的是什么?',
      '有啥风险要注意?',
    ],
  },
  sector: {
    name: '板块查询',
    icon: '🏭',
    description: '查询板块龙头股',
    greeting: '👋 想了解哪个板块?我可以告诉你对应的龙头股和关键词(只从我配置的 20 个板块里答)。',
    quickReplies: [
      '新能源板块有哪些龙头股?',
      '半导体板块关注什么?',
      '低空经济是什么?',
    ],
  },
  policy: {
    name: '政策解读',
    icon: '📜',
    description: '通俗解释财经政策',
    greeting: '👋 把政策原文或者关键词发给我,我用大白话解释 + 打比方 + 影响分析。',
    quickReplies: [
      '降准是什么意思?',
      'LPR 调整影响房贷吗?',
      '集采对医药股是利好还是利空?',
    ],
  },
  concept: {
    name: '概念科普',
    icon: '📚',
    description: '解释财经名词',
    greeting: '👋 遇到不懂的财经名词?发给我,我用最简单的话+生活化比喻解释。',
    quickReplies: [
      '什么是 PE?',
      '北向资金是什么?',
      '融资融券是啥意思?',
    ],
  },
  history: {
    name: '历史回顾',
    icon: '🗓',
    description: '查看过去几天早报',
    greeting: '👋 我可以帮你回顾过去 7 天的早报内容,看看一周的关键资讯。',
    quickReplies: [
      '本周讲了哪些大事?',
      '上周和这周比较?',
      '最近有啥政策?',
    ],
  },
};

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
  const now = new Date();
  return new Date(now.getTime() + 8 * 3600 * 1000);
}

function monthStr() {
  const d = bjNow();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

function dayStr() {
  const d = bjNow();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
}

function pathToKvKey(path) {
  if (path.startsWith('web/skills/')) {
    return `skills:${path.split('/').pop().replace('.md', '')}`;
  }
  if (path.startsWith('logs/')) {
    return `logs:${path.split('/').pop().replace('.md', '')}`;
  }
  if (path === 'config.yaml') return 'config:yaml';
  return null;
}

async function fetchGitHub(path, env) {
  // 1. 优先从 KV 读(主动同步的内容 + 被动缓存的内容都在这里)
  if (env.KV) {
    const kvKey = pathToKvKey(path);
    if (kvKey) {
      try {
        const cached = await env.KV.get(kvKey);
        if (cached) return cached;
      } catch (e) {
        console.log('KV read failed:', e.message);
      }
    }
  }

  // 2. KV 未命中 → 兜底:jsDelivr(公开仓库)或 GitHub raw(私有仓库)
  const useJsdelivr = env.PUBLIC_REPO === 'true' && !env.GITHUB_TOKEN;
  const base = useJsdelivr
    ? `https://cdn.jsdelivr.net/gh/${env.GITHUB_REPO}@main/`
    : `https://raw.githubusercontent.com/${env.GITHUB_REPO}/main/`;
  const url = base + path;

  const headers = {};
  if (env.GITHUB_TOKEN) headers['Authorization'] = `token ${env.GITHUB_TOKEN}`;
  const r = await fetch(url, { headers });
  if (!r.ok) {
    throw new Error(`GitHub ${path} ${r.status}: ${await r.text()}`);
  }
  const content = await r.text();

  // 3. 回写 KV(被动缓存:skill 1 小时,其他 15 分钟)
  if (env.KV) {
    const kvKey = pathToKvKey(path);
    if (kvKey) {
      const ttl = path.startsWith('web/skills/') ? 3600 : 900;
      try {
        await env.KV.put(kvKey, content, { expirationTtl: ttl });
      } catch (e) {
        console.log('KV write failed:', e.message);
      }
    }
  }
  return content;
}

function extractSystemPrompt(md) {
  const end = md.indexOf('-->', md.indexOf('<!--'));
  if (md.startsWith('---')) {
    const fmEnd = md.indexOf('\n---', 3);
    if (fmEnd > 0) return md.slice(fmEnd + 4).trim();
  }
  return md.trim();
}

function extractLatestDayBrief(logs) {
  const dayKey = `## ${dayStr()}`;
  const idx = logs.lastIndexOf(dayKey);
  if (idx < 0) {
    return logs.slice(-3000);
  }
  const nextSection = logs.indexOf('\n## ', idx + 5);
  return nextSection > 0 ? logs.slice(idx, nextSection).trim() : logs.slice(idx).trim();
}

function extractRecentLogs(logs) {
  const sections = logs.split(/\n## (?=\d{4}-\d{2}-\d{2})/);
  return sections.slice(-7).join('\n## ').trim();
}

async function loadTodayBrief(env) {
  // 优先 KV logs:latest(GitHub Actions 主动同步,~50ms)
  if (env.KV) {
    try {
      const latest = await env.KV.get('logs:latest');
      if (latest) return latest;
    } catch (e) {
      console.log('KV latest read failed:', e.message);
    }
  }
  // 兜底:从 GitHub 拉 logs/YYYY-MM.md,提取当天段落
  const logs = await fetchGitHub(`logs/${monthStr()}.md`, env);
  return extractLatestDayBrief(logs);
}

async function loadRecentLogs(env) {
  // 优先 KV logs:YYYY-MM
  if (env.KV) {
    try {
      const monthly = await env.KV.get(`logs:${monthStr()}`);
      if (monthly) return extractRecentLogs(monthly);
    } catch (e) {
      console.log('KV monthly read failed:', e.message);
    }
  }
  const logs = await fetchGitHub(`logs/${monthStr()}.md`, env);
  return extractRecentLogs(logs);
}

async function buildSystemPrompt(skillId, env) {
  const md = await fetchGitHub(`web/skills/${skillId}.md`, env);
  let prompt = extractSystemPrompt(md);

  if (prompt.includes('{{today_brief}}')) {
    try {
      prompt = prompt.replace('{{today_brief}}', await loadTodayBrief(env));
    } catch (e) {
      prompt = prompt.replace('{{today_brief}}', '(今日早报暂未生成)');
    }
  }
  if (prompt.includes('{{recent_logs}}')) {
    try {
      prompt = prompt.replace('{{recent_logs}}', await loadRecentLogs(env));
    } catch (e) {
      prompt = prompt.replace('{{recent_logs}}', '(历史日志暂未生成)');
    }
  }
  if (prompt.includes('{{sectors_config}}')) {
    try {
      prompt = prompt.replace('{{sectors_config}}', await fetchGitHub('config.yaml', env));
    } catch (e) {
      prompt = prompt.replace('{{sectors_config}}', '(板块配置加载失败)');
    }
  }
  return prompt;
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
    const errText = await r.text();
    throw new Error(`DeepSeek ${r.status}: ${errText}`);
  }
  const data = await r.json();
  return data.choices?.[0]?.message?.content || '(空回复)';
}

async function handleSkills() {
  const skills = Object.entries(SKILLS_META).map(([id, s]) => ({
    id,
    name: s.name,
    icon: s.icon,
    description: s.description,
    default: !!s.default,
    greeting: s.greeting,
    quickReplies: s.quickReplies,
  }));
  return json({ skills });
}

async function handleChat(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: '请求格式错误' }, 400);
  }
  const { skill, message, history } = body;
  if (!skill || !message) {
    return json({ error: '缺少 skill 或 message 参数' }, 400);
  }
  if (!SKILLS_META[skill]) {
    return json({ error: `未知 skill: ${skill}` }, 400);
  }
  if (!env.DEEPSEEK_API_KEY) {
    return json({ error: '服务器未配置 DEEPSEEK_API_KEY' }, 500);
  }
  if (!env.GITHUB_REPO) {
    return json({ error: '服务器未配置 GITHUB_REPO' }, 500);
  }
  try {
    const systemPrompt = await buildSystemPrompt(skill, env);
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
      if (url.pathname === '/api/skills') return await handleSkills();
      if (url.pathname === '/api/chat' && request.method === 'POST') {
        return await handleChat(request, env);
      }
      if (url.pathname === '/' || url.pathname === '/health') {
        return json({ ok: true, service: 'a-stock-chat', time: bjNow().toISOString() });
      }
      return json({ error: 'Not Found' }, 404);
    } catch (e) {
      return json({ error: 'Internal: ' + e.message }, 500);
    }
  },
};
