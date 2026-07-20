# BidScout Crawler

BidScout 第一阶段爬虫项目。目标来源由 `Business-Unit-for-BidScout/requirements` 的 `knowledge/index/sources.yaml` 统一管理。

公开报告：<https://bidscout.futurescience.technology/>

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
- 每天北京时间 `11:30` 和 `18:15` 先完成采集并更新 `data` 分支；
- 每天北京时间 `14:00` 发送“前一晚 `19:00` 至当天 `12:00`”新增信息；
- 每天北京时间 `19:00` 发送“当天 `12:00` 至 `19:00`”新增信息；
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
- `OPENAI_API_KEY`（可选，不配置时使用 `REQUIREMENTS_TOKEN` 调用 GitHub Models）；
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

## 合规边界

不破解或绕过登录、验证码、会员、付费墙、robots 或访问控制，不使用账号轮换、指纹伪装或暴力枚举。代理池和 IP 轮换可以用于出口隐私、区域可达性、节点健康切换和负载分散，但不得由目标站点的拒绝、限流、验证码或 WAF 信号触发立即换 IP 继续请求，也不得清零来源状态或增加总请求量。

未知或公开代理只允许在隔离环境中承载无凭据、无 Cookie、无敏感参数的公开页面 GET 请求，必须保持 TLS 校验并检查异常响应。候选来源只允许人工触发的小样本测试。
