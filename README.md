# BidScout Crawler

BidScout 第一阶段爬虫项目。目标来源由 `Business-Unit-for-BidScout/requirements` 的 `knowledge/index/sources.yaml` 统一管理。

公开报告：<https://bidscout.futurescience.technology/>

每日报告：<https://bidscout.futurescience.technology/daily/index.html>

## 每日招采报告与企业微信

参考节能行业监测项目，`daily-report.yml` 每天北京时间 **09:00** 生成并发布
**前一自然日 00:00 至次日 00:00** 的招采日报，然后发送到现有
`WECOM_WEBHOOK_URL` 对应的企业微信群。GitHub 定时任务可能延迟。
日报独立于现有 14:00、19:00 的分时摘要；日报即使没有新增信息也会发送。

- 统计口径为 `first_seen_at`（首次采集时间），不把历史公告当作当天发布。
- 展示新增总数、招采相关数、分类分布、来源数、人工复核数及公告原文入口。
- 完整报告和历史归档位于 `daily/YYYY-MM-DD.html` 与 `daily/index.html`；
  同日期 JSON 只包含日报所需的公开字段，不包含数据库、原始路径或内部诊断。
- 企业微信只发送精简日报和日期报告链接，消息限制在 4096 UTF-8 字节内。
- 先发布 Pages，再核验对应 HTML/JSON 可访问，最后发送企业微信。
- 数据取自现有 `data` 分支，无需来源清单凭据或运行新一轮爬取。
  报告显示数据快照的实际更新时间；快照过期、时间未知或最近采集无来源时明确提示覆盖不足，
  不将零新增解释为当天没有招采公告。历史日期根据当前累计归档回溯。
- 每个机器人、每个报告日期只发送一次。`notification-state` 分支保存日期、发送状态和哈希，
  不保存 Webhook、机器人密钥或消息原文。发送前先记录 `sending`；网络结果不确定时保留该状态，
  后续运行停止重发，需人工核对群消息和记录。明确拒绝时记录 `rejected`，修正配置后可重试。

手动运行 Actions → **Publish and send BidScout daily report**：默认只发布日报；
勾选 `send_wecom` 后发送前一日的日报，重复运行会跳过已经成功发送的日期。
现有 `WECOM_WEBHOOK_URL` Secret 可直接复用，不需要将密钥写入仓库或本地文件。

离线构建与消息预览：

```bash
python -m bidscout_crawler.report --input data --output site --snapshot-updated-at "2026-10-15T00:00:00Z"
python -m bidscout_crawler.notify_daily --public-dir site --dry-run
```

`--snapshot-updated-at` 应填写数据分支提交时间，而非当前时间。缺省时读取
`last-run.json` 的 `completed_at`；旧快照没有此字段时显示更新时间未知。
可以用 `--daily-date YYYY-MM-DD` 构建截至指定完整自然日的历史报告，用
`notify_daily --date YYYY-MM-DD --dry-run` 预览对应摘要。

**2026-10-15 接入检查：** `data` 分支最近一次更新为 2026-08-23；
最近云端采集在读取私有 requirements 仓库时报告 `Bad credentials`，
来源清单中 `verified + monitoring.active=true` 的来源数为 0。
需要恢复 `REQUIREMENTS_TOKEN` 的读取权限，并审核启用实际来源，才能持续产生新的采集数据。
日报会继续如实呈现数据覆盖情况。

## 当前能力

- 从来源注册表读取地址；
- 按来源串行、低频、增量访问；
- 当前实现遇到 401、403、429、验证码、WAF 或明确拒绝时立即停止该来源的本次任务；
- 保存原始响应、抽取正文、SQLite 数据库和 JSONL；
- 不做业务筛选，所有发现内容分类为：
  - `procurement_notice`
  - `award_or_result_notice`
  - `procurement_change_notice`
  - `contract_notice`
  - `other_procurement_related`
  - `not_procurement`
  - `uncertain`
- 配置 `OPENAI_API_KEY` 时优先使用 OpenAI 兼容 API 分类；未配置或调用失败时使用确定性规则，保留处理方法。

## GitHub Actions

`crawl.yml` 支持：

- `workflow_dispatch` 手动运行；
- 每天北京时间 `14:00` 和 `19:00` 启动采集并更新 `data` 分支；
- 采集完成后立即计算对应时段新增数，新增数为 `0` 时不创建通知工作流；
- `14:00` 批次发送“前一晚 `19:00` 至当天 `12:00`”新增信息；
- `19:00` 批次发送“当天 `12:00` 至 `19:00`”新增信息；
- 推送内容包含数据窗口、来源和公告原文链接；Webhook 仅通过仓库 Secret `WECOM_WEBHOOK_URL` 注入；
- 只对 `verified + monitoring.active=true` 来源定时采集；
- 手动运行可显式允许少量候选来源测试；
- 数据保存为 Actions artifact，同时将 `data/` 提交到 `data` 分支，避免污染 `main`。

