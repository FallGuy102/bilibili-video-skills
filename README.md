# Bilibili 视频总结 Skills

这是一组面向 Codex 的视频总结 Skill，主要用于总结哔哩哔哩视频，同时兼容部分其他公开视频网址和本地视频文件。

仓库提供两种工作模式：优先使用低成本的字幕与语音文本；只有在画面确实影响理解时，才下载视频轨道并抽取少量关键帧。

## 两个 Skill 的区别

| Skill | 处理内容 | 适合场景 | 资源消耗 |
| --- | --- | --- | --- |
| `bilibili-video-summary` | 视频标题、简介、平台总结、字幕、语音 | 访谈、演讲、知识讲解、观点分析、播客 | 较低 |
| `bilibili-video-visual-summary` | 字幕或语音，以及经过筛选的重要画面 | 游戏视频、PPT、公式、软件操作、演示和视觉证据分析 | 较高 |

如果视频只需要理解“说了什么”，应优先使用第一个 Skill。如果画面中的操作、文字、图表或事件会改变结论，再使用第二个。

## 工作方式

### 纯内容总结

`bilibili-video-summary` 按照以下顺序获取信息：

1. 获取 Bilibili 视频元数据和平台生成的 AI 总结。
2. 尝试读取视频公开字幕。
3. 对其他平台尝试通过 `yt-dlp` 获取字幕。
4. 没有可用文本时，才下载音频并使用 `faster-whisper` 进行本地语音识别。
5. 根据文本整理核心观点、论证结构、案例、结论和时间点。

这个流程不会为了总结语音而下载视频画面，因此通常速度更快、消耗更低。

### 内容与画面总结

`bilibili-video-visual-summary` 会先完成文本分析，再根据字幕中的“看这里”“如图”“接下来演示”等提示定位相关时间点，并进行有限的画面抽取：

1. 获取字幕或生成本地语音转录。
2. 从关键时间点、镜头切换处或均匀时间点抽取少量帧。
3. 将画面时间戳与对应语音对齐。
4. 综合说明“视频说了什么”和“画面实际展示了什么”。

它采用稀疏抽帧，不是逐帧观看。对于高速动作、短暂 UI 变化或需要连续运动判断的内容，结果可能需要在相关时间段增加采样密度。

## 安装

将仓库克隆到本地：

```bash
git clone https://github.com/FallGuy102/bilibili-video-skills.git
```

然后将两个 Skill 目录复制到 Codex 的个人 Skill 目录：

```bash
mkdir -p ~/.codex/skills
cp -R bilibili-video-skills/skills/bilibili-video-summary ~/.codex/skills/
cp -R bilibili-video-skills/skills/bilibili-video-visual-summary ~/.codex/skills/
```

也可以使用符号链接，方便在仓库更新后立即生效：

```bash
ln -s "$(pwd)/bilibili-video-skills/skills/bilibili-video-summary" ~/.codex/skills/bilibili-video-summary
ln -s "$(pwd)/bilibili-video-skills/skills/bilibili-video-visual-summary" ~/.codex/skills/bilibili-video-visual-summary
```

重新打开 Codex 会话后即可使用。

## 依赖

基础要求：

- Python 3.10 或更高版本
- 可公开访问的 Bilibili 视频，或本地视频文件

按功能选择安装：

- `yt-dlp`：处理其他视频平台、字幕回退及部分媒体下载
- `faster-whisper`：在没有字幕时进行本地语音识别
- `ffmpeg` 与 `ffprobe`：抽取视频画面；视觉总结必需

示例：

```bash
python3 -m pip install yt-dlp faster-whisper
```

`ffmpeg` 建议使用操作系统的软件包管理器安装。

## 使用示例

安装后，可以直接向 Codex 提供网址或本地文件：

```text
总结这个视频，只分析它讲了什么，不分析画面：
https://www.bilibili.com/video/BVxxxxxxxxxx/
```

```text
总结这个游戏设计视频，并结合画面分析实际展示的机制：
https://www.bilibili.com/video/BVxxxxxxxxxx/
```

也可以提出更具体的要求，例如：

- 按时间顺序整理视频内容。
- 提取核心观点和论据。
- 总结成学习笔记。
- 检查口头描述与画面演示是否一致。
- 只分析某个时间区间的界面、PPT 或游戏机制。

## 手动运行辅助脚本

通常应由 Skill 自动选择流程，也可以单独运行脚本。

只获取现有字幕和平台文本，不启动语音识别：

```bash
python3 skills/bilibili-video-summary/scripts/prepare_transcript.py \
  "视频网址或本地文件" --out-dir ./output --asr none
```

没有字幕时启用本地语音识别：

```bash
python3 skills/bilibili-video-summary/scripts/prepare_transcript.py \
  "视频网址或本地文件" --out-dir ./output --asr local --model small
```

抽取有限数量的场景变化帧：

```bash
python3 skills/bilibili-video-visual-summary/scripts/extract_frames.py \
  "视频网址或本地文件" --out-dir ./frames --mode scene --max-frames 20
```

脚本会将报告、转录文本、元数据或抽取画面保存到指定输出目录，重复使用同一目录可以复用已经完成的处理结果。

## 限制

- 不会绕过登录、付费、地区或账号限制。
- 默认不读取浏览器 Cookie；无法公开访问时，建议提供本地视频文件。
- Bilibili 接口或页面规则变化后，字幕及媒体获取方式可能需要更新。
- 语音识别可能误判人名、数字、公式和专业术语。
- 视觉总结只检查选中的画面，不等同于逐帧理解整个视频。
- 请遵守视频平台条款、版权要求和所在地法律，仅处理你有权访问和分析的内容。

## 项目结构

```text
skills/
├── bilibili-video-summary/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── scripts/prepare_transcript.py
└── bilibili-video-visual-summary/
    ├── SKILL.md
    ├── agents/openai.yaml
    └── scripts/
        ├── prepare_transcript.py
        └── extract_frames.py
```

