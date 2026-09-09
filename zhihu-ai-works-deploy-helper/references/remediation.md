# 分类型自愈与复检

自愈只处理已经证明属于项目事实的问题。平台事实先按 [platform-contract.md](platform-contract.md) 查证；下游交付形状始终以 [protocol.md](protocol.md) 为最高优先级。

## 通用闭环

对每个阻断项输出：finding code、完整证据路径、受影响能力、平台或协议约束、最小修改、行为取舍、是否需要授权和复检条件。端口交付标准是预先允许的机械适配，不需要为该项暂停请求授权；仍须在最终交付说明中披露。

该要求适用于探测、平台查证、生成、校验、归档和远端 CustomStep，不限于 deploy plan finding。Skill 更新检查与安装是 advisory：其失败只保留简要证据并继续项目探测，不属于阻断项，也不进入本页闭环。

对其余适用阶段：

- 依据必须是可定位的文件/配置/日志/命令输出或官方 URL，并说明它证明了什么；不能只有结论。
- 自愈引导必须给出下一步动作、目标位置或命令、责任方和复检成功条件；不能只写“修复配置”或“联系管理员”。
- 无法自动修复时，明确缺失的选择、凭证、外部状态或协议变更，并说明用户或维护者补齐后如何继续。
- 多个阻断必须逐项输出，不得只解释第一个，也不得用一个笼统建议覆盖不同根因。

1. 从 detector evidence、相关源码、manifest、lockfile、框架配置和完整远端日志确定根因。
2. 区分机械配置修改、业务行为修改和架构调整。
3. 提出最小修改；不得通过改描述符、跳过校验或修改编译产物掩盖源码问题。
4. 删除或改变 SSR、数据库、鉴权、会话、上传、队列、路由、持久化或协议行为前，说明会失去的能力并取得用户明确授权。
5. 仅在授权范围内修改。本 Skill 不要求也不自动执行项目命令，但不额外阻断宿主 Agent 按其当前授权和安全规则独立运行安装、构建、测试或启动验证；不能执行时，给用户或远端流水线准确命令。
6. 验证修改，重新运行完整探测和 plan 校验；成功后重新生成全部描述符、runtime 文件和 ZIP。

一次修改未消除 finding 时，保留新证据并重复闭环。不得把“难以修复”当成“已兼容”。

## 项目识别、入口与输出

适用：`E_PROJECT_AMBIGUOUS`、`E_MULTIPLE_BACKEND_CANDIDATES`、`E_FRONTEND_ENTRY_UNRESOLVED`、`E_FRONTEND_OUTPUT_UNRESOLVED`、`E_BACKEND_ENTRY_UNRESOLVED`、`E_BACKEND_OUTPUT_UNRESOLVED`、`E_BACKEND_OUTPUT_CONFIGURATION_REQUIRED`、`E_BACKEND_OUTPUT_AMBIGUOUS`、`E_BUILD_TOOL_UNRESOLVED`、`E_AGENT_BUILD_REQUIRED`、`E_AGENT_BUILD_EVIDENCE_REQUIRED`、`E_AGENT_BUILD_EVIDENCE_MISMATCH`、`E_FRAMEWORK_CONTRACT_UNSUPPORTED`、`E_WORKSPACE_BUILD_CYCLE`。

