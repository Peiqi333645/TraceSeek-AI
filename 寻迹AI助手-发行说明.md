# 寻迹AI助手 定制版

## 已完成

- 固定黄色新手界面，移除顶部五套主题选择。
- 红色“立即运行”主按钮，绿色运行进度条与正常状态提示。
- 品牌显示改为“寻迹AI助手”，Windows/Mac 构建产物改名为 `TraceSeek-AI`。
- 设置页增加“剩余分析次数、充值码、立即充值”。
- 客户端只保存用户令牌，不包含运营方的 DeepSeek/豆包主密钥。
- 新增 `gateway_server`：充值码生成、设备激活、余额查询、扣费日志和 OpenAI 兼容转发。
- 保留 MIT License 和原作者版权信息。

## 生成双击安装包

项目已经配置 GitHub Actions。把本目录提交到你自己的 GitHub 私有仓库，在 Actions 页面选择
`release`，点击 `Run workflow`，填写版本 `1.0.0`。构建结束后下载：

- `TraceSeek-AI-Setup.exe`：Windows 10/11 x64 安装程序。
- `TraceSeek-AI.dmg`：Apple 芯片 Mac 安装盘。

Windows和Mac二进制必须分别在对应系统构建，PyInstaller不能在Linux跨平台生成这两个成品。

## 正式启用充值功能

1. 把 `gateway_server` 部署到带 HTTPS 域名的服务器。
2. 设置 `GATEWAY_ADMIN_KEY`、`UPSTREAM_BASE_URL`、`UPSTREAM_API_KEY`、`UPSTREAM_MODEL`。
3. 构建桌面安装包时设置 `XIANYU_BILLING_BASE_URL=https://你的网关域名`。
4. 通过网关管理接口批量生成充值码，在闲鱼成交后发给客户。

没有配置网关地址时，桌面软件仍可运行和扫码登录，但充值卡会显示演示状态，AI统一计费不可用。

## 推荐售价

- 体验版：39元/7天。
- 标准版：199元/台，API次数另购。
- 专业版：399元/两台设备，含一年更新。
- 500次：9.9元；2000次：29.9元；10000次：99元。

正式销售前应测试闲鱼账号风控，并在商品说明中明确自动化访问和账号限制风险。
