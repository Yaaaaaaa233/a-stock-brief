// Pages Function:GET /api/health
// 健康检查

export async function onRequestGet({ env }) {
  return Response.json({
    ok: true,
    service: 'a-stock-pages',
    has_kv: !!env.KV,
    has_deepseek: !!env.DEEPSEEK_API_KEY,
    time: new Date(Date.now() + 8 * 3600 * 1000).toISOString(),
  }, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
    },
  });
}
