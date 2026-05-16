# EzSubtitles

EzSubtitles is a local, offline subtitle generator with powerful  `.srt` editing functions, powered by [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper).

The programme enable users to **automatically** generate subtitles **locally**, review and proofread them **quickly**, and export a clean `.srt` file **without uploading the media to an online service.**

It is suggested to use the released version for individual users.

## Limitations

- The programme is developed and tested on `MacOS`; thus it will likely fail on `Windows`.
- The interface is currently only available in `Chinese`.

## Features

image [https://github.com/user-attachments/assets/756c1343-d61f-4e57-9f59-6d222eba0a77]
- Utilizes the local `faster-whisper` model to generate `Chinese` and `English` subtitles offline; Provides a ~~through~~ developing  GUI for editing.
- Automatically opens *a file picker* from Finder when the app launches. Another plausible option for importing media is *drag and drop*.
- Displays video playback on the upper left, with the current subtitle shown below the media preview.
- Provides a simple editing timeline on the left below, with:
  - current playback position
  - subtitle blocks
  - time markers
  - draggable subtitle start/end points
  - snapping to markers and neighbouring subtitle boundaries
- Shows all subtitles in a table on the right.
- Supports keyboard-driven review:
  - `Enter`: edit or confirm the current subtitle. Use `Command + Enter` during the text edit to return.
  - `Up` `Down`: move between subtitle rows, automatically jump to the start of the new subtitle row.
  - `Left` `Right`: jump to the start or end of the current subtitle
  - `Command + E`: export `.srt`  
  
  **advanced repair functions**
  - `Option + C`: split subtitle at text cursor, using current playback/video position as the timing boundary.
    - The first block includes the contents before the cursor, starting at the start position of the original block and ends at the current playback position.
    - The second block includes the contents behind the cursor, starting at the current playback position and ends at the end position of the original block.
  - `Option + M`: merge the selected consecutive subtitles into one block.
- Exports subtitles as `.srt`.

## Release

Release builds are intended to include the dependencies and the `faster-whisper` model. Users who download a release should be able to run the app without manually installing Python packages or downloading the model.  
* **The releases are usually several versions behind the code; thus they are more stable.**  
* For now, release builds only target `MacOS`.

## Install

Create a virtual environment, and install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Install `ffmpeg` if it is not already available:

```bash
brew install ffmpeg
```

## Model Setup
- Installing `faster-whisper` with `pip` successfully does not mean the model has been downloaded or placed in the correct location.

For local development, place the model at:

```text
models/small
```

Alternatively, point EzSubtitles to a local model directory with `EASYSUB_MODEL`:

```bash
EASYSUB_MODEL=/Users/your-name/models/faster-whisper-small python -m easysubtitles
```

## Run From Source

```bash
. .venv/bin/activate
python -m easysubtitles
```
