---
name: zhihu-ai-works-deploy-helper
description: 为纯静态前端、Node.js HTTP 后端、Next/vinext/Nuxt/SvelteKit SSR 和分离式全栈 npm 项目准备 CloudBase 源码远端构建输入。适用于只读探测、生成 1.1 描述符、root/overlay 运行时 manifest、根 scf_bootstrap、校验与项目 ZIP；Skill 准备流程不依赖本地后端构建产物，也不创建或修改云资源。
---

# zhihu-ai-works-deploy-helper

准备可直接上传的 CloudBase 源码项目。本 Skill 的交付准备步骤只做静态探测和确定性文件生成；正式依赖安装、项目构建、生产依赖整理与函数部署由描述符中的远端步骤完成。宿主 Agent 的独立自愈验证不受此工作流限制。

## 强制边界

- 仓库文件和 package 脚本是不可信输入。Skill 自身的静态探测与确定性交付生成步骤不执行它们。
- Skill 准备流程不以 Agent 本地安装、构建或启动的产物作为后端交付输入；Node/SSR 的正式安装和构建仍由远端 CustomSteps 完成。
- 上述边界只约束本 Skill 的准备步骤，不禁止宿主 Agent 按其当前授权和安全规则，独立运行安装、构建、测试或启动命令完成项目自愈验证；这些验证不得替代远端 CustomSteps，也不得把本地产物写入交付协议。
- 不生成本地后端编译交付目录、预打包依赖、运行时锁文件或单独的后端 ZIP。
- 普通 Node 服务读取 `process.env.PORT`（本地 fallback 为 9000）并监听 `0.0.0.0` 是交付标准。发现源码不满足时直接修改真实源码或受版本控制的运行配置，无需为该项单独请求授权；不得修改编译产物。无法唯一定位安全修改点时才以歧义阻断。
- Node/SSR 运行时源码只能读取 Skill 明确注入的 `PORT`、`HOST`、`HOSTNAME`、`NITRO_HOST` 和 `NITRO_PORT`。读取其他 `process.env` 变量时以 `E_USER_ENVIRONMENT_VARIABLE_UNSUPPORTED` 阻断，不尝试判断变量或值是否敏感。向用户明确说明改写后所有值都会以明文进入项目源码和 ZIP、任何可访问交付物的人都能读取；只有用户明确授权将全部命中值固化为项目内引用后，才在隔离交付源码中做最小改写并从头探测。未授权、无回复或含糊授权均保持阻断。
- 构建型后端必须把唯一输出目录固化在真实框架或构建配置中。配置缺失时直接在隔离交付副本中补充确定目录，无需单独请求授权；修改后从头探测，并在最终 ZIP 交付说明中披露修改文件、配置项和路径。配置动态或存在多解时，宿主 Agent 可在其授权边界内实际安装、构建和启动验证，再用已审查的显式输出目录与入口重新探测；本地产物不得进入 ZIP。
- 知乎 AI Works 支持部署的项目需要可以被 iframe 内嵌。探测到有效响应头配置明确使用 CSP `frame-ancestors 'none'`、仅允许 `'self'`、`X-Frame-Options: DENY/SAMEORIGIN`，或有效页面代码通过 `top`/`self` 判断和顶层重定向实施 JS 防内嵌时，以 `E_IFRAME_EMBEDDING_FORBIDDEN` 硬阻断并列出命中文件。阻断期间不得生成或复用运行时输入、部署描述符和 ZIP。移除这些限制会降低点击劫持防护，必须先取得用户对“移除全部命中限制”的明确授权；不得提供保留任一有效阻断但继续打包的部分授权选项。授权只允许执行最小修改，不直接解除门禁；修改后保留其他 CSP 指令和安全中间件并从头探测，只有新的非 blocked 计划不再包含该 finding 时才可生成部署包。
- 交付包管理器固定为 npm。隔离副本没有 `package-lock.json`，或来自 pnpm/yarn 时，宿主 Agent 直接尝试 npm 安装；成功后保留生成的 npm lockfile，排除旧包管理器 lock/config 并披露转换。只有 npm 实际失败时才按错误阻断和引导修复。
- 纯静态分支绝不调用后端生成器，不计算运行时依赖，不生成后端计划字段、描述符、manifest、准备脚本或 bootstrap。
- 仅清理能够证明由本 Skill 生成的旧文件；归属不明时阻断并报告。
- 项目变化后，旧计划、描述符、bootstrap、运行时 manifest 和 ZIP 全部失效，必须从探测重新开始。
- 不创建或修改 CloudBase 资源，不执行实际部署命令。

