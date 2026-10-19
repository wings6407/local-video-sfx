# 案例 01：投掷软团与落地散开

输入是最初上传的 **2.3 秒、960×720、30 fps** 方块角色投掷动画。成品使用本地程序合成，只有挥手破风、软团落地与少量颗粒散落。

| 动作层 | 起点 | 窗口长度 |
| --- | ---: | ---: |
| 出手破风 | 0.345 s | 0.360 s |
| 软团落地 | 1.366667 s | 0.270 s |
| 颗粒散落 | 1.390 s | 0.480 s |

- [原始输入视频](input.mp4)
- [画面接触表](inspection/contact.jpg)
- [可修改的声音计划及提示词](plan.json)
- [纯音效 WAV](output/projectile-throw.wav)
- [同步 MP4 预览](output/projectile-throw.mp4)
- [出手分轨](output/stems/throw.wav) · [落地分轨](output/stems/impact.wav) · [散落分轨](output/stems/scatter.wav)
- [校验结果](output/verification.json) · [测试报告](test-report.md)

## 重跑

在仓库根目录运行，选择一个新输出目录：

```bash
python scripts/video_sfx.py inspect examples/01-projectile-throw/input.mp4 --out working/first-inspection
python scripts/video_sfx.py render examples/01-projectile-throw/plan.json --out working/first-render --stems
python scripts/video_sfx.py verify working/first-render/manifest.json
python -m unittest discover -s tests -v
```

WAV 为 **48 kHz / PCM 24-bit / 立体声**，每声道 **110,400 帧**。动作间隔和末尾留白保持静音。分轨共用最终增益，可相加还原混音（仅有 PCM 量化误差）。

本例的自然语言提示词保存设计意图，不由程序合成器解析。自动测试验证技术属性和静音窗口，不代替试听对材质、风格及音量的判断。
