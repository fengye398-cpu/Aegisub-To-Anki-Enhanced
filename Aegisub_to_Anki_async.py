#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Aegisub to Anki - 单张异步制卡（快速版）
不等待 AnkiConnect 响应，立即返回
"""

import os
import sys
import json
import time
from pathlib import Path

def generate_video_id(video_name, start_time, end_time):
    """生成视频ID"""
    def format_time(ms):
        h = int(ms // 3600000)
        m = int((ms % 3600000) // 60000)
        s = int((ms % 60000) // 1000)
        ms_part = int(ms % 1000)
        return f"{h}.{m:02d}.{s:02d}.{ms_part:03d}"

    video_name = video_name.replace(' ', '_').replace("'", '')
    start_str = format_time(start_time)
    end_str = format_time(end_time)
    return f"{video_name}_{start_str}-{end_str}"

def load_config():
    """加载配置文件（和批量脚本共用配置）"""
    import sys

    # PyInstaller打包后需要特殊处理
    if getattr(sys, 'frozen', False):
        # 如果是打包后的exe，使用exe所在目录
        script_dir = Path(sys.executable).parent
    else:
        # 如果是Python脚本，使用脚本所在目录
        script_dir = Path(__file__).parent

    config_path = script_dir / "config.json"

    if not config_path.exists():
        print(f"配置文件不存在，创建默认配置: {config_path}")
        default_config = {
            "deck_name": "Default",
            "model_name": "movies2anki - subs2srs (video)",
            "extraction_mode": "audio_snapshot_video",
            "video_crf": 24,
            "video_preset": "veryfast",
            "audio_bitrate": "128k",
            "snapshot_quality": 3,
            "show_window": False,
            "field": {
                "Audio": "Audio",
                "Video": "Video",
                "SnapShot": "Snapshot",
                "Expression": "Expression",
                "Meaning": "Meaning",
                "Note": "Notes"
            }
        }
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
            print(f"默认配置文件已创建: {config_path}")
            print("请修改 deck_name 为你的Anki牌组名称")
        except Exception as e:
            print(f"错误: 无法创建配置文件: {e}")
            input("\n按任意键退出...")
            raise

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 移除注释
            lines = []
            for line in content.split('\n'):
                comment_pos = line.find('//')
                if comment_pos >= 0:
                    lines.append(line[:comment_pos].rstrip())
                else:
                    lines.append(line)
            clean_content = '\n'.join(lines)
            return json.loads(clean_content)
    except json.JSONDecodeError as e:
        print(f"错误: 配置文件JSON格式错误: {e}")
        input("\n按任意键退出...")
        raise
    except Exception as e:
        print(f"错误: 无法读取配置文件: {e}")
        input("\n按任意键退出...")
        raise

def get_anki_media_dir():
    """自动检测 Anki 媒体目录"""
    anki_base = Path.home() / "AppData/Roaming/Anki2"

    # 遍历所有账户目录
    for profile_dir in anki_base.iterdir():
        if profile_dir.is_dir() and profile_dir.name not in ['addons21', 'crash.log']:
            media_dir = profile_dir / "collection.media"
            if media_dir.exists():
                return media_dir

    raise Exception("未找到 Anki 媒体目录")

def copy_media_files(files, anki_media_dir):
    """复制媒体文件到 Anki"""
    import shutil
    for file_info in files:
        src = Path(file_info['path'])
        if src.exists():
            dest = anki_media_dir / file_info['filename']
            shutil.copy2(src, dest)
            # 删除临时文件
            try:
                src.unlink()
            except:
                pass

def create_curl_request_file(note, request_file):
    """生成 curl 请求文件"""
    request = {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": note
        }
    }

    with open(request_file, 'w', encoding='utf-8') as f:
        json.dump(request, f, ensure_ascii=False)

def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-name", required=True)
    parser.add_argument("--start-time", type=int, required=True)
    parser.add_argument("--end-time", type=int, required=True)
    parser.add_argument("--meaning", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--video", required=True)
    args = parser.parse_args()

    # 加载配置
    config = load_config()
    deck_name = config["deck_name"]
    model_name = config["model_name"]
    fields_config = config["field"]

    # 生成ID和文件名
    card_id = generate_video_id(args.video_name, args.start_time, args.end_time)
    audio_filename = f"{card_id}.mp3"
    snapshot_filename = f"{card_id}.jpg"
    video_filename = f"{card_id}.mp4"

    # 复制媒体文件
    anki_media_dir = get_anki_media_dir()
    files = [
        {"filename": audio_filename, "path": args.audio},
        {"filename": snapshot_filename, "path": args.snapshot},
        {"filename": video_filename, "path": args.video}
    ]
    copy_media_files(files, anki_media_dir)

    # 构建字段
    parts = args.meaning.split("\\N", 1)
    fields = {
        fields_config["Expression"]: parts[0].strip(),
        fields_config["Meaning"]: parts[1].strip().replace("\\N", "<br>") if len(parts) > 1 else "",
        fields_config["Audio"]: f"[sound:{audio_filename}]",
        fields_config["SnapShot"]: f'<img src="{snapshot_filename}">',
        fields_config["Video"]: f"[sound:{video_filename}]",
        "Id": card_id
    }

    # 生成 curl 请求文件
    script_dir = Path(__file__).parent
    request_file = script_dir / "anki_request.json"

    note = {
        "deckName": deck_name,
        "modelName": model_name,
        "fields": fields,
        "options": {"allowDuplicate": False}
    }

    create_curl_request_file(note, request_file)

    # 异步调用 curl（后台执行，不等待）
    curl_cmd = f'start /B curl -s http://localhost:8765 -H "Content-Type: application/json" -X POST --data-binary @"{request_file}" >nul 2>&1'
    os.system(curl_cmd)

    # 立即返回成功
    print(f"制卡请求已发送 (异步)", file=sys.stderr)
    print(f"ID: {card_id}", file=sys.stderr)

if __name__ == "__main__":
    main()