## 必读资料

- 分类和运行时模式：[references/detection.md](references/detection.md)
- 描述符及文件协议（最高交付优先级）：[references/protocol.md](references/protocol.md)
- 官方依据、平台事实与查证流程：[references/platform-contract.md](references/platform-contract.md)
- 阻断与授权改造：[references/remediation.md](references/remediation.md)

## 依据优先级

1. [references/protocol.md](references/protocol.md)、本地 schema 和确定性生成器定义下游必须接收的字段、文件、命令顺序与分支不变量；Agent 不得用通用 CloudBase 示例擅自改写这些约定。
2. CloudBase 官方文档与固定 CLI 的实时帮助定义运行时、启动文件、CLI 参数和认证方式等平台事实。
3. 当前项目源码、manifest、lockfile、框架配置和错误日志定义项目事实。
4. 模型记忆、博客和第三方示例只能作为检索线索，不得作为交付或自愈依据。

下游协议与官方平台事实出现冲突时，不允许 Agent 自动降低、替换或扩展协议，也不允许忽略平台不兼容；必须停止生成，列出双方证据并请求维护者处理协议。仅当问题被证明属于项目事实时，才进入源码自愈。

## 统一阻断输出

任何阶段发生阻断时，都必须在同一次回复中给出：阻断项、直接证据、适用的协议/平台/项目依据、当前根因或尚未确认的事实、可执行的自愈步骤，以及完成自愈后的复检方式。不得只说“不支持”“验证失败”或“需要修改”。

能安全自动修复的项目问题直接按 remediation 处理并复检；需要用户选择、凭证、外部系统或协议维护时，自愈引导必须明确说明由谁提供什么、修改哪个位置或执行什么命令，以及满足什么条件后可以继续。无法自动修复不等于可以省略自愈引导。

## 工作流

### 0. 尽力检查并更新 Skill

在读取用户项目之前先运行下面的检查命令。宿主若已知当前执行环境默认禁网，必须先明确告知用户自动更新需要访问更新索引和 Skill ZIP，并请求用户授权网络；授权后按宿主自身的权限机制为本次更新阶段提供网络访问。权限仅用于更新索引 `https://openapi.zhihu.com/aiworks/publish_config/skill` 和经过检查器校验的 ZIP URL 主机，不得申请无限制网络，也不得把网络权限扩大到用户项目脚本：

```bash
python3 <skill-dir>/scripts/check_skill_update.py --skill-dir <skill-dir>
```

该检查是 advisory。若首次检查因沙箱禁网、DNS 解析失败或等价网络错误得到 `check-failed`，不得直接跳过更新：必须明确告知用户当前失败由网络限制引起，并请求用户授权网络。授权后用宿主提供的网络权限重试检查器一次，再按新结果继续更新流程；用户拒绝、未授权、宿主策略禁止网络或授权后仍失败时，简要报告原始错误，明确说明将使用本地版本并继续步骤 1。配置或版本元数据等非网络错误不请求网络授权，直接报告并使用本地版本继续。所有检查结果的 `blocking` 均为 false。

- `current`、`local-ahead`：继续步骤 1。
- `remote-unversioned`、非网络原因的 `check-failed`：提醒无法确认最新版，使用本地版本继续步骤 1，不进入“统一阻断输出”或 remediation 闭环。
- 网络原因的 `check-failed`：按上述授权流程最多重试检查器一次；未获授权或重试失败时使用本地版本继续步骤 1。
- `update-available` 且 `installable: false`：报告本地/远端版本和 warning，继续步骤 1。
- `update-available` 且 `installable: true`：复用本次更新阶段已获网络授权；若宿主按命令授权，则明确告知用户将下载新版 Skill，并为安装命令请求访问经过检查器校验的 ZIP URL 主机。正式发布当前预期为 `zhstatic.zhihu.com`，实际主机始终以检查器返回并校验的 `url` 为准。同一任务最多尝试安装一次：

```bash
python3 <skill-dir>/scripts/install_skill_update.py \
  --skill-dir <skill-dir> \
  --version <remoteVersion> \
  --url <url> \
  --sha256 <sha256> \
  --size <size>
```

安装失败时简要报告原始错误并继续使用当前版本。安装成功时重新读取更新后的 `SKILL.md`，再用上述受控网络权限运行一次检查器确认状态，然后直接继续步骤 1；即使复查仍为 `update-available` 或失败，也不得进行第二次安装尝试或扩大网络权限。调试阶段允许 HTTP 更新索引或 ZIP，但必须披露不安全传输 warning；正式分发使用 HTTPS。

