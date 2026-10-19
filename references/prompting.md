# 动作音效提示词与声音选择

先定位画面动作，再写声音。拆开运动声、接触声和余音通常比把整段复杂动作放进一个提示词更容易同步。使用本地模型时，可把生成的短音效剪入 `sample` 事件；程序合成参数不解析自然语言提示词。

| 画面 | English prompt example | 本地声源与处理 |
| --- | --- | --- |
| 投掷软团 | A small soft lump thrown with one compact whoosh, then a blunt sticky splat and a few short granular taps. Isolated dry Foley, silent gaps. | `whoosh` + `mud` + `scatter`，三段分开对齐 |
| 金属拍击 | A thin metal spatula swings down and smacks a hard floor with a short bright metallic slap and a low blunt impact. Tiny grit quickly settles. | `impact/metal` + `impact/body`，少量 `scatter` |
| 叶片前冲 | A small fan spins up rapidly and drives forward with chopping blade turbulence, then quickly spins down. Close mechanical action Foley. | `rotor`，辅以短 `whoosh`；只覆盖动作持续时间 |
| 马桶虹吸 | A toilet activates a strong liquid siphon, then small wet bubbles and brief ceramic seat contacts follow the visible seated struggling action. | `suction` + `bubble` + `impact/ceramic`，避免全段底噪 |
| 变身成形 | A character spins, two compact smoke poofs burst, then a steel tool forms with one short inharmonic metallic clink. Dry isolated sound effects. | 两次短 `whoosh`，按最终物体增加短材质声 |

负面提示词示例：

```text
music, melody, musical instruments, singing, speech, voice, narration,
environmental ambience, continuous background noise, crowd, traffic,
birds, long reverb, echo
```

负面提示词降低不需要的内容出现概率，不能代替试听。无环境底声时，静态展示和动作间空隙应安静；画面中正在旋转的叶片或正在虹吸的水流仍可有相应动作声。

可选本地开放权重引擎：[MMAudio](https://github.com/hkchengrex/MMAudio)、[Sony Woosh](https://github.com/SonyResearch/Woosh)、[AudioLDM2](https://github.com/haoheliu/AudioLDM2)。需要时核实相应权重的使用条件、显存和下载成本。此 Skill 不自动安装或下载这些模型。