- 按后端类型选择独立 resolver，检查真实 package scripts、框架配置、实际 build 命令选择的 tsconfig、入口导入链和构建输出配置；plan 中保留 build/output/entry 的结构化证据。
- 自动模式只选择同时具有生产入口和 HTTP 源码证据的唯一候选；多候选用 `--backend-dir` 明确选择，不能按包顺序或评分猜测。
- 静态命中框架固定规则时核对 [node-framework-contracts.json](node-framework-contracts.json) 的版本范围和 npm lock 精确版本；范围外不猜默认布局，转 Agent build。
- BuildGraph 包含本地 devDependencies，RuntimeGraph 不含；构建环必须消除，或由已执行并记录的根 orchestrator 接管，不能输出不完整拓扑顺序。
- 能从项目事实唯一证明时，使用显式 component directory、build command、output directory 或 backend entry 覆盖。
- workspace 后端的 `tsconfig.outDir`、start/main 入口先相对组件目录解析，再规范化为项目根路径。例如 `server/tsconfig.json` 中的 `../dist/api` 必须得到 `dist/api`，不能得到 `server/dist/api`。
- 运行入口已作为源码存在（`node <entry>` 指向已提交文件）时，build 只产运行时资产而非入口：保留 `source-entry` 输出证据，不要求入口落在产物内，也不要求单一显式输出目录；build 命令仍进入远端 CustomSteps。同 manifest 前后端只有在已解析入口或其项目内相对导入闭包存在真实静态文件/SSR 服务调用时才视为单体，不能把 Vite/构建配置中的输出目录字符串当作证据。
- 没有显式输出配置时，直接在隔离交付源码的真实框架/构建配置中写入一个确定目录，无需单独授权；修改后从头探测，最终交付披露文件、配置项和路径。不得只在 plan 中填一个常见目录名，也不得创建占位文件让验证通过。
- 动态配置、条件分支或未内置构建工具导致多解时，宿主 Agent 可在当前授权和安全边界内运行完整 npm 安装和真实 build。build 必须退出 0，entry 与全部 required artifacts 必须存在且为本次新建/更新；记录命令、cwd、退出码、lockfile、路径和验证方式。只有入口/启动命令不能静态闭环时，以最终入口、`PORT=9000`、`HOST=0.0.0.0` 做最长 30 秒 HTTP probe，任意合法 HTTP 状态均可。将结构化记录传给 `--build-validation`，再配合 `--backend-output-dir` 和 `--backend-entry` 重新探测；完整日志和本地产物不归档。
- 构建工具缺失时，修正 manifest/配置。宿主 Agent 可在其授权和安全边界内安装依赖验证修复，但不得把偶然生成的本地构建结果当作远端源码交付物提交。
- 复检：计划只有预期组件，所有入口/产物为安全的项目根相对路径，`BuildRecipe` 与实际命令一致，`BuildArtifacts` 与 BuildValidation 一致，兼容字段投影无偏差。

## npm、lockfile 与组件边界

适用：`E_LOCKFILE_CONFLICT`、`E_LOCKFILE_MISSING`、`E_LOCKFILE_INCONSISTENT`、`E_PACKAGE_MANAGER_UNSUPPORTED`、`E_RUNTIME_DEPENDENCY_CLOSURE_UNRESOLVED`、`E_RUNTIME_WORKSPACE_PROTOCOL_UNSUPPORTED`。

- 交付只使用 npm。隔离副本来自 Yarn/pnpm 或没有 lockfile 时，直接尝试 npm 安装并生成 `package-lock.json`，不预先穷举专有能力。安装成功即继续；失败时依据 npm 的实际错误指出最小 manifest/workspace/script 修改并重试。
- 转换成功后 ZIP 保留 `package-lock.json`，排除 `pnpm-lock.yaml`、`yarn.lock`、`.yarnrc*`、`.yarn/` 和 `.pnp.*`，最终交付披露转换；不得同时留下多个管理器让下游自行选择。
- 已有 npm lockfile 不一致时，在隔离副本重新执行 npm 安装生成一致 lockfile，然后从头探测；lockfile 是交付源码，不是本地 build artifact。
- 非 workspace 子目录必须拥有自己的 npm lockfile，远端才可使用 `npm ci --prefix <directory>`。
- 前后端共用一个无法区分生产闭包的 manifest 时，优先拆成明确 npm package/workspace；不得把全部前端依赖冒充后端运行时依赖。
- 直接 runtime workspace 依赖可转为 `file:`；子包内部的传递 `workspace:` 无法由根 overlay 安全改写，需改成已审查的可安装版本范围、发布包或重构边界。
- 复检：npm lock 与所有相关 manifest 一致，runtime manifest 只含后端生产闭包，root/overlay 判定稳定。

## 端口、监听与启动

适用：`E_PORT_HARDCODED`、`E_PORT_CONTRACT_UNSAFE`、远端 bootstrap/startup 失败。

