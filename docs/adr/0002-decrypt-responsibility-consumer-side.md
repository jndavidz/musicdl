# ADR-0002: master/surround51 加密档解密责任在消费方

日期：2026-10-26 ｜ 状态：Accepted

## Context

酷我 zhenpin master（20900kmflac，192k/24bit）与 surround51（20501kmflac）档位返回**加密 mflac/mgg + ekey**（`server/adapters/kuwo.py` 契约注释）。消费方须用 `scripts/kuwo_qmc_decryptor.py` 解密得明文 flac/ogg。webgui 下载钩子已实现端到端解密并按实测定档。

关键消费方能力事实：**MusicFree 插件只消费 ≤320k mp3**——加密无损档的现实唯一消费方是 webgui。

## Decision

**维持"server 出件（加密件+ekey）、消费方解密"分工**。server 不做服务端解密、不提供解密代理流。

**补行（2026-10-27 定案，音乐生态计划 V3.1）**：**保真层只消费本地文件，API 不入播放链**——无损/高解析档的现实入口只有 webgui 下载入库（解密后落本地曲库），由 Lyrion/Hi-Fi 链从本地文件播放；API 直链（无论明文还是加密件+ekey）永不进入任何播放类消费链，播放类消费方只吃 ≤320k mp3。

## 拒绝记录

- **服务端解密（返回明文直链或代理流）**：收益对象是插件生态，但 MusicFree 只需 ≤320k mp3（原生支持，无需解密）；而 NAS（DS416play，弱机）承担大文件解密代理流的 CPU/内存/带宽是真实压力。若未来出现需要明文档的新消费方，重新打开本 ADR。

## Consequences

- webgui 必须保留 QMC 解密钩子与 `scripts/kuwo_qmc_decryptor.py`——这是无损能力的一部分，不随库通道冻结而废弃。
- API 响应的 `ekey` 字段是对外契约的一部分，不得移除。
