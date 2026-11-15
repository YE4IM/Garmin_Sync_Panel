# Changelog

## v0.1.1 - 2026-11-16

### 新增

- `AUTO_SYNC_STEPS` 环境变量：逗号分隔配置每日定时同步执行的步骤（`activity_init`、`activity_sync`、`health_sync`、`activity_export`、`weight_sync`），留空时执行全部步骤，行为与 v0.1.0 一致。

### 修复

- 小米体脂秤 FIT 文件不再写入 MetabolicAge 字段。Garmin 内部以毫秒存储该指标，第三方 FIT 上传后 UI 会把毫秒值按"年"渲染（如 24 岁显示为 `757366224000年`）；现在 Garmin 会直接隐藏该指标。

### 其他

- README 提供中英双语版本（`README.md` / `README.en.md`）。

## v0.1.0 - 2026-06-28

首个公开版本。

### 包含内容

- Garmin 运动和健康数据同步。
- 小米 / Mi Fitness 体重数据同步到 Garmin。
- 自托管 Web 面板。
- 默认本地用户名密码登录。
- 私有部署可切换到外部账号服务。
- 每日 Markdown、JSON、CSV 报告。
- SMTP 和 Microsoft Graph 邮件发送。
- 可选 AI 训练和健康分析。
- systemd 和 nginx 部署示例。
- 使用规则、账号风险、数据存储和数据传输说明。

### 适合的使用方式

- 个人服务器部署。
- 私有健康和运动数据整理。
- 每日邮件复盘。
- 给自己或小范围可信环境使用。

### 不包含

- 官方云服务。
- Docker / GHCR 镜像包。
- PyPI 包。
- 多用户 SaaS 权限模型。
- 第三方平台官方授权或合作承诺。

### 升级说明

这是首个公开版本，没有历史公开版本需要迁移。
