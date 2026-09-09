# CloudBase 官方依据与平台查证流程

最后核验日期：2026-08-19。

## 权威边界

本文件维护平台事实，不定义下游交付格式。交付字段、文件集合、CustomSteps 顺序和 root/overlay 语义始终以 [protocol.md](protocol.md)、本地 schema 与生成器为最高优先级。

CloudBase 官方资料用于确认该协议依赖的平台能力是否仍成立。若官方事实与下游协议冲突：

1. 不修改或绕过下游协议；
2. 不继续生成可能无法运行的交付物；
3. 报告冲突的协议条款、官方依据、影响范围和建议的协议维护动作；
4. 只有维护者更新协议后才能继续。

阻断报告同时给出解除路径：指出维护者需修改的协议条款、需要重新核验的官方事实、受影响的生成器/schema，以及更新后应重新执行的探测和完整校验。协议冲突不能自动自愈，但不能省略可执行的维护引导。

模型记忆、搜索摘要、博客、问答和第三方项目不是权威依据。

## 官方资料

| 主题 | 官方链接 | 本 Skill 依赖的事实 |
| --- | --- | --- |
| HTTP 函数启动文件 | https://docs.cloudbase.net/cloud-function/develop/scf-bootstrap | HTTP 函数需要 `scf_bootstrap`；Web Server 使用 9000 端口；官方 Node 示例展示绝对运行时路径，但平台不替项目选择 npm script 或已解析 Node 入口；启动文件需要可执行权限。 |
| 运行环境支持 | https://docs.cloudbase.net/cloud-function/runtime-support | 当前列出 Node.js 26.x、24.11、22.21、20.19、18.15、16.13；函数运行时由根 `cloudbaserc.json#functions[].runtime` 选择，描述符 `NodeVersion` 保留项目探测主版本，bootstrap 不拼接版本化 Node 路径。 |
| 部署云函数 | https://docs.cloudbase.net/cli-v1/functions/deploy | `tcb fn deploy` 支持 `--dir`、`--httpFn`、`--force`、环境选择和非交互部署。 |
| CLI 安装与登录 | https://docs.cloudbase.net/cli-v1/install | CI 可使用 `--apiKeyId`、`--apiKey`；临时密钥登录增加 `--token`。 |
| 云函数配置 | https://docs.cloudbase.net/cli-v1/functions/configs | HTTP 类型、Node 运行时版本、函数目录和云端安装依赖等平台配置语义。 |
| CLI 实时帮助 | https://docs.cloudbase.net/cli-v1/global-options | 平台建议 Agent 在生成命令前查看对应 `--help`；实时帮助优先于模型记忆。 |

## 当前下游选择

函数配置使用的固定 runtime 字面值为 `Nodejs16.13`、`Nodejs18.15`、`Nodejs20.19`、`Nodejs22.21`、`Nodejs24.11`。

这些值是下游协议在官方可用能力中的选择，不因官方新增运行时而自动漂移：

- 后端描述符 `NodeVersion` 使用项目静态探测到的 Node 主版本，不能被生成器覆盖；bootstrap 不再承载 Node 版本选择。根 `cloudbaserc.json` 的函数 runtime 是独立的下游固定选择：只使用 16.13、18.15、20.19、22.21、24.11 五档并向上映射，20 及以下开启 installDependency，20 以上关闭。官方当前还列出 26.x，但协议未纳入；项目主版本高于 24 时必须阻断，用户明确授权后才可 reviewed override 到 24，且不得改变描述符 `NodeVersion`。
- bootstrap 严格投影 resolver 已写入计划的 `RuntimeLaunch`。框架契约确认独立 server 产物时使用 PATH 中的 `node <RuntimeEntry>`；普通 Node/Nest/自定义 SSR root 可保留已解析的 npm start script；overlay 使用生成的 npm start script。生成器不得重新读取 manifest 改选启动方式，也不得生成 `/var/lang/node<major>/bin/node`。函数 runtime 必须来自固定 cloudbaserc 表；探测主版本可以保留在描述符中而不要求精确命中函数 runtime 字面值。
- 项目没有唯一 Node 主版本声明时，兼容回退为 `20` 并产生 `W_NODE_VERSION_FALLBACK`；这不是对已探测项目的版本限制。
- HTTP 服务端口固定为 9000。
- `PORT`、`NITRO_PORT` 为 9000；`HOST`、`HOSTNAME`、`NITRO_HOST` 为 `0.0.0.0`。
- bootstrap 位于项目根，使用 LF、末尾换行和 `0755`；执行计划中的 `RuntimeLaunch`，不把 Node 入口降级成“无 start script 时的兜底”。
- 部署从项目根执行，使用下游协议固定的 `${functionName}` 字面占位符、`--dir .`、`--httpFn`、`--force`、`--yes` 和环境变量认证；真实函数名由下游在执行前替换。

官方文档出现更高版本或不同推荐值，只说明平台新增能力，不授权 Agent 改写项目已经明确声明的版本；必须先确认项目与目标运行时兼容。

## 强制查证流程

遇到以下任一情况，必须查证，不得只依赖本文件缓存：

- 用户报告远端安装、构建、启动、登录或部署失败；
- CLI 返回 unknown option、deprecated、authentication、runtime 或 function configuration 错误；
- 官方行为与当前生成命令看起来不一致；
- Agent 准备建议改变 Node 版本、bootstrap、端口、部署参数、认证参数或函数目录；
- 本文件最后核验日期之后存在合理的平台变更可能。

按以下顺序执行：

1. 定位失败的 CustomStep 和完整错误，不依据最后一行日志猜原因。
2. 读取上表中与该事实直接相关的官方页面；技术查证只使用 CloudBase 官方来源。
3. 如果环境中已存在下游固定版本的 `tcb`，运行对应的只读帮助命令，例如 `tcb fn deploy --help` 或 `tcb login --help`。不得为了查证在 Agent 本地安装 CLI，也不得登录或修改云资源。
4. 记录：查询日期、官方 URL 或帮助命令、被验证的具体事实、与下游协议是否一致。
5. 分类为：项目问题、凭证/环境问题、暂时性平台问题或协议—平台冲突。
6. 只有项目问题进入 [remediation.md](remediation.md)；凭证问题只给安全配置指导；暂时性平台问题保留原协议并建议重试/升级处理；协议冲突直接阻断并升级给维护者。

网络或官方页面不可访问时，如果结论会影响平台相关修改或交付正确性，必须报告查证未完成并阻断。报告须列出未能访问的官方 URL/帮助命令、原始错误、安全重试方法和查证成功后的复检步骤。不得用第三方资料填补权威证据。

## 静态分支

纯静态项目不适用函数 runtime、bootstrap 或函数部署查证，不得因为读取了本文件而生成任何后端输入。
