# C3 kugou adapter lyric fallback 链

Status: claimed
Type: task

roadmap §2 C3：容器 /lyric 稳定 400（error_code 20010，NAS 环境事实）时 fallback 到库层/官方歌词端点。
方案：容器 /lyric 失败或空 → 酷狗官方歌词服务（lyrics.kugou.com search → krcs.kugou.com download，匿名、零 Cookie，与容器内实现同链路）。
恢复 test_smoke.py kugou lyric non-empty 断言（探测通过后）。

## Comments