### 1. 多轮变更与产物失效

任何源码、manifest、lockfile、框架配置、路由或生成文件变化都会使旧交付状态失效。移除能够证明由本 Skill 生成但已不属于当前分支的文件；归属不明则停止并报告。从下一步重新执行完整探测，不沿用旧结论。

### 2. 不执行代码的探测阶段

对 package 项目先统一 npm 输入：若隔离副本没有 `package-lock.json`，或存在 pnpm/yarn lock/config，宿主 Agent 在当前授权和安全边界内直接尝试 `npm install`。成功后保留生成的 `package-lock.json`，移除隔离副本中的旧 lock 和专属运行配置并继续，不暂停询问；只有 npm 实际失败或宿主无执行授权时才按真实错误阻断。原始项目保持不变，最终交付披露转换。

```bash
python3 <skill-dir>/scripts/inspect_node_project.py \
  --root <project> \
  --output <project>/_tmp/deploy-plan.json

python3 <skill-dir>/scripts/validate_deploy_output.py \
  --plan-only <project>/_tmp
```

可传入已审查的 `--frontend-dir`、`--backend-dir`、构建命令、`--frontend-output-dir`、`--backend-output-dir`、`--backend-entry`、Node 版本、路由前缀和健康检查路径。Agent build 消歧还必须传 `--build-validation <json>`；探测器会核对实际命令、入口和产物，不接受只有路径覆盖而没有验证链的结果。

如果计划为 blocked，停止生成并按“统一阻断输出”逐项处理；不得调用运行时输入、描述符或归档生成器，也不得交付已有 ZIP。npm manager/lock finding 先在隔离副本自动尝试 npm 转换并从头探测，成功时不向用户制造一次中断。`E_PORT_HARDCODED`、`E_PORT_CONTRACT_UNSAFE` 和 `E_BACKEND_OUTPUT_CONFIGURATION_REQUIRED` 直接按交付标准修改可唯一定位的真实源码/配置，无需暂停请求单独授权；修改后复检并从头探测。`E_USER_ENVIRONMENT_VARIABLE_UNSUPPORTED` 不向用户解释内部描述符字段，只列出变量名、源码位置和当前部署无法提供这些运行时值的事实；不判断敏感性，明确披露全部值将以明文进入源码和 ZIP 后，只询问用户是否授权固化全部命中变量。获得明确授权后在隔离交付源码中改为项目内引用，不在最终说明中重复变量值，再从头探测；未授权、无回复或含糊授权保持阻断。`E_IFRAME_EMBEDDING_FORBIDDEN` 是硬打包门禁：阻断提示必须明确原文告知用户“知乎 AI Works 支持部署的项目需要可以被 iframe 内嵌”，再说明全部命中证据和点击劫持防护变化，只询问用户是否明确授权移除全部命中的 iframe 限制。不得提供保留首页 JS 防内嵌、响应头、frameguard 或其他有效阻断同时继续打包的选项；拒绝、跳过、无回复或含糊授权均保持阻断并结束准备。获得完整授权后，只移除全部命中的 `frame-ancestors` 指令、`X-Frame-Options`/frameguard 设置和 JS 防内嵌行为，不删除完整 CSP 或 Helmet，再运行相关测试或启动探测并从头探测。授权本身不解锁打包；只有新计划非 blocked 且不再包含 `E_IFRAME_EMBEDDING_FORBIDDEN` 时，才能继续生成运行时输入、描述符和 ZIP。`E_BACKEND_OUTPUT_AMBIGUOUS`、`E_AGENT_BUILD_REQUIRED` 按 finding 中的 Agent build/start 验证流程消歧，并用 `--build-validation`、`--backend-output-dir` 与 `--backend-entry` 固化已验证结果。其他 finding 先按 platform contract 判断是否依赖平台事实并完成官方查证，再根据 remediation 解释证据、能力影响和最小改造；涉及业务行为或架构取舍时取得用户明确授权。项目命令是否执行遵循宿主 Agent 当前授权与安全规则。

### 2. 按项目类型分支

#### 纯静态

包括构建型静态前端和 `DeliveryMode: static-files`。只运行描述符生成器：

```bash
python3 <skill-dir>/scripts/write_deploy_descriptors.py \
  --output-root <project> \
  --plan <project>/_tmp/deploy-plan.json \
  --frontend-install-cmd "npm ci"
```

