# musicdl-webgui

易用的 musicdl Web 下载界面（参考原作者 `examples/musicdlgui` PyQt5 版重新设计）。

## 功能特性

| 需求 | 实现 |
|------|------|
| 选择平台 | 18 个平台分四组：kwqq-API 六源 / 自有直连 / 聚合网关 / 扩展平台 |
| 平台搜索结果数量 | 每个平台 chip 独立步进器（1–30），点击平台名启用/停用 |
| 下载目录固定一个 | 所有平台的文件统一落盘到 `download_dir`，**无任何平台子目录、无 pkl** |
| 文件命名易读 | 默认 `{artist} - {title} - {album}.ext`，缺失要素自动省略，重名自动 `(1)` |
| 音质级别 | 无损优先 / 仅无损 / 320k / 128k / 不限；跨平台同曲按偏好自动择优 |
| 单曲单文件 | 歌词 + 封面 + 标题/歌手/专辑标签全部嵌入音频文件（默认不生成 .lrc 外挂） |

其他：SSE 实时进度（百分比/速度）、失败单条重试、整批取消、命名模板自定义、设置持久化。

## 快速开始

```bash
cd /mnt/d/repos/musicdl
uv run python examples/musicdlwebgui/app.py            # 默认 http://127.0.0.1:3004
```

常用参数：

```bash
--host 0.0.0.0 --port 3004          # 局域网访问（建议同时配置 api_key）
--download-dir /mnt/d/MusicDL       # 覆盖并持久化下载目录
```

依赖已包含在仓库根 requirements（fastapi/uvicorn）；musicdl 本体以 editable 安装即可。

## 混合架构：kwqq-API 六源 + 进程内库

自 `api-server` 分支的 kw-qq-music-api（`docs/API-REFERENCE.md`）上线后，webgui 采用双后端：

