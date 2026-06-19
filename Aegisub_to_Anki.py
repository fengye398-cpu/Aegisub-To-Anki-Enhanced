#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Aegisub to Anki - 通过AnkiConnect添加卡片
将Aegisub字幕的音频、截图和文本添加到Anki
"""

import os
import sys
import json
import argparse
import random
import string
import requests
from pathlib import Path
import logging
from datetime import datetime
import time
import sqlite3
import subprocess
import multiprocessing

# 尝试导入psutil用于RAM检测
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# 全局Session对象,复用HTTP连接
_http_session = None
# 模板字段缓存
_model_fields_cache = {}
# 最后一次AnkiConnect错误信息
_last_error = None


def check_ffmpeg():
    """检查 FFmpeg 是否可用"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # 使用 ASCII 字符避免编码问题
    print("\nFFMPEG_NOT_FOUND", file=sys.stderr)
    return False


def calculate_optimal_workers(operation_type='light'):
    """根据可用RAM和CPU核心数计算最优worker数量

    Args:
        operation_type: 'video' (视频编码，内存密集) 或 'light' (音频/stream copy，轻量级)

    Returns:
        int: 最优worker数量
    """
    cpu_count = multiprocessing.cpu_count()

    if not HAS_PSUTIL:
        # 没有psutil，使用保守默认值
        if operation_type == 'video':
            return min(3, max(2, cpu_count // 2))
        else:
            return min(6, cpu_count)

    # 获取可用RAM（GB）
    available_ram_gb = psutil.virtual_memory().available / (1024 ** 3)
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)

    logger.info(f"[系统资源] 总内存: {total_ram_gb:.1f}GB, 可用: {available_ram_gb:.1f}GB")

    if operation_type == 'video':
        # 视频编码：每个worker约250-300MB，使用40%可用RAM
        usable_ram_gb = max(0, available_ram_gb - 0.8)
        target_ram_gb = usable_ram_gb * 0.4
        workers = int(target_ram_gb * 1024 / 300)
        workers = max(2, min(workers, cpu_count, 8))

        logger.info(f"[自动调整] 视频编码worker: {workers}个 (基于{available_ram_gb:.1f}GB可用内存)")
        return workers
    else:
        # 轻量级操作（音频/stream copy）：每个worker约50MB
        usable_ram_gb = max(0, available_ram_gb - 0.5)
        target_ram_gb = usable_ram_gb * 0.3
        workers = int(target_ram_gb * 1024 / 50)
        workers = max(4, min(workers, cpu_count, 12))

        logger.info(f"[自动调整] 轻量级操作worker: {workers}个")
        return workers


def sanitize_video_name(name):
    """清理视频名称，将特殊字符和空格替换为下划线

    Args:
        name: 原始视频名称

    Returns:
        清理后的视频名称，例如: "01 Hector's arrival" -> "01_Hectors_arrival"
    """
    if not name:
        return name

    # 替换空格为下划线
    name = name.replace(' ', '_')

    # 移除或替换特殊字符（保留字母、数字、下划线、连字符）
    import re
    # 保留字母、数字、下划线、连字符，其他字符替换为空
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name)

    return name


def format_time_for_filename(milliseconds):
    """将毫秒转换为文件名时间格式: H.MM.SS.mmm

    Args:
        milliseconds: 毫秒数

    Returns:
        格式化的时间字符串，例如: 0.00.01.570
    """
    total_seconds = milliseconds / 1000.0
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    ms = int(milliseconds % 1000)

    return f"{hours}.{minutes:02d}.{seconds:02d}.{ms:03d}"


def generate_filename_from_id(file_id, extension):
    """根据Id生成文件名（movies2anki格式）"""
    return f"{file_id}{extension}"


def generate_video_id(video_name=None, start_time=None, end_time=None):
    """生成视频ID（格式：videoname_H.MM.SS.mmm-H.MM.SS.mmm）

    Args:
        video_name: 视频文件名（不含扩展名），例如 "01 Hector's arrival"
        start_time: 起始时间（毫秒）
        end_time: 结束时间（毫秒）

    Returns:
        格式化的ID，例如: "01_Hectors_arrival_0.00.01.570-0.00.03.140"
    """
    # 如果没有提供视频名称，使用时间戳作为默认值
    if not video_name:
        timestamp = int(time.time() * 1000)
        video_name = f"aegisub_{timestamp}"
    else:
        # 清理视频名称中的特殊字符
        video_name = sanitize_video_name(video_name)

    # 如果有时间信息，使用时间格式
    if start_time is not None and end_time is not None:
        start_str = format_time_for_filename(start_time)
        end_str = format_time_for_filename(end_time)
        return f"{video_name}_{start_str}-{end_str}"
    else:
        # 没有时间信息，只返回视频名称
        return video_name