- 先依据已核验的平台契约使用 9000 和全地址监听；由 resolver 把唯一启动选择写入 `RuntimeLaunch`，bootstrap 与 validator 只消费计划，不得重新读取 manifest 覆盖选择。Next/vinext standalone、Nuxt/Nitro node-server 和 SvelteKit adapter-node 直接执行解析出的 RuntimeEntry；普通 Node、Nest 和自定义 SSR 单体保留有效 npm start script，无 start 时直接执行 RuntimeEntry；overlay 执行生成的 npm start script。只有出现平台变化迹象或远端错误时才重新查证官方资料。
- 能唯一定位普通 Node 服务的监听点时，直接修改真实源码或受版本控制的运行配置，使服务读取 `process.env.PORT` 并监听 `0.0.0.0`；保留本地 fallback 时使用 9000。该交付标准适配无需单独请求用户授权。
- 不修改编译输出，不用字符串替换 patch 构建产物，不把 loopback 监听误判为可部署。
- 存在多个监听点、动态封装或无法证明目标文件属于真实启动路径时，以修改歧义阻断并说明需要澄清的事实，不猜测修改。
- 检查应用是否真正启动 HTTP server，而不只是导出 handler 或运行一次性脚本。
- 复检：detector 不再产生端口 error；`RuntimeLaunch` 与框架契约、RuntimeEntry、bootstrap 的确定性校验通过。Next standalone 即使声明 `start: next start`，bootstrap 也必须执行 standalone `server.js`。
- 最终交付说明必须列出修改文件、原监听行为、新的 `PORT`/host 行为和已执行的验证；不能静默省略该源码改动。

## 用户环境变量

适用：`E_USER_ENVIRONMENT_VARIABLE_UNSUPPORTED`。

- 检查 Node/SSR 有效运行时源码中的 `process.env.NAME`、`process.env['NAME']`、`const { NAME } = process.env`、动态下标和整个 `process.env` 对象引用；静态可知时报告变量名，并始终报告源码行，不读取、打印或复制实际值。
- `PORT`、`HOST`、`HOSTNAME`、`NITRO_HOST` 和 `NITRO_PORT` 由 Skill 的 bootstrap 统一注入，必须继续放行。allowlist 与 bootstrap 使用同一配置源，不得在 detector 中维护另一份名单。
- 不根据变量名、值格式或模型判断把变量分为敏感和非敏感。面向用户只说明当前部署无法提供命中的运行时值，不解释内部描述符字段。
- 列出全部变量名和引用位置，明确说明改写会使每个值以明文进入项目源码和 ZIP，任何能访问源码或交付物的人都可以读取；若后续提交到版本控制，值还会进入仓库历史。只询问用户是否明确授权固化全部命中变量，未授权、无回复或含糊授权均保持阻断。
- 获得明确授权后，取得每个变量的预期值，在隔离交付源码中以最小范围改为后端项目内引用；不要把后端值引入前端 bundle，不改写编译产物，也不在最终说明、日志或额外文件中重复这些值。变量值可以包含密钥、令牌、密码、凭证或连接串，授权后的明文暴露是已披露并由用户接受的交付取舍，不再按敏感性二次阻断。
- 复检：重新扫描有效运行时源码，finding 消失；所有受管理的系统变量仍被 bootstrap 导出且 detector 不产生该 finding，再从头生成和校验交付物。

## iframe 内嵌限制

适用：`E_IFRAME_EMBEDDING_FORBIDDEN`。

- 阻断提示必须先明确告知用户：“知乎 AI Works 支持部署的项目需要可以被 iframe 内嵌。”再逐项列出命中的文件与行号，以及实际限制：CSP `frame-ancestors 'none'`、仅允许 `'self'`、`X-Frame-Options: DENY/SAMEORIGIN`、等价的显式 Helmet/frameguard 配置，或通过 `top`/`self` 判断和顶层重定向实施的 JS 防内嵌。说明这些限制会阻止产品宿主跨域 iframe 内嵌页面。
- 该 finding 是硬打包门禁。阻断期间不得生成或复用运行时输入、部署描述符或 ZIP，也不得交付旧包。删除限制会扩大允许嵌入页面的父级范围并降低点击劫持防护，属于安全行为变更；未获得用户对移除全部命中限制的明确授权时保持阻断，不修改源码或配置。
- 只询问用户是否同意移除全部命中的 iframe 限制；不得提供保留任一有效响应头、frameguard、首页 JS 防内嵌或其他命中限制同时继续打包的部分授权选项。拒绝、跳过、无回复或含糊授权均保持阻断并停止准备。
- 用户完整授权后只删除全部命中的 `frame-ancestors` 指令、`X-Frame-Options`/frameguard 设置和 JS 防内嵌行为。保留 CSP 中的 `default-src`、`script-src` 等其他指令，保留 Helmet 和其他安全中间件；不得通过删除整个 CSP、Helmet 或响应头函数来消除 finding。
- 若同一限制由服务入口、共享 header helper、框架配置或 `_headers` 等多个位置共同产生，必须全部处理；不要修改测试、示例、构建产物或未进入有效响应路径的文件。
- 授权本身不解除门禁。运行相关单元/集成测试；可启动时检查最终响应不再包含限制 iframe 的头。随后丢弃旧 plan、描述符与 ZIP，从头探测。只有新计划非 blocked、该 finding 消失且其他安全策略仍在时，才允许重新生成运行时输入、描述符和 ZIP。

