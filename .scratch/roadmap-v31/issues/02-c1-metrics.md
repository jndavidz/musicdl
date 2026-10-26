# C1 /metrics Prometheus 端点

Status: claimed
Type: task

roadmap §2 C1：prometheus-client 暴露 /metrics（parsers 健康度、缓存 hit_rate、请求延迟直方图、请求计数）。
验收「Grafana 看到数据」——端点输出合法 exposition 格式 + README 补 scrape 配置说明；Grafana 侧验证留 NAS 批次。

约束：per-app 独立 CollectorRegistry（离线冒烟会在同进程起多个 app）；
/metrics 走原生文本响应不走 envelope；label 用 route 模板防基数爆炸。

## Comments
