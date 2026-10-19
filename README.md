# Local Video SFX · 本地视频纯音效 Skill

为视频、GIF 和网页中的多段动画演示逐段制作动作音效。默认使用本地程序合成，也能导入本地音频素材；输出 **48 kHz / PCM 24-bit / 立体声 WAV** 和同步 **H.264/AAC MP4**。

适合游戏动作预览、投掷与落地、金属工具攻击、旋风、虹吸及变身效果。可按要求保持无音乐、无人声、无环境底声；静态间隔保持安静。

## 首例测试

[首例：投掷软团、落地散开](examples/01-projectile-throw/README.md) 附 **2.3 秒原始视频、声音计划、分轨 WAV、混音 WAV、同步 MP4 与校验结果**。

- [输入视频](examples/01-projectile-throw/input.mp4)
- [纯音效 WAV](examples/01-projectile-throw/output/projectile-throw.wav)
- [同步 MP4](examples/01-projectile-throw/output/projectile-throw.mp4)
- [测试记录](examples/01-projectile-throw/test-report.md)

本仓库的首例由 NumPy / SciPy 程序合成，没有使用在线生成服务或 AI 扩散模型。提示词用于保存设计意图或供后续本地模型使用，程序合成器本身不理解自然语言。

## 安装与调用

将仓库作为 `local-video-sfx` 文件夹放入 Codex 的 skills 目录，保持 `SKILL.md`、`scripts/` 与 `references/` 的相对路径。通过 `$local-video-sfx` 调用。

Python **3.10+**，安装依赖，并确保 `ffmpeg`、`ffprobe` 在 PATH：

```bash
python -m pip install -r requirements.txt
python scripts/video_sfx.py --help
```

如 FFmpeg 不在 PATH，可使用全局参数（在子命令前）：

```text
python scripts/video_sfx.py --ffmpeg FFMPEG_PATH --ffprobe FFPROBE_PATH inspect INPUT --out INSPECTION
```

## 快速使用

在用户选定的工作目录中保存输出。Windows 用户有 G 盘存储要求时，把输出、临时目录、虚拟环境和下载内容都放在 G 盘。

```bash
# 先生成接触表和实际播放时间，查看画面后再写计划
python scripts/video_sfx.py inspect examples/01-projectile-throw/input.mp4 --out working/inspect

# 运行首例；输出目录已有成品时，选择新目录或明确加 --overwrite
python scripts/video_sfx.py render examples/01-projectile-throw/plan.json --out working/demo --stems
python scripts/video_sfx.py verify working/demo/manifest.json

# 下载用户指定网页中直接链接的 GIF / 视频，不执行网页脚本
python scripts/video_sfx.py collect PAGE_URL --out working/references

# 为每段演示写一个 JSON 计划，独立输出并打包
python scripts/video_sfx.py batch PLAN_DIRECTORY --out working/delivery
```

计划格式与 GIF 最后一帧停顿的处理见 [plan-schema.md](references/plan-schema.md)。声音提示词与材质选择见 [prompting.md](references/prompting.md)。每段 `prompt_notes` 会保存在输出 manifest 中。

### 输出

| 文件 | 内容 |
| --- | --- |
| `ID.wav` | 48 kHz、24-bit、立体声纯音效 |
| `ID.mp4` | 原画面与新音轨的同步预览，30 fps |
| `stems/` | 可选的各事件分轨，共用混音增益 |
| `cue_sheet.csv` | 动作事件时间、类型、强弱、声像 |
| `manifest.json` | 处理方式、输入校验值、计划与提示词 |
| `verification.json` | 格式、时长、削波与静音区间检查 |
| `index.json` / `delivery.zip` | 批量模式的逐段索引和交付包 |

工具按媒体实际播放时长生成 WAV；30 fps 预览只在尾部补齐不到一帧。自动检查不代替声音内容试听，不会把程序合成标成 AI 生成。导入本地 AI 素材时可使用 `sample` 事件；本工具不上传素材，也不自动下载模型。

## 测试

```bash
python -m unittest discover -s tests -v
```

17 项测试调用真实 CLI 与 FFmpeg，覆盖首例音轨格式、静音区间、声像、重复生成、分轨还原、GIF 尾帧停顿与 10 ms 帧延迟、奇数画幅、非法输入、覆盖保护、源音轨排除、网页收集及逐段批量打包。[Skill 行为实测](tests/skill-evaluation.md)另记录了独立执行和 GIF 时钟转换。GitHub Actions 在 push / pull request 时运行相同测试。

代码采用 [MIT License](LICENSE)。示例视频用于本仓库的流程演示与回归测试。
