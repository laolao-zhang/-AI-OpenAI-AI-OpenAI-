# 移动云盘 AI 网关 · 通用核心（实验版）

面向移动云盘 AI 网关项目的通用 OpenAI 风格转发核心。包括请求鉴权、账号轮询、本地每日用量、简易配额、SSE 转发、状态面板与模拟上游。

**本版本不包含移动云盘登录或专用适配器，不能直接登录移动云盘或获取其 ApiKey。** 需要使用者自行提供有权使用的 OpenAI 兼容上游地址和凭据。

## 本地演示

需要 Python 3.10+，无需安装第三方依赖。先在一个终端启动模拟上游：

```sh
python mock_upstream.py
```

再打开一个终端（Linux/macOS）：

```sh
export GATEWAY_TOKEN='replace-with-a-long-random-token'
export UPSTREAM_URL='http://127.0.0.1:8900/v1/chat/completions'
export UPSTREAM_ACCOUNTS='[{"name":"demo","key":"mock-key"}]'
export GATEWAY_MODEL='mock-model'
export DAILY_TOKEN_LIMIT=10000
python gateway.py
```

访问 `http://127.0.0.1:8899/admin` 查看用量，客户端 Base URL 为 `http://127.0.0.1:8899/v1`，使用 `GATEWAY_TOKEN` 作为 Bearer 令牌。`.env.example` 是配置示例，不会自动加载。

`UPSTREAM_ACCOUNTS` 是 JSON 数组，用户自行配置已有上游凭据；每次请求轮询一个账号，上游错误不会触发换号重试。`DAILY_TOKEN_LIMIT` 是每个账号的本地每日额度，0 表示不限。它只依据上游返回的 `usage.total_tokens` 记账：若上游没有返回用量或请求并发，额度可能不准确或被超出，不能作为硬性消费限制。用量文件默认位于 `data/usage.json`，包含账号名称，注意保护和备份。

服务默认仅监听本机，没有 TLS 或速率限制，不应直接暴露公网。管理面板目前只展示统计，账号与配额通过环境变量配置。模型列表由 `GATEWAY_MODEL` 配置，不自动查询上游。

## 测试

```sh
python -m unittest -v test_gateway
```

测试只连接本机模拟上游，不证明第三方服务或真实账户可用。请勿提交真实密钥、Cookie、账号数据或日志。