Build-free 静态目录省略 `--frontend-install-cmd`。最终只能有：

```text
<project>/_tmp/deploy-plan.json
<project>/_tmp/frontend.deploy.json
```

若存在任何后端预置文件，不得归档或完成交付。

#### 含 Node 后端或 SSR

先生成 Agent 预计算的运行时输入，再生成描述符：

```bash
python3 <skill-dir>/scripts/write_backend_runtime.py \
  --project-root <project> \
  --plan <project>/_tmp/deploy-plan.json

python3 <skill-dir>/scripts/write_deploy_descriptors.py \
  --output-root <project> \
  --plan <project>/_tmp/deploy-plan.json \
  --frontend-install-cmd "npm ci"
```

纯后端可省略前端安装参数。Node 项目始终生成根 `scf_bootstrap` 和根 `cloudbaserc.json`。`cloudbaserc.json` 固定使用 `{{env.CLOUDBASE_ENV_ID}}`、`{{env.CLOUDBASE_SERVICE_NAME}}`、函数根 `.` 和 HTTP 类型；只有 runtime 与 installDependency 按计划中的 `CloudFunctionRuntime` 投影。只有 overlay 模式生成：

```text
_tmp/backend.runtime.package.json
_tmp/prepare-backend-package.js
```

root 模式不得生成或执行这两个文件。

### 3. root 与 overlay

root 模式仅用于组件目录为项目根、项目类型为纯 Node 后端或 SSR、且根 manifest 就是完整运行时 manifest 的项目。典型为根级 Express/Koa/Nest、Next/vinext SSR、Nuxt SSR 和 SvelteKit SSR。

overlay 模式用于分离式全栈、子目录 Node、workspace SSR、根 manifest 为聚合器或无法证明根依赖完整的项目。

后端组件必须包含：

```json
{
  "RuntimeManifestMode": "root | overlay",
  "RuntimeEntry": "项目根相对入口",
  "RuntimePackagePath": "实际运行时 package.json 路径",
  "RuntimeLaunch": {
    "Kind": "node-entry",
    "Entry": "与 RuntimeEntry 相同的项目根相对入口",
    "Source": "resolver 的选择依据"
  },
  "CloudFunctionRuntime": {
    "Runtime": "Nodejs22.21",
    "InstallDependency": false,
    "Source": "auto-map | reviewed-override"
  }
}
```

`RuntimeLaunch` 是 resolver 对启动方式的权威选择；`node-entry` 使用与 `RuntimeEntry` 相同的 `Entry`，`npm-script` 改用安全的 `Script` 名称。bootstrap 和 validator 只消费该字段，不得重新读取 package manifest 后覆盖它。还必须包含 `RuntimeResolution`、`BuildRecipe` 和 `BuildArtifacts`。`RuntimeResolution` 记录 resolver、版本化框架契约及 build/output/entry 的结构化事实；具有固定启动方式的 SSR 框架契约同时声明 `LaunchKind`。`BuildRecipe` 是有序的实际 npm 构建步骤；`BuildArtifacts` 只记录生成内容，角色限于 `server-runtime`、`runtime-assets`、`runtime-metadata`，路径统一为项目根相对路径。旧 `BuildCommand`、`OutputPath` 和 `WorkspaceDeps.BuildOrder` 只是经过 validator 交叉校验的兼容投影。

workspace 同时生成两张图：`BuildGraph` 包含本地 `dependencies`、`optionalDependencies`、`devDependencies`，用于排序和构建环检测；`RuntimeGraph` 只包含生产依赖，用于运行时闭包。存在构建环时默认阻断，不能按扫描顺序继续；只有经 Agent build 证据验证的根 orchestrator 可以接管完整构建配方。

overlay manifest 只保留合法的 name、version、private、type，写入根相对 main/start，仅含生产依赖；直接运行时 workspace 依赖写为 `file:./<directory>`。若运行时 workspace 子包自身仍含传递 `workspace:` 声明，因根级 overlay 无权改写子包 manifest，必须阻断并报告。准备脚本只校验预计算文件和运行时入口，再原子替换根 manifest；不得扫描、推断、合并或复制项目资源。

### 4. 后端 resolver 与运行时入口