def setup_logger():
    """设置日志记录器"""
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    log_file = script_dir / "toanki_debug.log"

    # 配置日志格式
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info(f"新的制卡会话开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)

    return logger


# 创建全局logger
logger = setup_logger()


def get_http_session():
    """获取或创建HTTP Session,用于复用连接"""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        logger.info("[性能] 创建新的HTTP Session (连接复用)")
    return _http_session


def anki_connect_request(action, params):
    """发送请求到AnkiConnect (性能优化版)"""
    global _last_error
    perf_start = time.time()

    url = "http://localhost:8765"
    payload = {
        "action": action,
        "version": 6,
        "params": params
    }

    logger.info(f"[请求] action={action}")
    # 优化: 仅在需要时输出详细payload
    # logger.debug(f"请求payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    #向 AnkiConnect插件最大请求时间3600秒
    try:
        http_start = time.time()
        session = get_http_session()
        response = session.post(url, json=payload, timeout=3600)
        http_time = time.time() - http_start
        logger.info(f"[性能] HTTP请求耗时: {http_time:.3f}秒")

        response.raise_for_status()

        parse_start = time.time()
        result = response.json()
        parse_time = time.time() - parse_start
        logger.info(f"[性能] JSON解析耗时: {parse_time:.3f}秒")

        # 优化: 简化响应日志,不使用indent和ensure_ascii
        # logger.debug(f"AnkiConnect响应: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # 调试：打印完整响应
        if action == "addNotes":
            logger.info(f"[调试] 完整响应: {json.dumps(result, ensure_ascii=False)}")

        if result.get("error"):
            # 保存错误信息
            _last_error = result['error']
            # 对于addNotes，即使有error也要返回result（包含部分成功的卡片）
            if action == "addNotes":
                logger.warning(f"[警告] addNotes部分失败: {result['error']}")
                print(f"AnkiConnect错误: {result['error']}", file=sys.stderr)
            else:
                logger.error(f"[错误] AnkiConnect返回错误: {result['error']}")
                print(f"AnkiConnect错误: {result['error']}", file=sys.stderr)
                return None
        else:
            # 清除错误信息
            _last_error = None

        total_time = time.time() - perf_start
        logger.info(f"[性能] {action} 总耗时: {total_time:.3f}秒")
        return result.get("result")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"无法连接到AnkiConnect: {e}")
        print("错误: 无法连接到AnkiConnect。请确保Anki正在运行并已安装AnkiConnect插件。", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.Timeout as e:
        logger.error(f"AnkiConnect请求超时: {e}")
        print("错误: AnkiConnect请求超时", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"请求失败: {e}", exc_info=True)
        print(f"请求失败: {e}", file=sys.stderr)
        return None


def store_media_file(filename, path):
    """存储媒体文件到Anki媒体库"""
    logger.info(f"准备存储媒体文件: filename={filename}, path={path}")

    # 检查文件是否存在
    if not Path(path).exists():
        logger.error(f"媒体文件不存在: {path}")
        return None

    # 获取文件大小
    file_size = Path(path).stat().st_size
    logger.info(f"文件大小: {file_size} bytes")

    # 将Windows路径分隔符转换为正斜杠
    path = path.replace("\\", "/")
    logger.debug(f"转换后的路径: {path}")

    params = {
        "filename": filename,
        "path": path
    }
    result = anki_connect_request("storeMediaFile", params)

    if result:
        logger.info(f"媒体文件存储成功: {result}")
    else:
        logger.error(f"媒体文件存储失败: filename={filename}")

    return result


def store_media_files_batch(files):
    """批量上传媒体文件到Anki媒体库 (性能优化版)

    Args:
        files: 文件信息列表，每个元素包含:
            - filename: 目标文件名
            - path: 源文件路径

    Returns:
        成功上传的文件名列表
    """
    logger.info(f"[批量上传] 准备批量上传 {len(files)} 个媒体文件")

    # 验证所有文件是否存在
    valid_files = []
    for file_info in files:
        filename = file_info['filename']
        path = file_info['path']

        if not Path(path).exists():
            logger.error(f"[批量上传] 文件不存在: {path}")
            continue

        # 获取文件大小
        file_size = Path(path).stat().st_size
        logger.info(f"[批量上传] {filename}: {file_size} bytes")

        # 将Windows路径分隔符转换为正斜杠
        path = path.replace("\\", "/")

        valid_files.append({
            "filename": filename,
            "path": path
        })

    if not valid_files:
        logger.error(f"[批量上传] 没有有效的文件可上传")
        return []

    # 直接复制到Anki媒体文件夹（跳过AnkiConnect）
    copy_to_anki_media(valid_files)

    return [True] * len(valid_files)


def get_anki_media_dir():
    """自动检测 Anki 媒体目录"""
    anki_base = Path.home() / "AppData/Roaming/Anki2"

    # 遍历所有账户目录
    for profile_dir in anki_base.iterdir():
        if profile_dir.is_dir() and profile_dir.name not in ['addons21', 'crash.log']:
            media_dir = profile_dir / "collection.media"
            if media_dir.exists():
                logger.info(f"[检测] 找到Anki媒体目录: {media_dir}")
                return media_dir

    raise Exception("未找到 Anki 媒体目录")


def copy_to_anki_media(files):
    """复制媒体文件到Anki媒体文件夹"""
    import shutil
    try:
        anki_media = get_anki_media_dir()
    except Exception as e:
        logger.error(f"无法检测Anki媒体目录: {e}")
        return

    for file_info in files:
        src = Path(file_info['path'].replace("/", "\\"))
        if src.exists():
            dest = anki_media / file_info['filename']
            shutil.copy2(src, dest)
            logger.info(f"[复制] {file_info['filename']} -> Anki媒体库")
            # 删除临时文件
            try:
                src.unlink()
            except:
                pass



def load_config(config_path=None):
    """加载配置文件

    Returns:
        tuple: (config_dict, config_file_path)
    """
    if config_path is None:
        # 获取脚本所在目录的config.json
        # PyInstaller 打包后需要特殊处理
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe,使用exe所在目录
            script_dir = Path(sys.executable).parent
        else:
            # 如果是Python脚本,使用脚本所在目录
            script_dir = Path(__file__).parent
        config_path = script_dir / "config.json"
    else:
        config_path = Path(config_path)

    logger.info(f"尝试加载配置文件: {config_path}")

    if not config_path.exists():
        logger.warning(f"配置文件不存在，创建默认配置: {config_path}")
        default_config = {
            "deck_name": "Default",
            "model_name": "Basic",
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
            logger.info(f"默认配置文件已创建: {config_path}")
        except Exception as e:
            logger.error(f"无法创建配置文件: {e}")
            print(f"错误: 无法创建配置文件: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            # 读取文件内容并移除注释（支持 // 和 # 风格的注释）
            content = f.read()
            # 移除单行注释（// 和 #）
            lines = []
            for line in content.split('\n'):
                # 查找注释位置（不在字符串内的 // 或 #）
                in_string = False
                comment_pos = -1
                for i, char in enumerate(line):
                    if char == '"' and (i == 0 or line[i-1] != '\\'):
                        in_string = not in_string
                    elif not in_string:
                        # 检查 // 注释
                        if i < len(line) - 1 and line[i:i+2] == '//':
                            comment_pos = i
                            break
                        # 检查 # 注释
                        elif char == '#':
                            comment_pos = i
                            break

                if comment_pos >= 0:
                    lines.append(line[:comment_pos].rstrip())
                else:
                    lines.append(line)

            clean_content = '\n'.join(lines)
            config = json.loads(clean_content)
        logger.info(f"配置文件加载成功")
        logger.debug(f"配置内容: {json.dumps(config, ensure_ascii=False, indent=2)}")
        return config, config_path
    except json.JSONDecodeError as e:
        logger.error(f"配置文件JSON格式错误: {e}", exc_info=True)
        print(f"错误: 配置文件JSON格式错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.error(f"无法读取配置文件: {e}", exc_info=True)
        print(f"错误: 无法读取配置文件: {e}", file=sys.stderr)
        sys.exit(1)


def get_absolute_path(path):
    """获取绝对路径"""
    if not path:
        return None

    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)
    else:
        # 相对路径转换为绝对路径
        return str(Path.cwd() / path_obj)


def load_model_fields_cache(config_dir):
    """从本地文件加载模板字段缓存

    缓存文件格式:
    {
        "model_name": {
            "fields": ["Id", "Expression", "Meaning", ...],
            "timestamp": 1763296682650,
            "ttl": 86400000  // 24小时过期（毫秒）
        }
    }

    Args:
        config_dir: config.json所在的目录路径

    Returns:
        dict: 缓存字典，如果缓存不存在或已过期则返回空字典
    """
    cache_file = Path(config_dir) / "model_fields_cache.json"

    if not cache_file.exists():
        logger.info("[持久化缓存] 缓存文件不存在")
        return {}

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        # 验证并清理过期缓存
        current_time = int(time.time() * 1000)
        valid_cache = {}

        for model_name, cache_entry in cache_data.items():
            timestamp = cache_entry.get('timestamp', 0)
            ttl = cache_entry.get('ttl', 86400000)  # 默认24小时

            if current_time - timestamp < ttl:
                valid_cache[model_name] = cache_entry
                logger.info(f"[持久化缓存] 模板 '{model_name}' 缓存有效")
            else:
                logger.info(f"[持久化缓存] 模板 '{model_name}' 缓存已过期")

        return valid_cache

    except json.JSONDecodeError as e:
        logger.error(f"[持久化缓存] 缓存文件JSON格式错误: {e}")
        return {}
    except Exception as e:
        logger.error(f"[持久化缓存] 读取缓存文件失败: {e}")
        return {}


def save_model_fields_cache(cache_data, config_dir):
    """保存模板字段缓存到本地文件

    Args:
        cache_data: 缓存字典
        config_dir: config.json所在的目录路径
    """
    cache_file = Path(config_dir) / "model_fields_cache.json"

    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"[持久化缓存] 缓存已保存到 {cache_file}")
    except Exception as e:
        logger.error(f"[持久化缓存] 保存缓存文件失败: {e}")


def extract_media_silent(input_file, audio_path, snapshot_path, video_path, start_time, end_time, extraction_mode,
                         video_crf=24, video_preset='veryfast', audio_bitrate='128k', snapshot_quality=3):
    """静默提取媒体文件(无窗口)"""
    import subprocess
    import platform

    start_sec = start_time / 1000.0
    duration_sec = (end_time - start_time) / 1000.0

    # 构建FFmpeg命令
    cmd = ['ffmpeg', '-y', '-ss', str(start_sec), '-i', input_file, '-t', str(duration_sec)]

    if extraction_mode == 'audio':
        cmd.extend(['-vn', '-c:a', 'libmp3lame', '-b:a', audio_bitrate, audio_path])
    elif extraction_mode == 'audio_snapshot':
        cmd.extend([
            '-map', '0:a', '-c:a', 'libmp3lame', '-b:a', audio_bitrate, audio_path,
            '-map', '0:v', '-vframes', '1', '-q:v', str(snapshot_quality), snapshot_path
        ])
    else:  # audio_snapshot_video
        cmd.extend([
            '-c:v', 'libx264', '-crf', str(video_crf), '-preset', video_preset, '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', audio_bitrate, '-ac', '2', video_path,
            '-t', str(duration_sec), '-vn', '-c:a', 'libmp3lame', '-b:a', audio_bitrate, audio_path,
            '-t', str(duration_sec), '-vframes', '1', '-q:v', str(snapshot_quality), snapshot_path
        ])

    # Windows下使用CREATE_NO_WINDOW隐藏窗口
    creationflags = 0
    if platform.system() == 'Windows':
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        subprocess.run(cmd, check=True, creationflags=creationflags,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        logger.error(f"[媒体提取] 失败: {e}")
        return False


def execute_batch_file(batch_file_path):
    """执行批处理文件并等待完成"""
    import subprocess
    import platform

    logger.info(f"[批处理] 执行: {batch_file_path}")

    creationflags = 0
    if platform.system() == 'Windows':
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        subprocess.run([batch_file_path], check=True, creationflags=creationflags,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"[批处理] 执行完成")
        return True
    except Exception as e:
        logger.error(f"[批处理] 执行失败: {e}")
        return False


def process_batch(batch_file_path):
    """批量处理任务文件，批量上传媒体并创建多张卡片

    批量任务JSON格式(数组)：
    [
      {
        "video_name": "S01E01",
        "start_time": 749190,
        "end_time": 751090,
        "meaning": "字幕文本",
        "audio": "C:/.../aegisub_audio_temp_1.mp3",
        "snapshot": "C:/.../aegisub_snapshot_temp_1.png",
        "video": "C:/.../aegisub_video_temp_1.mp4",
        "input_file": "C:/.../video.mp4",
        "ffmpeg_batch": "C:/.../ffmpeg_batch.bat"
      }
    ]
    """
    batch_start = time.time()
    logger.info(f"[批量] 读取任务文件: {batch_file_path}")

    # 加载配置
    print("正在验证配置，请稍候...", file=sys.stderr)
    config, config_path = load_config()
    config_dir = config_path.parent
    deck_name = config.get("deck_name", "Default")
    model_name = config.get("model_name", "Basic")
    fields_config = config.get("field", {})

    # 清理上次遗留的临时文件
    logger.info("[清理] 清理旧的临时文件...")
    cleanup_start = time.time()
    cleanup_count = 0

    import glob
    temp_patterns = [
        'aegisub_audio_temp_*.mp3',
        'aegisub_snapshot_temp_*.png',
        'aegisub_snapshot_temp_*.jpg',
        'aegisub_video_temp_*.mp4'
    ]

    for pattern in temp_patterns:
        for file_path in glob.glob(str(config_dir / pattern)):
            try:
                os.remove(file_path)
                cleanup_count += 1
            except Exception as e:
                logger.warning(f"[清理] 删除文件失败: {file_path}, 错误: {e}")

    cleanup_time = time.time() - cleanup_start
    logger.info(f"[清理] 已删除 {cleanup_count} 个临时文件，耗时: {cleanup_time:.3f}秒")

    # 读取批量任务
    try:
        with open(batch_file_path, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except Exception as e:
        logger.error(f"[批量] 读取任务文件失败: {e}")
        print(f"读取批量任务失败: {e}", file=sys.stderr)
        return

    if not isinstance(tasks, list) or not tasks:
        logger.error("[批量] 任务列表为空")
        print("批量任务为空", file=sys.stderr)
        return

    logger.info(f"[批量] 任务数量: {len(tasks)}")

    # 只有多张卡片时才验证牌组和模板（单张跳过验证以提升性能）
    if len(tasks) > 1:
        logger.info(f"[批量] 验证牌组: {deck_name}")
        deck_names = anki_connect_request("deckNames", {})
        if not deck_names or deck_name not in deck_names:
            error_msg = f"错误：牌组 '{deck_name}' 不存在"
            logger.error(error_msg)
            print(error_msg, file=sys.stderr)
            if deck_names:
                print(f"可用牌组: {', '.join(deck_names[:10])}", file=sys.stderr)
            sys.exit(1)

        logger.info(f"[批量] 验证模板: {model_name}")
        model_names = anki_connect_request("modelNames", {})
        if not model_names or model_name not in model_names:
            error_msg = f"错误：模板 '{model_name}' 不存在"
            logger.error(error_msg)
            print(error_msg, file=sys.stderr)
            if model_names:
                print(f"可用模板: {', '.join(model_names[:10])}", file=sys.stderr)
            sys.exit(1)

        print("配置验证成功", file=sys.stderr)
    else:
        logger.info("[单张] 跳过验证，直接制卡（性能优化）")
        print("正在制卡，请稍候...", file=sys.stderr)

    # 预取模板字段
    persistent_cache = load_model_fields_cache(config_dir)
    if model_name in persistent_cache:
        model_fields = persistent_cache[model_name].get('fields', [])
    else:
        model_fields_response = anki_connect_request("modelFieldNames", {"modelName": model_name})
        model_fields = model_fields_response or []
        # 保存缓存
        if model_fields:
            persistent_cache[model_name] = {
                'fields': model_fields,
                'timestamp': int(time.time() * 1000),
                'ttl': 86400000
            }
            save_model_fields_cache(persistent_cache, config_dir)

    files_to_upload = []
    notes = []

    id_field_name = None
    for fn in model_fields:
        if fn and str(fn).lower() == 'id':
            id_field_name = fn
            break

    # 检查是否需要提取媒体
    input_file = tasks[0].get('input_file') if tasks else None
    if not input_file:
        # 从ffmpeg_batch推断需要提取媒体
        ffmpeg_batch_file = tasks[0].get('ffmpeg_batch') if tasks else None
        if ffmpeg_batch_file:
            logger.info(f"[并行提取] 开始并行提取媒体文件")
            print("正在提取媒体文件...", file=sys.stderr)

            import subprocess
            import platform
            from concurrent.futures import ThreadPoolExecutor, as_completed

            creationflags = 0
            if platform.system() == 'Windows':
                creationflags = subprocess.CREATE_NO_WINDOW

            def extract_single(task_info):
                task, idx = task_info
                audio_path = task.get('audio', '').replace('/', '\\')
                snapshot_path = task.get('snapshot', '').replace('/', '\\')
                video_path = task.get('video', '').replace('/', '\\')
                start_time = task.get('start_time')
                end_time = task.get('end_time')
                extraction_mode = task.get('extraction_mode', 'audio_snapshot_video')
                video_crf = task.get('video_crf', 24)
                video_preset = task.get('video_preset', 'veryfast')
                audio_bitrate = task.get('audio_bitrate', '128k')
                snapshot_quality = task.get('snapshot_quality', 3)

                # 从第一个任务���取input_file
                batch_file = task.get('ffmpeg_batch')
                if batch_file and Path(batch_file).exists():
                    with open(batch_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        import re
                        match = re.search(r'-i "([^"]+)"', content)
                        if match:
                            input_file_path = match.group(1)

                            start_sec = start_time / 1000.0
                            duration_sec = (end_time - start_time) / 1000.0

                            try:
                                # 音频
                                subprocess.run(['ffmpeg', '-y', '-ss', str(start_sec), '-i', input_file_path,
                                              '-t', str(duration_sec), '-vn', '-c:a', 'libmp3lame',
                                              '-b:a', audio_bitrate, audio_path],
                                             creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

                                # 截图
                                subprocess.run(['ffmpeg', '-y', '-ss', str(start_sec), '-i', input_file_path,
                                              '-vframes', '1', '-q:v', str(snapshot_quality), snapshot_path],
                                             creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

                                # 视频
                                if extraction_mode == 'audio_snapshot_video':
                                    subprocess.run(['ffmpeg', '-y', '-ss', str(start_sec), '-i', input_file_path,
                                                  '-t', str(duration_sec), '-c:v', 'libx264', '-crf', str(video_crf),
                                                  '-preset', video_preset, '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                                                  '-b:a', audio_bitrate, '-ac', '2', video_path],
                                                 creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

                                return idx, True
                            except Exception as e:
                                logger.error(f"[并行提取] 任务#{idx} FFmpeg失败: {e}")
                                return idx, False
                return idx, False

            # 并行执行
            max_workers = calculate_optimal_workers('light')
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(extract_single, (task, idx)) for idx, task in enumerate(tasks, 1)]
                for future in as_completed(futures):
                    idx, success = future.result()
                    if success:
                        logger.info(f"[并行提取] 任务#{idx} 完成")

            logger.info(f"[并行提取] 所有媒体文件提取完成")

    for idx, task in enumerate(tasks, start=1):
        video_name = task.get('video_name')
        start_time = task.get('start_time')
        end_time = task.get('end_time')
        meaning_text = task.get('meaning', "")

        if start_time is None or end_time is None:
            logger.warning(f"[批量] 任务#{idx} 缺少时间信息，跳过")
            continue

        card_id = generate_video_id(video_name=video_name, start_time=start_time, end_time=end_time)

        audio_filename = generate_filename_from_id(card_id, ".mp3")
        snapshot_filename = generate_filename_from_id(card_id, ".jpg")
        video_filename = generate_filename_from_id(card_id, ".mp4")

        audio_path = task.get('audio')
        snapshot_path = task.get('snapshot')
        video_path = task.get('video')

        if audio_path:
            files_to_upload.append({"filename": audio_filename, "path": audio_path})
        if snapshot_path:
            files_to_upload.append({"filename": snapshot_filename, "path": snapshot_path})
        if video_path:
            files_to_upload.append({"filename": video_filename, "path": video_path})

        fields = {}
        if meaning_text:
            parts = meaning_text.split("\\N", 1)
            if len(parts) == 2:
                fields[fields_config.get("Expression", "Expression")] = parts[0].strip()
                fields[fields_config.get("Meaning", "Meaning")] = parts[1].strip().replace("\\N", "<br>")
            else:
                fields[fields_config.get("Expression", "Expression")] = parts[0].strip()
        if audio_path:
            fields[fields_config.get("Audio", "Audio")] = f"[sound:{audio_filename}]"
        if snapshot_path:
            fields[fields_config.get("SnapShot", "Snapshot")] = f'<img src="{snapshot_filename}">'
        if video_path:
            fields[fields_config.get("Video", "Video")] = f"[sound:{video_filename}]"
        if id_field_name:
            fields[id_field_name] = card_id

        for field_name in model_fields:
            if field_name not in fields:
                fields[field_name] = ""

        notes.append({"deckName": deck_name, "modelName": model_name, "fields": fields})

    # 批量上传媒体
    if files_to_upload:
        logger.info(f"[批量] 准备上传媒体: {len(files_to_upload)} 个文件")
        store_media_files_batch(files_to_upload)

    # 批量创建卡片
    logger.info(f"[批量] 调用 addNotes 创建 {len(notes)} 张卡片")
    results = anki_connect_request("addNotes", {"notes": notes})

    # 处理返回结果
    success = 0
    if results is None:
        # 批量失败，先检查是否是配置错误
        if _last_error and ('deck was not found' in str(_last_error) or 'model was not found' in str(_last_error)):
            # 配置错误，直接报错退出
            error_msg = str(_last_error)
            if 'deck was not found' in error_msg:
                logger.error(f"[错误] 牌组不存在: {deck_name}")
                print(f"\n错误：牌组 '{deck_name}' 不存在", file=sys.stderr)
                print("请在 Anki 中创建该牌组，或修改 config.json 中的 deck_name", file=sys.stderr)
            elif 'model was not found' in error_msg:
                logger.error(f"[错误] 模板不存在: {model_name}")
                print(f"\n错误：模板 '{model_name}' 不存在", file=sys.stderr)
                print("请在 Anki 中创建该模板，或修改 config.json 中的 model_name", file=sys.stderr)
            sys.exit(1)

        # 不是配置错误，检查哪些卡片重复
        logger.warning(f"[批量] 批量添加失败，检查重复卡片...")
        can_add = anki_connect_request("canAddNotes", {"notes": notes})

        if can_add and isinstance(can_add, list):
            duplicate_indices = [i for i, can in enumerate(can_add) if not can]
            new_indices = [i for i, can in enumerate(can_add) if can]

            logger.info(f"[检查] 发现 {len(duplicate_indices)} 张重复，{len(new_indices)} 张可添加")

            # 只添加非重复的卡片
            if new_indices:
                new_notes = [notes[i] for i in new_indices]
                logger.info(f"[批量] 添加 {len(new_notes)} 张新卡片")
                new_results = anki_connect_request("addNotes", {"notes": new_notes})
                if isinstance(new_results, list):
                    success = sum(1 for r in new_results if r)

            # 输出重复卡片信息到stderr（供Aegisub显示）
            if duplicate_indices:
                logger.warning(f"[重复] 以下 {len(duplicate_indices)} 张卡片已存在:")
                print(f"\nDUPLICATE_COUNT:{len(duplicate_indices)}", file=sys.stderr)
                for idx in duplicate_indices:  # 显示全部重复卡片
                    task = tasks[idx] if idx < len(tasks) else {}
                    start_ms = task.get('start_time', 0)
                    end_ms = task.get('end_time', 0)
                    # 转换为时:分:秒.毫秒格式
                    start_str = f"{start_ms//3600000}:{(start_ms%3600000)//60000:02d}:{(start_ms%60000)//1000:02d}.{start_ms%1000:03d}"
                    end_str = f"{end_ms//3600000}:{(end_ms%3600000)//60000:02d}:{(end_ms%60000)//1000:02d}.{end_ms%1000:03d}"
                    logger.warning(f"  - 卡片#{idx+1}: {start_str}-{end_str}")
                    print(f"DUPLICATE_CARD:{idx+1}:{start_str}-{end_str}", file=sys.stderr)
        else:
            logger.error(f"[检查] 无法检查重复卡片")
    elif isinstance(results, list):
        # 部分成功
        success = sum(1 for r in results if r)
        failed_count = len(results) - success
        if failed_count > 0:
            logger.info(f"[批量] 跳过 {failed_count} 张重复卡片")

    logger.info(f"[批量] 创建完成: {success}/{len(notes)}")

    batch_total = time.time() - batch_start
    logger.info(f"[批量] 总耗时: {batch_total:.3f}秒")

    # 输出到stderr和状态文件
    result_text = f"Batch created: {success}/{len(notes)}\nTotal time: {batch_total:.3f}s"
    print(result_text, file=sys.stderr)

    # 写入状态文件供Lua读取
    status_file = Path(batch_file_path).parent / "toanki_status.txt"
    try:
        with open(status_file, 'w', encoding='utf-8') as f:
            f.write(f"success={success}\n")
            f.write(f"total={len(notes)}\n")
            f.write(f"time={batch_total:.3f}\n")
        logger.info(f"[批量] 状态文件已写入: {status_file}")
    except Exception as e:
        logger.error(f"[批量] 写入状态文件失败: {e}")


def main():
    """主函数"""
    # 检查 FFmpeg
    if not check_ffmpeg():
        sys.exit(1)

    # 程序开始时间
    program_start = time.time()
    logger.info("开始执行主函数")
    logger.info(f"[性能] 程序启动时间: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")

    # 设置命令行参数
    parser = argparse.ArgumentParser(description="Aegisub to Anki - 添加卡片到Anki")
    parser.add_argument("-a", "--audio", help="音频文件路径")
    parser.add_argument("-s", "--snapshot", help="截图文件路径")
    parser.add_argument("-v", "--video", help="视频文件路径")
    parser.add_argument("-m", "--meaning", help="字幕文本")
    parser.add_argument("-n", "--note", help="笔记内容")
    parser.add_argument("--video-name", help="视频文件名（不含扩展名），例如: 01")
    parser.add_argument("--start-time", type=int, help="起始时间（毫秒）")
    parser.add_argument("--end-time", type=int, help="结束时间（毫秒）")
    parser.add_argument("--batch", help="批量处理模式：指定包含批量任务的JSON文件路径")

    args = parser.parse_args()

    # 检查是否是批量处理模式
    if args.batch:
        logger.info(f"批量处理模式: {args.batch}")
        process_batch(args.batch)
        return

    logger.info(f"命令行参数:")
    logger.info(f"  - 音频路径: {args.audio}")
    logger.info(f"  - 截图路径: {args.snapshot}")
    logger.info(f"  - 视频路径: {args.video}")
    logger.info(f"  - 字幕文本: {args.meaning}")
    logger.info(f"  - 笔记内容: {args.note}")
    logger.info(f"  - 视频名称: {args.video_name}")
    logger.info(f"  - 起始时间: {args.start_time}")
    logger.info(f"  - 结束时间: {args.end_time}")

    # 加载配置
    config, config_path = load_config()
    config_dir = config_path.parent  # 获取配置文件所在目录

    deck_name = config.get("deck_name", "Default")
    model_name = config.get("model_name", "Basic")
    fields_config = config.get("field", {})

    logger.info(f"Anki配置:")
    logger.info(f"  - 牌组名称: {deck_name}")
    logger.info(f"  - 模板名称: {model_name}")
    logger.info(f"  - 字段配置: {fields_config}")

    # 准备字段数据
    fields = {}

    # 生成唯一的卡片ID（movies2anki格式）
    card_id = generate_video_id(
        video_name=args.video_name,
        start_time=args.start_time,
        end_time=args.end_time
    )
    logger.info(f"生成卡片ID: {card_id}")

    # 收集需要上传的媒体文件（批量上传优化）
    files_to_upload = []
    media_info = {}  # 存储文件名和字段的映射关系

    # 处理音频
    if args.audio:
        logger.info(f"准备音频文件: {args.audio}")
        audio_path = get_absolute_path(args.audio)
        if audio_path and Path(audio_path).exists():
            audio_filename = generate_filename_from_id(card_id, ".mp3")
            files_to_upload.append({
                "filename": audio_filename,
                "path": audio_path
            })
            media_info['audio'] = {
                'filename': audio_filename,
                'field': fields_config.get("Audio", "Audio"),
                'format': 'sound'
            }
            logger.info(f"✓ 音频文件加入上传队列: {audio_filename}")
        else:
            logger.warning(f"音频文件不存在: {args.audio}")
            print(f"警告: 音频文件不存在: {args.audio}", file=sys.stderr)

    # 处理截图
    if args.snapshot:
        logger.info(f"准备截图文件: {args.snapshot}")
        snapshot_path = get_absolute_path(args.snapshot)
        if snapshot_path and Path(snapshot_path).exists():
            snapshot_filename = generate_filename_from_id(card_id, ".jpg")
            files_to_upload.append({
                "filename": snapshot_filename,
                "path": snapshot_path
            })
            media_info['snapshot'] = {
                'filename': snapshot_filename,
                'field': fields_config.get("SnapShot", "Snapshot"),
                'format': 'image'
            }
            logger.info(f"✓ 截图文件加入上传队列: {snapshot_filename}")
        else:
            logger.warning(f"截图文件不存在: {args.snapshot}")
            print(f"警告: 截图文件不存在: {args.snapshot}", file=sys.stderr)

    # 处理视频
    if args.video:
        logger.info(f"准备视频文件: {args.video}")
        video_path = get_absolute_path(args.video)
        if video_path and Path(video_path).exists():
            video_filename = generate_filename_from_id(card_id, ".mp4")
            files_to_upload.append({
                "filename": video_filename,
                "path": video_path
            })
            media_info['video'] = {
                'filename': video_filename,
                'field': fields_config.get("Video", "Video"),
                'format': 'video'
            }
            logger.info(f"✓ 视频文件加入上传队列: {video_filename}")
        else:
            logger.warning(f"视频文件不存在: {args.video}")
            print(f"警告: 视频文件不存在: {args.video}", file=sys.stderr)

    # 批量上传所有媒体文件（性能优化：一次HTTP请求）
    if files_to_upload:
        logger.info(f"========== 开始批量上传 {len(files_to_upload)} 个文件 ==========")
        batch_start = time.time()

        results = store_media_files_batch(files_to_upload)

        batch_time = time.time() - batch_start
        logger.info(f"[性能] 批量上传耗时: {batch_time:.3f}秒")

        # 根据上传结果填充字段
        if results:
            for i, result in enumerate(results):
                if result:
                    # 判断是哪个文件
                    uploaded_filename = files_to_upload[i]['filename']

                    # 查找对应的媒体类型
                    for media_type, info in media_info.items():
                        if info['filename'] == uploaded_filename:
                            field_name = info['field']
                            if info['format'] == 'sound':
                                fields[field_name] = f"[sound:{uploaded_filename}]"
                            elif info['format'] == 'image':
                                fields[field_name] = f'<img src="{uploaded_filename}">'
                            elif info['format'] == 'video':
                                fields[field_name] = f"[sound:{uploaded_filename}]"  # 视频也使用[sound:]格式
                            logger.info(f"✓ {media_type}字段已添加: {field_name}")
                            break
                else:
                    logger.warning(f"文件上传被跳过: {files_to_upload[i]['filename']}")
        else:
            logger.error("批量上传失败")
    else:
        logger.info("没有媒体文件需要上传")

    # 处理字幕
    if args.meaning:
        logger.info(f"处理字幕文本: {args.meaning}")
        parts = args.meaning.split("\\N", 1)
        if len(parts) == 2:
            expression_field = fields_config.get("Expression", "Expression")
            meaning_field = fields_config.get("Meaning", "Meaning")
            fields[expression_field] = parts[0].strip()
            fields[meaning_field] = parts[1].strip().replace("\\N", "<br>")
            logger.info(f"字幕字段已添加: {expression_field} = {parts[0].strip()}, {meaning_field} = {parts[1].strip()}")
        else:
            expression_field = fields_config.get("Expression", "Expression")
            fields[expression_field] = parts[0].strip()
            logger.info(f"字幕字段已添加: {expression_field} = {parts[0].strip()}")

    # 处理笔记
    if args.note:
        logger.info(f"处理笔记内容: {args.note}")
        note_field = fields_config.get("Note", "Notes")
        fields[note_field] = args.note
        logger.info(f"笔记字段已添加: {note_field} = {args.note}")

    # 检查是否有字段数据
    if not fields:
        logger.error("没有提供任何字段数据")
        print("错误: 没有提供任何字段数据", file=sys.stderr)
        sys.exit(1)

    logger.info(f"准备添加卡片,字段数据: {json.dumps(fields, ensure_ascii=False, indent=2)}")

    # 获取模板的所有字段，确保没有遗漏的必填字段 (带持久化缓存优化)
    logger.info("检查模板字段...")
    perf_model_start = time.time()

    # 优化: 使用持久化缓存避免重复查询
    # 首先加载持久化缓存
    persistent_cache = load_model_fields_cache(config_dir)

    # 检查缓存中是否有该模板
    if model_name in persistent_cache:
        cache_entry = persistent_cache[model_name]
        model_fields = cache_entry.get('fields', [])
        logger.info(f"[性能] 从持久化缓存读取模板字段 (耗时: ~0.000秒)")
    else:
        # 缓存未命中，需要查询API
        logger.info(f"[持久化缓存] 模板 '{model_name}' 不在缓存中，查询API...")
        model_fields_response = anki_connect_request("modelFieldNames", {"modelName": model_name})
        if model_fields_response:
            model_fields = model_fields_response
            # 保存到持久化缓存
            current_time = int(time.time() * 1000)
            persistent_cache[model_name] = {
                "fields": model_fields,
                "timestamp": current_time,
                "ttl": 86400000  # 24小时（毫秒）
            }
            save_model_fields_cache(persistent_cache, config_dir)
            logger.info(f"[性能] 查询并缓存模板字段到持久化缓存")
        else:
            model_fields = []

    perf_model_time = time.time() - perf_model_start
    logger.info(f"[性能] 模板字段处理耗时: {perf_model_time:.3f}秒")

    if model_fields:
        logger.info(f"模板 '{model_name}' 的所有字段: {model_fields}")

        # 为所有未填充的字段添加占位符
        # 特别处理 Id 字段 - 使用我们生成的card_id
        for field_name in model_fields:
            if field_name not in fields:
                if field_name.lower() == 'id':
                    # 使用生成的card_id（movies2anki格式）
                    fields[field_name] = card_id
                    logger.debug(f"为Id字段设置值: {field_name} = {fields[field_name]}")
                else:
                    # 其他空字段留空
                    fields[field_name] = ""
                    logger.debug(f"为空字段添加默认值: {field_name} = (空)")

    logger.info(f"最终字段数据: {json.dumps(fields, ensure_ascii=False, indent=2)}")

    # 添加卡片
    params = {
        "note": {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields
        }
    }

    logger.info("调用addNote API")
    result = anki_connect_request("addNote", params)

    if result:
        logger.info(f"卡片添加成功! 卡片ID: {result}")
        print(f"成功添加卡片，ID: {result}")
    else:
        logger.error("添加卡片失败")
        print("添加卡片失败", file=sys.stderr)
        sys.exit(1)

    # 程序总耗时
    program_total = time.time() - program_start
    logger.info("程序执行完成")
    logger.info(f"[性能] ========== 总耗时: {program_total:.3f}秒 ==========")
    # 输出总耗时到stderr供Aegisub捕获(使用英文避免编码问题)
    print(f"Total time: {program_total:.3f}s", file=sys.stderr)
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
