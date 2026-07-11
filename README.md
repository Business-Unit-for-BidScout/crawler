# BidScout Crawler

BidScout 第一阶段爬虫项目。目标来源由 `Business-Unit-for-BidScout/requirements` 的 `knowledge/index/sources.yaml` 统一管理。

## 当前能力

- 从来源注册表读取地址；
- 按来源串行、低频、增量访问；
- 遇到 401、403、429、验证码、WAF 或明确拒绝立即停止该来源；
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
- 每日分散时间运行；
- 只对 `verified + monitoring.active=true` 来源定时采集；
- 手动运行可显式允许少量候选来源测试；
- 数据保存为 Actions artifact，同时将 `data/` 提交到 `data` 分支，避免污染 `main`。

仓库需要配置：

- `REQUIREMENTS_TOKEN`：只读访问私有 requirements 仓库；
- `OPENAI_API_KEY`（可选，不配置时使用 GitHub Models 和当前 workflow token）；
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选）
- `CRAWLER_USER_AGENT`（建议包含联系邮箱）

未配置独立 AI Secret 时，workflow 默认通过 GitHub Models 的 `openai/gpt-4o-mini` 完成 AI 分类；如果模型调用失败，才使用规则分类并在结果中记录回退原因。

## 本地验证

```bash
python -m pip install -e '.[test]'
pytest
python -m bidscout_crawler.cli --sources /path/to/requirements/knowledge/index/sources.yaml --allow-candidates --source-id example --max-sources 1 --max-items 2
```

## 合规边界

不绕过登录、验证码、会员、付费墙、robots 或访问控制；不使用代理池、账号轮换、指纹伪装或暴力枚举。候选来源只允许人工触发的小样本测试。