## GitHub Pages 报告

`pages.yml` 将成功爬取产生的 Artifact 转换为公开的只读静态报告：

- 显示采集摘要、分类数量、来源运行状态；
- 支持按分类、来源、复核状态筛选及全文搜索；
- 展示 AI 判断理由、支持引文、正文摘录和原始公告链接；
- 不发布 SQLite、原始二进制响应、Cookie、Secret 或请求头；
- 可手动输入历史 crawl run ID 重新发布，默认使用最新成功的手动爬取结果；
- 后续每次成功爬取都会自动刷新 Pages；若某次没有可展示文档，发布流程会保留当前有效页面，避免被空报告覆盖。

本地生成：

```bash
python -m bidscout_crawler.report --input /path/to/crawl-data --output site --run-id 29156878256
```

仓库需要配置：

- `REQUIREMENTS_TOKEN`：只读访问私有 requirements 仓库；
- `OPENAI_API_KEY`（可选，不配置时使用 `REQUIREMENTS_TOKEN` 调用 GitHub Models）；若 GitHub Models 在官方退休 brownout 期间返回 HTTP 410，工作流会明确告警并继续使用可审计的规则分类，不将其误报为 AI 分类。
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选）
- `CRAWLER_USER_AGENT`（建议包含联系邮箱）
- `WECOM_WEBHOOK_URL`：企业微信群机器人 Webhook，只存于 GitHub Actions Secret，不写入代码或日志

未配置独立 AI Secret 时，workflow 默认通过 GitHub Models 的 `openai/gpt-4o-mini` 完成 AI 分类；`REQUIREMENTS_TOKEN` 因而还需要具有 GitHub Models 读取权限。如果模型调用失败，才使用规则分类并在结果中记录回退原因。

## 出口配置现状

产品基线允许使用免费或低价代理、商业代理、自建出口、VPN、Cloudflare WARP、代理池和动态 IP，以隐藏办公室固定 IP、改善区域可达性、隔离故障或分散出口负载。

当前爬虫尚未内置代理发现、代理池调度或出口审计；`httpx` 会按其默认行为读取运行环境中的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 和 `NO_PROXY`，因此目前只能由运行环境提供单一代理出口。后续出口管理必须显式配置并记录出口配置版本，且在所有出口之间共享来源级请求预算、`Retry-After`、暂停和熔断状态。要求受保护出口的任务在代理失败时必须停止，不得回退办公室直连。

## 本地验证

```bash
python -m pip install -e '.[test]'
pytest
python -m bidscout_crawler.cli --sources /path/to/requirements/knowledge/index/sources.yaml --allow-candidates --source-id example --max-sources 1 --max-items 2
```

## 陕西企业政策日报推送

独立的 [shaanxi-policy-monitor](https://github.com/Business-Unit-for-Enterprise-Service/shaanxi-policy-monitor) 负责陕西省、西安市企业政策采集和网页发布。本仓库的 `policy-daily.yml` 只读取其当天已发布的日报，复用现有 `WECOM_WEBHOOK_URL` 发送政策简报。

计划北京时间每天 09:05 发送，10:05、11:05 检查漏发；GitHub 定时任务可能延迟。前两次若当日报告尚未发布则等待下一次，最后一次仍缺失会明确失败。手动运行 `Send Shaanxi policy daily report` 也可补发当天报告。不会发送前一天的陈旧快照。

政策日报采用 `notification-state` 分支下独立的 `wecom-shaanxi-policy` 发送记录，与招采日报互不冲突；已确认发送的日期不重复发送。网络超时后若无法确认企业微信是否收到，会保留 `sending` 状态并阻止自动重发，需要核对群消息与记录后处理。

## 合规边界

不破解或绕过登录、验证码、会员、付费墙、robots 或访问控制，不使用账号轮换、指纹伪装或暴力枚举。代理池和 IP 轮换可以用于出口隐私、区域可达性、节点健康切换和负载分散，但不得由目标站点的拒绝、限流、验证码或 WAF 信号触发立即换 IP 继续请求，也不得清零来源状态或增加总请求量。

未知或公开代理只允许在隔离环境中承载无凭据、无 Cookie、无敏感参数的公开页面 GET 请求，必须保持 TLS 校验并检查异常响应。候选来源只允许人工触发的小样本测试。
