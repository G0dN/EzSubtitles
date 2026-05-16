# EasySubtitles

本地离线自动字幕 + SRT 校对工具 MVP。

## 功能

- 启动时自动打开导入窗口，拖拽或导入视频/音频后自动生成字幕
- 使用本地 `faster-whisper` 模型生成中英文字幕
- 左侧显示视频画面或音频波形
- 媒体下方实时预览当前字幕
- 简易编辑轨道：时间坐标轴、字幕块、时间点标记、拖动字幕开始/结束并吸附到标记或相邻字幕边界
- 右侧字幕列表：点击跳转、编辑文本、上下箭头切换、Enter 确认
- 导出 `.srt`

## 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

`faster-whisper` 是离线推理库，但模型文件需要提前下载到本机。推荐把模型放到项目内 `models/small`，或者启动时指定模型目录：

```bash
EASYSUB_MODEL=/Users/gordon/models/faster-whisper-small python -m easysubtitles
```

注意：`pip list` 里有 `faster-whisper` 只代表转写库已经安装，不代表 Whisper 模型文件已经在本地。为了保持离线，应用不会默认用 `small`、`medium` 这类模型名触发联网下载。

需要系统安装 `ffmpeg`，用于从视频中抽取音频和生成波形数据。

## 运行

```bash
. .venv/bin/activate
python -m easysubtitles
```

## 备注

如果没有安装 `faster-whisper` 或没有可用模型，应用仍可打开并生成一条占位字幕，方便测试 GUI 校对流程。
