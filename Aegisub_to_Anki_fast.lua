
local tr = aegisub.gettext

script_name = tr("导出选中字幕行发送到Anki单张制卡")
script_description = tr("异步制卡，立即返回，适合单张快速制卡")
script_author = ""
script_version = "1.0"

local function get_temp_dir()
    local aegisub_dir = aegisub.decode_path("?user")
    local temp = aegisub_dir .. "\\toanki_temp"
    os.execute('mkdir "' .. temp .. '" 2>nul')
    return temp
end

local function process(subs, sel)
    -- 只处理单张
    if #sel ~= 1 then
        aegisub.debug.out("快速制卡仅支持单张字幕\n")
        aegisub.debug.out("请选择1行字幕，或使用批量制卡功能\n")
        return
    end

    local temp_dir = get_temp_dir()
    local py_file = temp_dir .. "\\Aegisub_to_Anki_async.py"

    -- 获取视频信息
    local video_path = aegisub.project_properties().video_file
    if not video_path or video_path == "" then
        aegisub.debug.out("错误：未加载视频文件\n")
        return
    end

    local video_name = video_path:match("([^/\\]+)%.[^.]+$") or "video"

    -- 获取字幕信息
    local line = subs[sel[1]]
    local start_time = line.start_time
    local end_time = line.end_time
    local text = line.text

    -- 生成临时文件路径
    local audio_path = temp_dir .. "\\aegisub_audio_temp_1.mp3"
    local snapshot_path = temp_dir .. "\\aegisub_snapshot_temp_1.jpg"
    local video_path_out = temp_dir .. "\\aegisub_video_temp_1.mp4"

    -- 提取媒体（同步，必须等待）
    aegisub.debug.out("正在提取媒体文件...\n")

    local start_sec = start_time / 1000
    local duration = (end_time - start_time) / 1000

    -- 生成批处理文件（使用成熟方案）
    local batch_file = temp_dir .. "\\ffmpeg_extract.bat"
    local f = io.open(batch_file, "w")

   -- 设置 UTF-8 编码
    f:write("chcp 65001 >nul\n")

    -- 音频
    f:write(string.format('start /B /WAIT ffmpeg -y -ss %.3f -i "%s" -t %.3f -vn -c:a libmp3lame -b:a 128k "%s"\n',
        start_sec, video_path, duration, audio_path))

    -- 截图
    f:write(string.format('start /B /WAIT ffmpeg -y -ss %.3f -i "%s" -vframes 1 -q:v 3 "%s"\n',
        start_sec, video_path, snapshot_path))

    -- 视频
    f:write(string.format('start /B /WAIT ffmpeg -y -ss %.3f -i "%s" -t %.3f -c:v libx264 -crf 24 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 128k -ac 2 "%s"\n',
        start_sec, video_path, duration, video_path_out))

    -- 检查是否有EXE版本
    local exe_file = temp_dir .. "\\Aegisub_to_Anki_async.exe"
    local py_exists = io.open(py_file, "r")
    local exe_exists = io.open(exe_file, "r")

    if py_exists then
        py_exists:close()
        aegisub.debug.out("使用 Python 模式（开发）\n")
        f:write(string.format('python "%s" --video-name "%s" --start-time %d --end-time %d --meaning "%s" --audio "%s" --snapshot "%s" --video "%s"\n',
            py_file, video_name, start_time, end_time, text, audio_path, snapshot_path, video_path_out))
    elseif exe_exists then
        exe_exists:close()
        aegisub.debug.out("使用 EXE 模式（生产）\n")
        f:write(string.format('"%s" --video-name "%s" --start-time %d --end-time %d --meaning "%s" --audio "%s" --snapshot "%s" --video "%s"\n',
            exe_file, video_name, start_time, end_time, text, audio_path, snapshot_path, video_path_out))
    else
        aegisub.debug.out("错误：找不到 Python 脚本或 EXE 文件\n")
        f:close()
        return
    end

    f:close()

    -- 执行批处理（包含媒体提取和制卡）
    aegisub.debug.out("正在制卡...\n")
    os.execute('cmd /c "' .. batch_file .. '"')

    -- 立即返回
    aegisub.debug.out("========================================\n")
    aegisub.debug.out("制卡请求已发送！\n")
    aegisub.debug.out("========================================\n")
    aegisub.debug.out("注意：\n")
    aegisub.debug.out("- 卡片正在后台创建中\n")
    aegisub.debug.out("- 请稍后在 Anki 中查看\n")
    aegisub.debug.out("- 此脚本不支持批量制卡\n")
end

aegisub.register_macro(script_name, script_description, process)
