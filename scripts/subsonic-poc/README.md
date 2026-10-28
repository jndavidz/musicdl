# Subsonic 门面 / DLNA 代理（已归档，冻结）

> 状态：**归档，不部署、不维护**（2026-10-28 用户裁决）。音流（Musiver）路径 C7 已被 Songloft 转正（P3）取代。
> 来源：`.state/` 一次性 POC 原样归档；运行日志与本机端口转发规则已清理。

## 文件

| 文件 | 作用 |
|---|---|
| `server.mjs` | 最小 Subsonic `/rest` 门面：ping/getLicense/getArtists/getAlbumList2/search3/getSong/stream/getCoverArt + 短期 ID（默认 10min）+ 320k 钳制 + 直链缓存 5min + Range 透传 + `u/p` 与 `token+salt` 鉴权 + `f=json` + 歌词接口声明 |
| `dlna-proxy.mjs` | 标准 UPnP MediaRenderer 描述 + AVTransport/RenderingControl SOAP 转发到 LX06。绕开设备描述不规范（`Content-Type: text/plain`、USN/UDN 不一致）导致音流丢弃设备；含「暂停后首次恢复」纠偏（无条件 Seek+Play + RelTime 校验 + 重试） |
| `virtual-renderer.mjs` | 对照组虚拟渲染器（证明音流本身发现逻辑正常，问题在 LX06 描述） |
| `ssdp-dump.mjs` / `ssdp-listen.mjs` / `ssdp-probe*.mjs` | SSDP 组播探测与监听（LX06 / 手机发现行为排查） |
| `dlna-seturi.xml` | `SetAVTransportURI` SOAP 报文样例 |

## 历史运行方式

```bash
node server.mjs        # :4533；env: KWQQ / SOURCES / ID_TTL_MS / URL_TTL_MS / POC_AUTH / POC_USER / POC_PASS
node dlna-proxy.mjs    # :4599；HOST/LX IP 硬编码在文件头
```

## 已知边界（不再修）

- 音流投送 URL 由手机自建媒体服务提供（手机即服务器），息屏/切网/杀进程影响播放——Songloft 路径同构，故不构成选型差异。
- 歌词：音流以空参调用 `getLyrics` 时已做兜底，但 App 仍显示"暂无"，用户裁决搁置。
- bilibili m4s 不纳入（需 remux）。
- POC 未经产品化，无鉴权硬化、无并发控制、无部署编排；仅供考古与恢复参照。