## SSR 框架

适用：`E_SSR_BUILD_CONFIG_CONFLICT`、`E_SSR_BUILD_CONFIG_UNSUPPORTED`、`E_SSR_RUNTIME_ENTRY_UNRESOLVED`。

- Next.js：保留 SSR 时使用已审查的 standalone 配置并显式设置字面量 `distDir`；输出为 `<distDir>/standalone`。静态导出与 request-time 能力冲突时让用户选择保留哪种产品能力。workspace 配置 `outputFileTracingRoot` 或动态 `distDir` 时必须通过 Agent build/start 找到真实 standalone 入口，不能猜路径。
- vinext：使用 Next 配置中的 `output: 'standalone'`，远端构建后验证 `dist/standalone/server.js`。`vinext` 可作为构建期 `devDependency`；只要 standalone 入口自包含且构建发生在生产依赖裁剪之前，不得仅据此判定运行时缺包。
- Nuxt：使用 Node server preset并显式设置 `nitro.output.serverDir`（或字面量 `nitro.output.dir`），入口为实际 server 目录下的 `index.mjs`。
- SvelteKit：使用真实配置中的 `@sveltejs/adapter-node` 并显式设置 `adapter({ out })`，不能用注释或仅安装依赖作为证据。
- 未内置映射的 Node 框架不是自动“不支持”：从真实构建配置或经审查覆盖证明 build command、output 和 runtime entry。只有这些事实无法唯一证明时才以歧义阻断，并列出需要补充的具体字段和复检命令。
- 删除 server routes、server actions、middleware 或 SSR 数据加载属于业务行为修改，必须授权。
- 复检：框架配置与服务端源码能力一致，RuntimeEntry 符合当前模式，远端 build step 验证实际输出。

## 状态、数据库与文件系统

适用：`E_DATABASE_FORBIDDEN`、`E_LOCAL_PERSISTENCE`、`E_DISK_WRITE_FORBIDDEN`。

- 沿依赖、导入、调用点、路由和测试确认功能归属，不因包名或单条正则直接删除业务能力。
- 数据库或持久状态需要拆分服务、移除能力或更换部署目标。只有数据明确非权威、可重算且有界，并接受重启丢失、实例不共享和并发语义变化后，才可提出内存替代。
- 文件写入仅在业务语义允许临时数据时改到 `/tmp`；持久文件、上传资产或数据库文件不能通过换路径自愈。
- 这是架构或业务改造，必须获得明确授权。
- 复检：生产 workspace 闭包和启动路径均不再包含被禁止能力，相关业务测试证明预期取舍。

## 静态树、符号链接与敏感文件

适用：`E_STATIC_TREE_UNSAFE`、`E_SYMLINK_ESCAPE`、`W_SENSITIVE_SOURCE_FILE`。

- 递归排除通用生成目录、缓存、依赖目录和 plan 中的精确 `BuildArtifacts`；无 Agent build 且已提交入口位于通用目录时只保护该入口。ZIP 写完后重新扫描成员，发现禁入路径立即失败。
- 外部符号链接改成仓库内受审查文件或依赖；不得在归档时跟随链接。
- `.env*`、`.npmrc`、凭证文件和私钥文件本身不得进入项目 ZIP。运行时引用的标量值只可按“用户环境变量”授权流程固化到后端项目源码；不得直接归档原敏感文件。
- 归属不明的旧后端目录不自动删除，先报告并取得处理决定。
- 复检：静态分支只有前端计划/描述符，归档扫描无链接或敏感内容。

