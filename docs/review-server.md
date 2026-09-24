# 给同事看的页面

服务器：`production-failure-analysis.usw2.i.etched.com`

**Daily tracker**（`dailyexcel.html`）还是今早那样的模块 / L10 / L11 表，不再往那一页加 SFT 报告。

**Daily FA**（`daily_FA.html`）才是今天的 failure analysis 页：上面是同一个选日子的月历，下面只有 L10 SFT 报告——测了多少台、失败多少台、失败 SN、yield、Download CSV、File Jira。

## 同事打开网页

公司网或 VPN 里：

- Daily FA：https://production-failure-analysis.i.etched.com/daily_FA.html
- Daily tracker：https://production-failure-analysis.i.etched.com/dailyexcel.html

nginx 把 80/443 转到本机 `127.0.0.1:8080`。安全组不开放 8787，不要把 `:8787` 发给同事。

- **Download CSV**：一天一行一个 SFT run（通过也写）。同一条 ESVM 只写一次 SN / attempt / final / 时间 / URL。没有 case id。开过票时，`jira` 列是该行所属 stage 的票链接。
- **File Jira**：按 L10_FLOW_TEST_COVERAGE 表 C 列（stage）分类，每个 stage 当天开一张 Bug。挂在 `JIRA_EPIC`（默认 ETCH-44407）下面。

## 服务器上的进程

仓库在 `/home/quan/factory_data_analysis`。systemd 用户服务 `factory-review.service` 监听 `127.0.0.1:8080`，登录退出也会继续跑（linger 已开）。

```sh
systemctl --user status factory-review.service
systemctl --user restart factory-review.service
```

这台机器到不了 pega4，**不要在服务器上拉 pega**。Daily FA 只读小的 `dailyfa.js`（日历 + SFT 报告）；Daily tracker 才读整份 `dailyexcel.js`。每天在能访问 pega 的电脑上重建，再拷上去：

```sh
python3 -m factory.cli dailyexcel
scp dashboard/data/dailyexcel.js dashboard/data/dailyfa.js \
  quan@production-failure-analysis.usw2.i.etched.com:factory_data_analysis/dashboard/data/
```

或 `make dailyexcel` 再 `make review-data`。拷完硬刷新 Daily FA 即可，不用重启服务。

开 Jira 需要在服务器 `.env` 里放 `JIRA_EMAIL` 和 `JIRA_API_TOKEN`。

本机只给自己看：

```sh
python3 -m factory.cli serve --port 8787
```

然后打开 http://127.0.0.1:8787/daily_FA.html 。