- 普通 Node/TypeScript resolver：从实际 `scripts.build` 选择 `tsc -p/--project`、`--project=` 或 `tsc -b/--build` 配置，递归解析项目内相对 `extends` 和 project references，以各自声明 `outDir` 的配置文件为路径基准；入口来自已审查参数、直接 `node <entry>` 的生产 start 或 package main。
- 源码入口 + 资产构建：入口是已提交源码（如 `node server.js`）而 build 只产出运行时读取的资产（如 `dist/client`、`dist/server`）时，入口保持源码、`OutputPath` 为 null，build 命令照常进入 CustomSteps，不要求入口落在产物内。同一 manifest 同时含前端框架与服务端框架时，仅当已解析的生产入口或其项目内相对 import/require 闭包包含真实的静态文件/SSR 服务调用，才判为自定义 SSR 单体（`backend-http`、catch-all）；构建输出目录字符串本身不是证据。
- Nest resolver：优先读取 build 命令选择的配置，再读取 `nest-cli.json#compilerOptions.tsConfigPath` 或 `tsconfig.build.json`，并与生产 start/main 入口交叉验证。
- Next resolver：要求 standalone，读取字面量 `distDir` 后得到 `<distDir>/standalone`；`BuildRecipe` 在 build 后把 `<distDir>/static` 复制到 standalone 内相同的 distDir 相对位置，并在存在时把 `public` 复制到 standalone。workspace 的 `outputFileTracingRoot` 或动态输出配置必须由 Agent build/start 验证实际 `server.js`。
- vinext resolver：依据其固定 standalone 构建契约使用 `dist/standalone/server.js`，并保留框架契约作为显式证据。
- Nuxt/Nitro resolver：读取 `nitro.output.serverDir`，或由字面量 `nitro.output.dir` 推导其 `server` 子目录；入口为该目录的 `index.mjs`。
- SvelteKit adapter-node resolver：读取 `adapter({ out })`，入口为该目录的 `index.js`。

自动后端选择先枚举全部“有生产入口且源码具有 HTTP listen/createServer/serve 证据”的候选。只有唯一候选时自动选择；框架依赖本身不是服务证据，多候选必须用 `--backend-dir` 明确指定。

v1 静态 resolver 只覆盖：已提交 Node 入口、上述 TypeScript 形态、Nest CLI、版本契约覆盖的 Next/vinext/Nuxt/SvelteKit，以及源码 Node 入口配合可静态证明的 Vite 资产输出。tsup、esbuild、swc、Babel、webpack、Rollup、Turbo、Nx、自定义 shell 和动态框架配置统一进入 Agent build，不猜路径。框架契约维护在 [references/node-framework-contracts.json](references/node-framework-contracts.json)，静态命中必须记录 lockfile 精确版本和契约 ID。

构建型后端没有显式输出配置时，先由 Agent 在隔离交付源码中写入确定目录，再从头探测，不直接采用隐式默认目录完成交付。静态证据不足时，Agent build 必须退出 0，确认 `RuntimeEntry` 和全部 required artifacts 是本次新建/更新内容，并记录命令、cwd、退出码、npm lockfile、路径和验证方式。只有入口与启动命令不能静态闭环时才执行 start probe：使用最终入口、`PORT=9000`、`HOST=0.0.0.0`，30 秒内得到任意合法 HTTP 响应即通过，然后终止进程。证据写入 plan 的 `BuildValidation`，完整日志不进入交付。验证产物只能用于消歧，必须由归档器排除，正式产物仍由远端 CustomSteps 从源码重建。

普通 Node workspace 的 start/main 入口与 `tsconfig.outDir` 都先按组件目录解析一次，再以项目根相对路径写入计划。保留仍在项目根内的 `../` 语义；不得用 `lstrip("./")` 删除父目录，也不得在生成 CustomSteps 时再次添加组件目录。

bootstrap 设置端口 9000 和全地址监听变量，并严格执行 `RuntimeLaunch`。当前 Next standalone、vinext standalone、Nuxt/Nitro node server 和 SvelteKit adapter-node 框架契约选择 `node-entry`，即使 root `package.json#scripts.start` 存在也直接 `exec node <RuntimeEntry>`；这些入口是 resolver 已确认的实际部署产物，不能被源码开发/通用生产 script 覆盖。普通 Node、Nest 和自定义 SSR 单体在 root manifest 有非空 `scripts.start` 时选择 `npm-script:start`，以保留 script 中的必要启动逻辑；没有 start 时选择 `node-entry`。overlay manifest 固定生成 start script 并选择 `npm-script:start`。新增 resolver 必须在框架契约中显式声明 `LaunchKind`，不得按“SSR”名称或 manifest 是否存在 start 二次猜测。不得拼接 `/var/lang/node<major>/bin/node`。文件必须为 LF、末尾换行和 `0755`。探测到的 Node 主版本仍原样写入 `backend.deploy.json#NodeVersion`；没有唯一项目声明时才使用带 warning 的兼容回退 20，不能覆盖已探测版本。函数 runtime 单独向上映射：不高于 16、18、20、22、24 的主版本分别使用 `Nodejs16.13`、`Nodejs18.15`、`Nodejs20.19`、`Nodejs22.21`、`Nodejs24.11`；映射到 16/18/20 时 `installDependency` 为 true，映射到 22/24 时为 false。探测版本高于 24 时以 `E_CLOUDBASERC_RUNTIME_UNSUPPORTED` 阻断；只有用户明确授权降级后，才以 `--backend-cloud-function-node-version 24` 记录 reviewed override，且不得改写 `NodeVersion`。

