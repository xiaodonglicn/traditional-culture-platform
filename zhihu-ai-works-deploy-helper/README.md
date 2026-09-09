# zhihu-ai-works-deploy-helper

为纯静态前端、Node.js HTTP 后端、Next.js/vinext/Nuxt/SvelteKit SSR 和分离式全栈 npm 项目准备 CloudBase 源码远端构建交付物的通用 Agent Skill。

## 安装

下载发布的 Skill ZIP 并解压，然后从解压目录安装：

```bash
npx skills add /path/to/zhihu-ai-works-deploy-helper -g
```

已安装 `1.1.1` 或更早 Git 分发版本的用户需要按上述方式人工重装一次；后续版本由 Skill 的更新索引检查 ZIP 更新。若检查遇到沙箱禁网或 DNS 解析失败，Agent 会明确说明原因并请求网络授权；授权后继续检查和下载，未授权或网络仍不可用时使用本地版本继续部署准备任务。

## 使用

在项目目录中告诉 Agent：

```text
使用 $zhihu-ai-works-deploy-helper 检查当前项目并生成 CloudBase 交付 ZIP。
```

Skill 会先检查项目。能够安全处理的问题会直接处理并复检；需要业务选择、外部信息或人工调整时，会说明原因和下一步。

## 能做什么

- 支持静态网站、Vite 等前端项目。
- 支持 Express、Koa、Nest 等 Node.js HTTP 服务。
- 支持 Next.js、vinext、Nuxt 和 SvelteKit 的 Node.js SSR 项目。
- 支持前后端分离项目和 npm workspace 中的单个 Node.js 服务。
- 为 Node 后端生成根 cloudbaserc.json，并按固定的 CloudBase 函数运行时表映射项目 Node 版本。
- 识别构建方式、运行入口、输出目录和路由，处理常见的交付兼容问题。
- 检查会阻止产品页面通过 iframe 内嵌的响应头和 JS 防内嵌行为并硬阻断打包；只有用户明确同意移除全部命中限制、完成最小修复且重新探测通过后才生成部署包。
- 生成经过检查、可直接上传的 CloudBase 源码交付 ZIP。
- 交付统一使用 npm；其他包管理器会先尝试转换，遇到问题时给出继续处理的方法。
- 最终 ZIP 以源码交付，不使用本地临时构建产物代替 CloudBase 构建。

## 不能做什么

- 不创建、修改或实际部署 CloudBase 云资源。
- 不在无法确认构建结果或运行入口时猜测交付路径。
- 不静默删除数据库、持久化、鉴权或其他业务能力。
- 不在用户完整授权前移除 CSP、X-Frame-Options 或其他 iframe 限制；不提供保留任一有效阻断但继续打包的部分授权选项。
- 不自动合并多个独立后端服务，也不替用户决定业务或架构取舍。

## 依据

- [CloudBase HTTP 云函数启动文件](https://docs.cloudbase.net/cloud-function/develop/scf-bootstrap)
- [CloudBase 运行环境支持](https://docs.cloudbase.net/cloud-function/runtime-support)
- [CloudBase CLI 云函数部署](https://docs.cloudbase.net/cli-v1/functions/deploy)
- [Skill 工作流与边界](SKILL.md)
- [交付协议](references/protocol.md)
- [平台依据与查证规则](references/platform-contract.md)
