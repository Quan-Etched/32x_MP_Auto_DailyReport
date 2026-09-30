# 给同事看的页面

服务器：`production-failure-analysis.usw2.i.etched.com`

**Daily tracker**（`dailyexcel.html`）还是模块 / L10 / L11 表，不再往那一页加 FA 报告。

**Daily FA**（`daily_FA.html`）才是 failure analysis 页：上面是同一个选日子的月历，下面是 L10 FAT、L10 SFT、L10 RIN 三张报告——测了多少台、失败 SN、yield，以及失败表（DUT SN / error type / test case / 测试时间 / error code / pega URL / File Jira）。点某一行的 Jira 才开单，开过之后那一行不能再点。

## 同事打开网页

公司网或 VPN 里：

- Daily FA：https://production-failure-analysis.i.etched.com/daily_FA.html
- Daily tracker：https://production-failure-analysis.i.etched.com/dailyexcel.html

nginx 把 80/443 转到本机 `127.0.0.1:8080`。安全组不开放 8787，不要把 `:8787` 发给同事。

- **Download CSV**：失败表的一份拷贝。一失败一行。
- **File Jira**：只开该行那台 DUT、那个 test case 的 Bug。挂在 `JIRA_EPIC`（默认 ETCH-44407）下面。

## 服务器上的进程

仓库在 `/home/quan/factory_data_analysis`。systemd 用户服务 `factory-review.service` 监听 `127.0.0.1:8080`，登录退出也会继续跑（linger 已开）。

```sh
systemctl --user status factory-review.service
systemctl --user restart factory-review.service
```

这台机器到不了 pega4，**不要在服务器上拉 pega**。Daily FA 只读小的 `dailyfa.js`（日历 + FAT/SFT/RIN 报告）；Daily tracker 才读整份 `dailyexcel.js`。每天在能访问 pega 的电脑上重建，再拷上去。

重建时，每条失败的 L10 run 会把 `log.jsonl` 下载到本机 `data/raw/pega-logs/`（同一条测试有多条 diagnosis 时，全部 `TH-` error code 都写进行里）。已经下过的 run 下次直接读本地缓存。拷上去的是带这些 code 的 `dailyfa.js`，不是日志原文：

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
