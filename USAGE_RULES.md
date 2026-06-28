# 使用规则与数据说明

这份说明写给部署者和使用者。项目本身只是一个自托管工具，不提供云服务，也不代替 Garmin、小米、Microsoft 或其他账号服务的官方客户端。

## 使用规则

1. 只登录本人拥有或已经获得明确授权的 Garmin、小米 / Mi Fitness、邮箱和账号服务。
2. 不要把这个服务开放成公共网站。默认定位是个人或小范围私有部署。
3. 不要把账号密码、OAuth Token、短信验证码、邮箱授权码交给不可信的人或服务。
4. 不要用它绕过第三方平台的访问限制、风控、付费限制、地区限制或账号规则。
5. 如果用于多人、团队、商业、医疗、保险、雇佣管理或类似场景，应先做隐私、合规和第三方条款审查。
6. 运动和健康数据可能不完整或不准确，不应作为医疗诊断、治疗建议或安全关键决策依据。

第三方条款可能会更新。使用前建议阅读相关官方条款和隐私政策：

- Garmin Terms of Use: https://www.garmin.com/en-US/legal/terms-of-use/
- Garmin Connect Privacy Policy: https://www.garmin.com/en-US/privacy/connect/policy/
- Xiaomi Privacy: https://privacy.mi.com/all/en_GB/
- Xiaomi Account Privacy: https://privacy.mi.com/globalmiaccount/en_US/
- Microsoft APIs Terms of Use: https://learn.microsoft.com/en-us/legal/microsoft-apis/terms-of-use
- Microsoft Graph overview: https://learn.microsoft.com/en-us/graph/overview

## 账号风险说明

本项目需要登录 Garmin 和小米账号，还可能调用 Microsoft Graph 或 SMTP 发送邮件。使用时可能遇到：

- 第三方平台要求验证码、二次验证或重新登录
- 第三方平台限制自动化访问、调整接口、触发风控或暂时锁定账号
- Token 过期、撤销、地区差异、接口不可用
- 邮箱服务拒绝 SMTP 密码登录，或要求 OAuth / 应用密码
- 第三方条款变化导致某些自动化方式不再适合继续使用

这些风险来自第三方平台规则和账号安全策略，不由本项目控制。部署者需要自行判断是否继续使用、是否降低同步频率、是否停用某个集成。

## 本项目会保存什么

默认情况下，数据保存在本机文件系统，不会上传到本项目自己的云端。

常见位置如下：

| 路径 | 内容 | 是否应提交到 Git |
| --- | --- | --- |
| `.env` | 服务配置、登录方式、邮件配置、API Key、客户端密钥 | 否 |
| `runtime/` | 日报、运行状态、AI 缓存、邮件状态、Microsoft Graph Token | 否 |
| `garmin-activity-sync/config.json` | Garmin 账号配置 | 否 |
| `garmin-activity-sync/data/` | SQLite 数据库、FIT 文件、导出数据、Garmin session | 否 |
| `garmin-activity-sync/logs/` | Garmin 同步日志 | 否 |
| `garmin-weight-sync/users.json` | 小米和 Garmin 账号配置、登录 Token | 否 |
| `garmin-weight-sync/config/` | Docker 或私有部署配置 | 否 |
| `garmin-weight-sync/data/` | 体重记录、FIT 文件、session、日志 | 否 |

公开仓库只应包含源码、示例配置、文档和测试。

## 会发生哪些数据传输

根据启用的功能，可能有这些传输：

1. Garmin 同步
   - 服务会向 Garmin Connect 登录或恢复 session。
   - 服务会读取运动、健康、睡眠、心率、HRV、体重等数据。
   - 体重同步功能可能会把小米体重数据生成 FIT 文件后上传到 Garmin Connect。

2. 小米 / Mi Fitness 同步
   - 服务会向小米账号或健康相关接口登录。
   - 服务会读取体重和体脂秤相关数据。
   - 登录 Token 会保存在本机配置或数据目录中。

3. 邮件发送
   - SMTP 模式会把日报发送到 `.env` 里配置的收件邮箱。
   - Microsoft Graph 模式会调用 Microsoft Graph `sendMail` 发送日报。
   - 日报附件可能包含运动、健康、睡眠、心率、体重和个人备注。

4. AI 分析，可选
   - 只有配置 `MIMO_API_KEY` 后才会调用外部 AI 接口。
   - 发送内容可能包括汇总后的运动、健康、体重、个人背景和临时提示词。
   - 不想把这些内容发给外部 AI 服务时，保持 `MIMO_API_KEY` 为空。

5. 外部登录服务，可选
   - 公开版本默认使用本地登录。
   - 私有部署如果设置 `AUTH_PROVIDER=wxylab`，登录请求会发送到配置的 WXY LAB Account V1 服务。

## 是否有项目自己的云端

没有。

这个项目不提供官方云端、不收集遥测、不把数据上传到作者服务器。所有持久化默认在部署机器本地。

但启用第三方功能时，数据会进入对应的第三方服务，例如 Garmin、小米、Microsoft 邮箱服务、SMTP 服务或配置的 AI 服务。这些服务的数据处理方式以各自条款和隐私政策为准。

## 清理数据

停止服务后，可以按需删除这些本地数据：

```bash
rm -rf runtime/
rm -rf garmin-activity-sync/data/
rm -rf garmin-activity-sync/logs/
rm -f garmin-activity-sync/config.json
rm -f garmin-weight-sync/users.json
rm -rf garmin-weight-sync/config/
rm -rf garmin-weight-sync/data/
```

删除前确认是否还需要历史报告、数据库或登录状态。删除后通常需要重新登录 Garmin、小米或 Microsoft。

## 发布和再分发

再分发代码时：

- 保留 `LICENSE` 和 `NOTICE.md`
- 不附带真实账号、密码、Token、数据库、FIT 文件、日志或日报
- 不使用 Garmin、小米、Microsoft 或其他第三方名称暗示官方授权或合作
- 如果面向他人提供服务，先补充自己的隐私政策、服务条款、删除数据流程和联系方式

本说明不是法律意见。不同地区、用途和组织要求可能不同，需要时应咨询专业人员。
