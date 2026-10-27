---
name: php-migration-analysis
description: "PHP low-to-high version upgrade troubleshooting knowledge base: version-range scoping strategy, log/code retrieval tactics, and a version-by-version lookup table of high-frequency breaking changes (5.x-8.5) used to attribute PHP errors during upgrade analysis."
---

# PHP 版本升级排障分析

本 skill 为「PHP版本升级问题分析员」提供版本区间定位策略、检索策略与迁移变更知识库。

## 使用方式

1. **确定版本区间**：先确认源版本与目标版本；升级跨多个版本时，把区间内每个 major/minor 的变更条目**依次叠加**作为比对基础（如 5.6→8.4 叠加 7.0–8.4 全部条目；7.4→8.4 只叠加 8.0–8.4）。
2. 解析异常后，查 `references/migration-changes.md`，把错误消息与区间内的变更条目比对，形成候选假设。
3. 按「日志与代码检索策略」逐级取证。
4. 答复中引用具体变更时，以 PHP 官方迁移指南（`php.net/manual/zh/migration*.php`）对应条目为准，必要时联网核验并附链接；速查表未覆盖的版本/条目以官方指南为准。

## 版本区间定位策略

- **源版本**：可从报错信息中的弃用提示、项目 `composer.json`、运行日志的 PHP 版本头（`X-Powered-By`）或用户陈述推断；推断不出时必须询问。
- **目标版本**：同上；注意区分「升级目标版本」与「当前实际运行版本」。
- **叠加原则**：候选假设必须落在区间内的变更条目上；跨多版本升级时，优先怀疑「中间版本已移除但旧环境一直带病运行的用法」，再怀疑目标版本新变化。
- **区间外排除**：区间外或未发生版本的变更不得用于解释问题。

## 日志与代码检索策略

### 检索顺序（先日志，后代码，逐级扩大范围）

1. **按请求标识**：有 `request_id` / `trace_id` / `X-Request-Id` 时先精确检索该标识，拿到完整请求链路日志（入口 → 业务日志 → PHP 报错）。
2. **按错误特征**：用错误消息中的稳定片段（函数名、类名、错误码）检索 PHP 错误日志（`php_errors.log` / php-fpm error log / stderr）与应用日志（Monolog / ThinkPHP / Laravel 等）。
3. **按时间窗**：有出错时间时，检索前后 ±5 分钟窗口；多条异常按时间排序还原先后关系。
4. **按接口路径**：检索 access log（nginx / apache），确认请求是否到达、响应码、耗时，判断异常发生在 PHP 层还是前置层。

### 检索技巧

- 优先用 ripgrep / grep 的固定字符串（`-F`）与上下文（`-C 20`）。
- 大文件先按时间戳定位区间，再细看。
- 只摘与结论相关的最小片段，不把整个日志文件倒进回复。
- 每命中一条证据，记录来源：日志文件绝对路径 + 行号 + 时间戳。

### 证据与置信度

- **只读**：仅允许只读命令/工具（grep / rg / find / cat / tail / Read 等）；禁止任何写操作。
- **多源交叉**：单一来源证据（只有一条日志或只有代码）结论置信度标低；「请求日志 + PHP 报错 + 代码位置 + 官方变更条目」四件套齐全时置信度标高。
- **敏感信息**：日志若含手机号、身份证、密钥等，输出时打码；不回显完整密钥/Token。

### 三方库判定

若根因是三方库（旧版 ThinkPHP 3.x、Discuz、老版 PHPUnit 等）自身不支持目标 PHP 版本，结论中必须指明库名与所需最低版本。
