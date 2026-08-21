# 统一 API 与充值服务

该目录部署在你控制的服务器，桌面安装包里不包含 DeepSeek/豆包主密钥。

环境变量：

- `GATEWAY_ADMIN_KEY`：管理充值码的高强度密码。
- `UPSTREAM_BASE_URL`：上游 OpenAI 兼容地址，例如 `https://api.deepseek.com`。
- `UPSTREAM_API_KEY`：你的上游密钥。
- `UPSTREAM_MODEL`：真实模型名。
- `GATEWAY_DB`：SQLite 文件路径，默认 `gateway.db`。

启动：`uvicorn gateway_server.app:app --host 0.0.0.0 --port 8080`

正式部署必须配置 HTTPS、反向代理、每日数据库备份和服务器防火墙。桌面客户端设置
`XIANYU_BILLING_BASE_URL=https://你的域名` 后，用户只需要输入充值码。

创建 10 个、每个含 500 次的充值码：

```bash
curl -X POST https://你的域名/admin/codes \
  -H "X-Admin-Key: 你的管理密码" -H "Content-Type: application/json" \
  -d '{"count":10,"credits":500}'
```
