# PHP 迁移变更知识速查（任意低版本 → 高版本排查用）

> 用途：解析异常后比对候选假设；**归因必须落在源/目标版本区间内的条目上**，跨多版本升级时按区间依次叠加（如 5.6→8.4 叠加 7.0–8.4 全部条目）。答复时注明命中的版本与条目，正式引用以 PHP 官方迁移指南（`php.net/manual/zh/migration*.php`）为准；未覆盖的版本/条目以官方指南为准。

## PHP 5.x（源版本常见遗留用法，升级前排查）

- `mysql_*` 系列扩展（5.5 起废弃，7.0 移除）
- `ereg*()` / `split()`（POSIX 正则，5.3 起废弃，7.0 移除）
- `register_globals` / `magic_quotes_*`（5.3/5.4 起移除，确认老代码是否残留依赖）
- 直接调用构造函数与类同名（PHP 4 风格构造函数，7.0 移除）
- `call_user_method()` / `set_magic_quotes_runtime()` 等 5.3 已废函数

## PHP 7.0

- `mysql_*` 系列移除（5.5 起已废，确认是否残留）
- `preg_replace` 的 `e` 修饰符移除
- `split()` / `ereg*()` 移除（早前已废）
- `global $$var` 变量间接引用变化
- 标量类型声明下的隐式转换收紧

## PHP 7.1

- 负数字符串偏移现在视为从末尾读取（行为变化）
- `rand()` / `srand()` 换成 MT19937
- `session_create_id()` 等变化

## PHP 7.2

- **`each()` 移除**（高频）
- `create_function()` 移除
- `__autoload()` 移除（须 `spl_autoload_register`）
- `track_errors` ini 移除
- `parse_str` 须传第二参

## PHP 7.3

- `image2wbmp()` 移除
- `fgetss()` / `string.strip_tags` 过滤移除
- `define_syslog_variables` 等移除
- heredoc 缩进规则收紧（语法层面，编译期报错）

## PHP 7.4

- `implode()` 历史参数顺序（`implode($pieces, $glue)`）弃用
- `money_format()` / `ezmlm_hash()` / `restore_include_path()` 移除
- `hebrevc` / `convert_cyr_string` 移除
- `__autoload` 之外的 unbinding callable；弱引用

## PHP 8.0（大版本）

- `throw` 表达式
- **字符串/数组的花括号访问 `{}` 移除**（高频，报错 `syntax error, unexpected "{"`）
- `each` 相关残留；`create_function` 彻底不可用；`money_format` 已移除
- 命名参数带来的**参数名变更**（大量内置函数参数改名，按位置传参不受影响、按名传参致命）
- 内部函数**严格类型**（传错类型从 Warning 变 TypeError）
- **比较运算收紧**（数字与数字字符串比较、0 与空字符串比较规则变化，典型：`'abc' == 0` 由 true 变 false）
- `str_contains` 等新函数
- `__sleep`/`__wakeup` 交互变化；`Reflection` 签名变化
- `resource` → `object` 迁移开始（如 `curl`、`gd`、`openssl`、`shmop`）

## PHP 8.1

- **向非空内部函数参数传 `null` 弃用**（高频，`trim(null)`、`strlen(null)`）
- `mysqli::init()` / `mysqli_embedded_server` 等移除
- `strftime` / `gmstrftime` 弃用（8.4 移除）
- 枚举、readonly 属性、`never` 返回类型
- `$_FILES` 变化

## PHP 8.2

- **动态属性弃用**（未声明的属性赋值，高频；`#[AllowDynamicProperties]` 豁免）
- **`${}` 字符串插值弃用**（`"{$a}"` 保留、`"${a}"` 弃用）
- `utf8_encode` / `utf8_decode` 弃用
- `mb_check_encoding` 等部分调用方式弃用
- `DateInterval` / `DatePeriod` 序列化格式变化
- `mysqli::execute_query` 等新增
- **部分可调用语法弃用**（`"self::method"` 字符串形式等）

## PHP 8.3

- `assert_options` / `assert.active` 弃用
- `ldap_connect` 分开的 `$hostname,$port` 形式弃用
- `mysqli_refresh` / `mysqli::refresh` 弃用
- `get_class` / `get_parent_class` 无参调用弃用
- 只读属性重新初始化（`readonly` 类）等

## PHP 8.4（目标版本）

- **隐式可空参数类型弃用**（`function f(string $s = null)` 须显式 `?string`，高频）
- `GMP` 由 resource 变 object
- `session_set_save_handler` 部分签名变化
- `mysqli_ping` 弃用
- `DOMDocument` 等扩展行为变化
- `curl_close` 对 share handle 的弃用
- `E_STRICT` 常量弃用并入 `E_ALL`（错误级别配置需核对）
- `xml_set_object` 等移除项收尾

## PHP 8.5（升级目标为最新版时）

- 管道运算符 `|>` 新增（正向变化，可用于改写嵌套调用）
- URI 扩展（`ext/uri`，WHATWG URL 解析）新增
- `#[\NoDiscard]` 属性与 `(void)` 强制丢弃语义
- 部分历史弃用项在 8.5 进一步收紧或移除——排查时以官方迁移指南为准逐项核对

> 以上 8.5 条目为方向性提示，正式答复引用前应联网核对官方迁移指南（`php.net/manual/zh/migration85.php`）。

## 通用（跨版本）

- 错误级别变化：大量 former `Notice/Warning` 升级为 `Warning/Error`
- `display_errors` / `error_reporting` 配置在新版本下的输出差异
- 框架/扩展（旧版 ThinkPHP 3.x、Discuz、老版 PHPUnit 等）自身不兼容 8.x——若根因是三方库不支持 PHP 8.4，结论中必须指明库名与所需最低版本