### 5. 远端 CustomSteps

生成器按以下顺序写入后端描述符：

每个 `CustomSteps` 元素必须是 `{"Name":"非空显示名称","Command":"非空命令"}` 对象，不得写成字符串。`Name` 和 `Command` 都必须是无 CR/LF 的单行字符串；一个步骤内的多条 shell 操作用行内 ` && ` 连接，不得写入字面换行。`Name` 只用于展示，步骤语义和确定性校验以同一对象中的 `Command` 为准。

1. `npm ci` 安装完整构建依赖。
2. 严格按 `BuildRecipe` 构建 workspace/后端，再对每个 required `BuildArtifact` 执行存在性验证；无需构建时验证已有入口。
3. 仅 overlay 执行 `node _tmp/prepare-backend-package.js`。
4. `npm install --omit=dev --ignore-scripts`。
5. 验证生产依赖、入口、bootstrap、`cloudbaserc.json`，并输出 manifest、bootstrap 与函数配置。
6. 安装固定版本 CloudBase CLI。
7. 使用环境变量登录，并以字面量 `${functionName}` 作为函数名占位符从项目根部署 HTTP 云函数；Skill 不读取项目名生成函数名，占位符由下游在执行前替换。

严禁通过 shell 文件存在性判断动态选择 overlay；该步骤必须由计划模式确定性生成。

### 6. 最终校验与归档

```bash
python3 <skill-dir>/scripts/validate_deploy_output.py <project>
python3 <skill-dir>/scripts/create_project_archive.py \
  --project-root <project> \
  --plan <project>/_tmp/deploy-plan.json
```

ZIP 递归排除 `.git`、所有 `node_modules`、`dist`、`build`、`out`、`.next`、`.nuxt`、`.output`、`.svelte-kit`、`.vite`、`.turbo`、coverage/cache、本次 `BuildArtifacts` 精确路径、pnpm/yarn lock 与专属配置、macOS 元数据（包括 `__MACOSX`、`.DS_Store` 和 `._*` AppleDouble 文件）、`.env*`、`.npmrc`、凭证、私钥、符号链接和非普通文件。无 Agent build 且入口本身是已提交源码时保护该入口不被通用目录规则误删。项目目录名中的空白字符在 ZIP 文件名、ZIP 唯一根前缀和 `frontend.deploy.json#BuildPath` 中统一替换为 `_`；不重命名隔离源码目录本身。写入后复检 ZIP；根 ZIP mode 为 `0666`。

## 完成条件

- `_tmp/deploy-plan.json` 与全部描述符通过 schema 和语义校验。
- 最终计划不是 blocked，且不存在 `E_IFRAME_EMBEDDING_FORBIDDEN`；用户授权只有在全部命中限制已实际移除并从头探测通过后才满足此条件。
- 静态项目不存在任何后端输入、`cloudbaserc.json` 或后端运行时计划字段。
- Node 项目存在根 `scf_bootstrap` 和确定性 `cloudbaserc.json`；root 无 overlay 文件，overlay 文件齐全且替换步骤位于构建之后。
- 描述符不包含本地构建产物路径，后端步骤从源码根执行远端构建与部署。
- ZIP 通过 CRC 校验且不包含排除项。
- 最终交付说明列出 Agent 为满足端口交付标准而修改的源码文件及修改前后行为；同时列出为确定输出目录而修改的配置文件、配置项、最终路径及验证结果。若使用 Agent build 消歧，还要列出执行命令和观察到的入口。不得把直接修改隐瞒为项目原状。
- 最终告知用户上传根目录生成的项目 ZIP；不得声称已部署云资源。
