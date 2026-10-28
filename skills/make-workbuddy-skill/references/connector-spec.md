# 连接器（Connector）完整规范

来源：WorkBuddy 官方文档（workbuddy.cn/docs → 连接器）。

## 1. 两种形态

| 形态 | 说明 |
|---|---|
| MCP + CLI | 标准化 MCP 协议对接外部服务（主流方式） |
| Skill + CLI | 内置脚本形态 |

二者在数据收集和权限边界上遵循一致原则。官方已上架：QQ 邮箱、腾讯文档、腾讯乐享、腾讯会议、TAPD、腾讯网盘等，同时支持自定义连接器。

## 2. mcp.json 基础结构

```json
{
  "mcpServers": {
    "my-service": {
      "type": "streamableHttp",
      "url": "https://example.com/mcp",
      "timeout": 30000,
      "headers": {
        "Authorization": "Bearer ${API_TOKEN}"
      }
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| url | 远程 MCP（SSE / Streamable HTTP）服务地址 |
| type | 传输类型，如 `http` / `streamableHttp`；远程 SSE 可省略 |
| timeout | 超时毫秒数，建议显式设置 |
| headers | 请求头；Token 鉴权用 `${VAR}` 占位，禁止写死真实密钥 |

## 3. x-workbuddy 元信息（展示与鉴权）

```json
{
  "mcpServers": {
    "my-service": {
      "url": "https://example.com/mcp",
      "x-workbuddy": {
        "displayName": { "zh": "我的服务", "en": "My Service" },
        "description": { "zh": "连接后可查询流程列表、待办流程单并创建流程单。", "en": "..." },
        "icon": "./avatars/my.svg",
        "auth": { "type": "oauth" }
      }
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| displayName | 引导卡片标题；不填回退 server 名 |
| description | 卡片描述，**必须写清"连接后能做什么"**——用户授权决策全靠这句 |
| icon | https:// 、data: URL 或相对插件根目录的本地路径（推荐放 `avatars/`）；不设置则用首字符 + 散列底色占位 |
| auth.type | `oauth` / `token` / `none` |

LocalizedString 约定：文案字段可写纯字符串或 `{zh, en}` 双语对象；双语缺失时回退 zh → en。

## 4. 鉴权方式

### oauth（推荐）

用户点击「连接」跳转扫码/浏览器授权，之后自动携带 Bearer 令牌并自动续期。体验最好，无需用户找 API Key。

### token（API Key）

`auth.type: "token"` + `tokenSchema` 声明表单。用户填写的值回填到 headers 的 `${VAR}` 占位：

```json
"x-workbuddy": {
  "auth": {
    "type": "token",
    "tokenSchema": {
      "title": { "zh": "配置访问 Token", "en": "Configure Token" },
      "description": { "zh": "请输入 API Token。", "en": "..." },
      "docUrl": "https://example.com/guide",
      "docLabel": { "zh": "如何获取 Token?", "en": "How to get a token?" },
      "fields": [
        {
          "key": "API_TOKEN",
          "label": { "zh": "API Token", "en": "API Token" },
          "placeholder": { "zh": "请输入 API Token", "en": "Enter API token" },
          "type": "password",
          "required": true,
          "description": { "zh": "将写入 Authorization Header", "en": "..." }
        }
      ]
    }
  }
}
```

字段说明：`key` 对应 headers 中的 `${key}` 占位；`type` 用 `password` 保护敏感凭据；`docUrl`/`docLabel` 提供获取帮助链接。

### none

无需鉴权的公开服务。

## 5. 客户端使用方式

1. **连接器页面发起**：连接器管理页 → 已授权卡片「去对话」
2. **创建任务时启用**：输入框左下角 `+` → 连接器，弹窗开启（未授权的先授权）
3. **执行中按需连接**（推荐）：任务执行到一半需要未连接的连接器时，输入框上方自动出现引导卡片，授权后自动继续执行，不中断任务

## 6. 失效与重连

授权过期时客户端自动弹出「重新连接」卡片，成功后自动重试失败步骤（同一步骤只重试一次）。网络超时、服务异常、无权限**不会**触发该卡片。也可在对话中说「重新连接 XX」主动触发。

## 7. 自然语言管理

- 「帮我安装 XX 连接器」→ 引导安装
- 「我安装了哪些连接器」→ 列出已安装及状态（含"已授权但关闭"的）
- 「卸载 XX 连接器」→ 弹确认窗后卸载（内置连接器不可卸载）

## 8. 在专家中声明连接器依赖

专家依赖已上架连接器时，在 plugin.json 的 `dependencies.connectors` 列出 ID；依赖自带 MCP 时在 `dependencies.mcpServers` 指向 `.mcp.json`。详见 expert-spec.md 第 4 节。