| 分组 | 平台 | 后端 | 特点 |
|------|------|------|------|
| kwqq-API 六源（自有账户态） | 酷我/QQ/千千/咪咕/**网易云·自有/酷狗·自有** | NAS `kwqq_api_base` 服务 | 元数据搜索(~0.3s) + 按 id 二段解析；网易走 MUSIC_U、酷狗走容器背书，可出**账户态无损**；带熔断与缓存 |
| 直连匿名链 | 网易云·直连 / 酷狗·直连 | 进程内 musicdl 库匿名链 | 不依赖 NAS，自有版离线时的备份路径 |
| 聚合网关 | TuneHub / GDStudio | 进程内库 | root_source 标注真实上游 |
| 扩展平台 | B站/汽水/歌曲宝/音乐岛/小白/MyFreeMP3/JBSou/MP3Juice | 进程内库 | 稳定性不一 |

工作方式：

1. API 组搜索只取元数据（质量徽章显示「待解析」，ext/大小在下载时才确定）；
2. 下载时二段式 `GET /{source}/song/url?id=&quality=` 出链 → 交给通用下载器落盘，
   标签/歌词(`/{source}/lyric`)/封面(`/{source}/song/info`)嵌入逻辑与库源完全一致；
3. 音质偏好映射：无损优先/仅无损→`flac`、320k→`320k`、128k→`128k`、不限→`auto`；
   NAS 端 `ENABLE_LOSSLESS=false`(默认) 时 flac/hires 返回 403 → 自动回退 auto 并在队列标注；
4. API 连通状态在平台区「● 在线/○ 离线」实时展示；离线时六源搜索失败，可改勾自有组。

配置（`config.json`）：`"kwqq_api_base": "http://10.10.10.2:3003"`、`"kwqq_api_key": ""`
（外网访问才需要 key，内网免）。

## 音质映射总表（调查实证后的最终落地）

### webgui 音质偏好 → 各后端实际请求

| webgui 偏好 | kuwo(API) | netease(API·自有) | kugou(API) | migu(API) | qq/qianqian(API) | 直连/聚合源 |
|------------|-----------|-------------------|------------|-----------|------------------|------------|
| 母带优先 | `20000kflac` | jymaster→dolby→sky→jyeffect→hires 尝试链 | `high`(54.9MB级) | SQ/ZQ | HR/3000 | 内置恒为最高档序 |
| 无损优先 | `2000kflac` | lossless | `flac` | SQ | SQ/3000 | 同上 |
| 仅无损 | 同无损优先，交付非FLAC即跳过 | 同左 | — | — | — | 同上 |
| 320k / 128k | 对应码率档 | standard/exhigh | 320/128 | HQ/PQ | 320/128 | 同上 |
| 不限 | auto | exhigh(320k) | 320(=auto) | HQ | 320 | 同上 |

### 库直连源内置档序（已全部是"最高→最低"，无需配置）

| 直连源 | 解析档序（从高到低） |
|--------|--------------------|
| 网易云·直连 | `jymaster → jyeffect → sky → hires → lossless → dolby → exhigh → standard`（八级 Eapi，实测峰值 37.8 MB/min 准母带）|
| 酷狗·直连 | 第三方 API 组：`viper_tape/viper_clear/viper_atmos/flac/high/320/128` 与 `hires/lossless/exhigh`（蝰蛇系上游未交付可用文件，实测上限 CD 7.3）|
| 酷我·直连 | nmobi `master/atmos_plus/atmos/flac` + 2000kflac/20000kflac 系（匿名上限 CD 12.5）|
| QQ·直连(l1组) | vkeys `[7,9,10,8,6,5]` · xingmian `flac24bit/hires/flac/320k` · xcvts/lxmusic `[999…]`（HR 实测 40.8）|
| TuneHub | parse API `flac24bit→flac→320k→128k`(kuwo/qq) + meting `400/380/320/128`(netease) |
| GDStudio | br=`999/740/320/192/128` |
| 千千/咪咕/小站群 | 3000 / SQ-ZQ / flac-wav 直链（CD 上限）|

> 说明：webgui 的音质偏好下拉**仅对 kwqq-API 六源生效**（下发 quality 参数）；直连与聚合源
> 由 musicdl 库固定按最高→最低档序解析，偏好只影响结果排序与择优。

### 实测能力矩阵 v3（2026-08，邓丽君/周杰伦/周深多曲采样）

| 渠道 | 请求的最高档 | 实测交付上限 (MB/min) | 高解析(17-42) | 母带(≥42) |
|------|------------|---------------------|:---:|:---:|
| **网易云·直连** (库内置公共 MUSIC_U) | 库八级档 jymaster→standard | **37.8**（《晴天》175.8MB flac）| ✓ 准母带 | ✗ 未命中 |
| QQ 音乐 (l1 SVIP 解析器组) | HR Hi-Res | **40.8**（《又见炊烟》104MB）| ✓ 贴母带线 | ✗ 差一线 |
| 网易云·自有 (88VIP 黑胶, ncm-api) | jymaster→hires 尝试链 + 灰色解灰(match→酷我镜像) | **jyeffect 21.4** / 灰色曲目解灰 flac 视镜像 | ✓ | ✗ 需SVIP |
| 酷我 (API 匿名) | 20000kflac 臻品母带 | ~12.5（CD 级，匿名被降级）| ✗ | ✗ 需VIP Cookie |
| 酷狗·自有 (概念版VIP) | quality=**high**（真发）| flac ~11.8（CD 上限级）；部分回退 128k 如实标注 | ✗ | ✗ viper_tape 需转码未实现 |
| **酷狗·直连** (库第三方API含蝰蛇档) | viper_tape/viper_clear/flac | flac 7.3（蝰蛇系上游未交付可用文件）| ✗ | ✗ |
| 千千 | rate=3000 | flac 12.3（CD 级）| ✗ | ✗ |
| 咪咕 | SQ/ZQ flag | 实际交付 mp3 HQ（标注与实物不符）| ✗ | ✗ |
| TuneHub | flac24bit 仅限 kuwo/qq parse API；netease 子源走 meting ≤400kbps | kuwo 子源 ~12.5；qq parse 服务常无响应 | ✗ | ✗ |
| GDStudio | br=999 压缩封顶 | 同曲直连 36-41 被压至 ≤19 | 边缘 | ✗ 设计性压缩 |
| 小站群 LIVEPOO/TWOT58/GEQUHAI/MITU/JCPOO/FLMP3 | flac/wav 直链 | 6–10（CD 级）| ✗ | ✗ |

要点：
- **严格母带(≥42) 当前全渠道未实测命中**，但「网易云·直连」37.8 与「QQ HR」40.8 已是
  准母带级（24bit 转制规格）。分级体系按实测体积如实标注，不信任上游档名。
- 高解析的两个稳定来源：网易·自有(88VIP 在架曲目, 18-22) 与 QQ HR(38-40.8)。
- 聚合网关(TuneHub/GDStudio)存在压缩陷阱：同曲直连 36-41 的源经它们只有 ≤19。
- 库内置公共 cookie 权益可能随上游变动 —— 「直连」通道规格以实际 resolve 为准。

## 下载目录指向群晖（/volume1/music/download）

`config.json` 默认 `download_dir=/volume1/music/download`。WSL2 需先把群晖同路径挂载进来
（挂载点与 NAS 路径一致，配置两端通用）：

```bash
# 前置: DSM 控制面板 → 共享文件夹 → music → 编辑 → NFS 权限 → 新增:
#   网段 10.10.10.0/24 · 可读写 · Squash 无映射 · 允许子文件夹装载
sudo bash examples/musicdlwebgui/scripts/mount-nas-music.sh        # NFS(推荐,免凭证)
sudo bash examples/musicdlwebgui/scripts/mount-nas-music.sh --smb  # 或 SMB 回退
```

脚本会写 `/etc/fstab` + systemd automount（断网不阻塞启动、空闲自动卸载），并以运行用户验证
`download/` 可写。

## 配置

首启自动生成 `examples/musicdlwebgui/config.json`（可用环境变量 `MUSICDL_WEBGUI_CONFIG` 改位置）：

```jsonc
{
  "download_dir": "/mnt/d/MusicDL-Downloads",   // 固定下载目录
  "naming_template": "{artist} - {title} - {album}",
  "quality_pref_default": "lossless_first",     // lossless_first|lossless_only|320k|128k|any
  "dedupe_default": true,                       // 跨平台同曲择优去重
  "save_lrc_sidecar": false,                    // true 时额外保存 .lrc 文件
  "concurrency": 3,                             // 同时下载并发数(重启生效)
  "search_timeout_s": 45,                       // 单次搜索总超时
  "max_limit_per_source": 30,
  "api_key": "",                                // 非空时所有请求需 x-api-key 或 Basic Auth
  "platform_defaults": {"qq": 5, "netease": 5}
}
```

## API 一览

| Method | Path | 说明 |
|--------|------|------|
| GET  | `/api/config` · PUT `/api/config` | 读取/更新配置 |
| POST | `/api/search` | `{keyword, sources: {"qq": 5}}` → 合并结果（含质量档位/大小/时长/来源） |
| POST | `/api/downloads` | `{keys, quality_pref, dedupe}` → 创建下载任务 |
| GET  | `/api/tasks` · `/api/tasks/{id}` | 任务列表/快照 |
| GET  | `/api/tasks/{id}/events` | SSE 实时进度流 |
| POST | `/api/tasks/{id}/retry` · DELETE `/api/tasks/{id}` | 单条重试 / 整批取消 |
| GET  | `/healthz` | 存活探针 |

## 设计说明（零改动 musicdl 库）

- **统一目录**：`search(persist_results=False)` 跳过库默认的 `<平台>/<时间 关键词>` 目录与 pkl；
  下载前覆写 `SongInfo.work_dir/_save_path` 指向固定目录。
- **单曲单文件**：patch `SongInfoUtils.savelrctofile`，歌词仅走 `embedlyrics` 嵌入
  （MP3-USLT / FLAC-LYRICS / M4A-©lyr）；封面经 `embedcover` 嵌入；基础标签经 `embedbasictags` 写入。
- **进度**：`ProgressStub` 以 duck-typing 替代 rich.Progress（覆盖 `_download` 与 HLS 分支的接口），
  回调写入内存任务状态，SSE 每 600ms 推快照。
- **音质档位**：按扩展名 + 大小/时长估算码率分级 hires/lossless/320k/128k/low/other，
  用于结果徽章、"仅看无损"过滤与同曲择优。

## 冒烟测试

```bash
XDG_STATE_HOME=$PWD/.state uv run python examples/musicdlwebgui/tests/test_smoke.py http://127.0.0.1:3004 尾戒
```

校验：搜索返回结构 → 创建任务 → SSE 进度收敛 → 文件位于 download_dir 根目录（无子目录/pkl/.lrc）→
文件名符合三要素模板。