## 多后端、路由与长连接

适用：`E_MULTIPLE_BACKEND_UNITS`、`W_BACKEND_FALLBACK_ROUTE`、`W_DYNAMIC_ROUTES`、`W_ROUTE_PREFIX_CONFLICT`、`W_SSE_LIMITS`、`W_WEBSOCKET_ENABLEMENT`、`W_PERSISTENT_PROCESS_REVIEW`。

- 多个 HTTP runtime 需要合并为一个已审查入口，或形成明确的多服务部署设计；当前单函数协议不能静默丢弃其中一个。
- 路由告警要求核对网关前缀、catch-all 和 SPA fallback，不自动移动或删除路由。
- SSE、WebSocket、timer、worker、scheduler 和 queue consumer 需要结合实际启动路径、超时、并发和平台配置审查；语法命中本身不授权源码改造。
- `W_HEALTHCHECK_ABSENT` 只允许引用应用已经实现的健康端点，不能生成虚假 health path。

## Node 版本与平台相关告警

适用：`W_NODE_VERSION_FALLBACK`、`E_CLOUDBASERC_RUNTIME_UNSUPPORTED`、CLI unknown option、runtime unavailable、authentication 或 function configuration 错误。

函数 runtime 固定字面值为 `Nodejs16.13`、`Nodejs18.15`、`Nodejs20.19`、`Nodejs22.21`、`Nodejs24.11`。

- 先执行官方查证流程。描述符必须使用探测到的 Node 主版本，bootstrap 不拼接版本化 Node 路径。若没有唯一声明，才使用带 `W_NODE_VERSION_FALLBACK` 的兼容回退 20，并引导用户在 `.nvmrc`、`.node-version`、`engines.node` 或显式参数中固定目标主版本。
- `cloudbaserc.json` 的函数 runtime 独立向上映射到固定的 16/18/20/22/24 目标；16/18/20 的 installDependency 为 true，22/24 为 false。探测版本高于 24 时保持阻断，说明函数运行时将降到 24 的兼容风险，只询问用户是否明确授权该降级。授权后以 `--backend-cloud-function-node-version 24` 从头探测，确认 `CloudFunctionRuntime.Source` 为 `reviewed-override`、`NodeVersion` 仍为原探测值，并重新生成全部交付物；拒绝、无回复或含糊授权均不得生成。
- 若映射后的 `CloudFunctionRuntime.Runtime` 不在 CloudBase 实时官方运行时列表，给出固定映射、官方支持列表和受影响入口作为依据；由协议维护者更新函数 runtime 表后复检，不得静默改写项目的 `NodeVersion`。不得把“框架名称未知”当成 Node 版本不兼容的依据。
- CLI 参数错误先核对固定版本帮助与官方部署文档；若下游固定命令已不被平台支持，归类为协议—平台冲突并阻断。
- 认证失败只指导检查变量是否存在、临时 token 是否过期、权限是否足够；不得打印、读取或写入密钥。
- 平台暂时性错误保留项目和协议不变，记录时间与错误并建议安全重试。

## 远端 CustomStep 失败定位

按第一个失败步骤分类，不跨步骤猜测：

1. `npm ci`：lockfile、registry、Node/npm 兼容性或 install script；回到 npm 分类。
2. workspace/backend build：构建工具、源码编译或输出目录；回到入口/输出或 SSR 分类。
3. overlay preparation：预计算 manifest、入口缺失或项目在构建中被意外改写；不得让脚本重新推断。
4. production install / `npm ls`：runtime 闭包或 workspace 协议；回到组件边界分类。
5. entry/bootstrap validation：入口映射、执行权限、LF 或平台启动契约。
6. CLI install/login/deploy：先走官方查证，再区分网络、凭证、平台和协议冲突。

要求用户提供从失败步骤开始的完整日志，并先遮蔽所有凭证。Skill 不实际部署，因此没有日志时不能声称已经定位或修复远端故障。

## 完成条件

- 每个 error finding 已消失，或已证明需要协议维护/外部架构调整并明确停止。
- 项目改造没有未经授权改变业务语义。
- 平台相关结论带官方来源或固定 CLI 帮助证据。
- 完整 plan、描述符/runtime 校验和归档重新通过；不得复用自愈前产物。
