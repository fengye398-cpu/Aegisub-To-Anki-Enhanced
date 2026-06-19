
local tr = aegisub.gettext

script_name = tr("导出选中字幕行发送到Anki批量制卡")
script_description = tr("Lua+Python混合优化")
script_author = ""
script_version = ""

local function ensureDirectoryExists(path)
    if not path then return false end
    -- 先检查目录是否存在，避免闪烁窗口
    local f = io.open(path .. "/test.tmp", "w")
    if f then
        f:close()
        os.remove(path .. "/test.tmp")
        return true
    end
    -- 目录不存在才创建
    local cmd = string.format('mkdir "%s" 2>nul', path)
    return os.execute(cmd)
end

local function checkFFmpeg()
    -- 跳过检查，假设 FFmpeg 已安装（避免闪烁窗口）
    return true
end

local function readConfig(config_path)
    local file = io.open(config_path, "r")
    if not file then
        -- 创建默认配置文件
        local default_config = [[{
    "deck_name": "Default",
    "model_name": "Basic",
    "extraction_mode": "audio_snapshot_video",
    "video_crf": 24,
    "video_preset": "veryfast",
    "audio_bitrate": "128k",
    "snapshot_quality": 3,
    "show_window": false,
    "field": {
        "Audio": "Audio",
        "Video": "Video",
        "SnapShot": "Snapshot",
        "Expression": "Expression",
        "Meaning": "Meaning",
        "Note": "Notes"
    }
}]]
        local f = io.open(config_path, "w")
        if f then
            f:write(default_config)
            f:close()
        end
        file = io.open(config_path, "r")
        if not file then
            return nil
        end
    end

    local content = file:read("*a")
    file:close()

    return {
        deck_name = content:match('"deck_name"%s*:%s*"([^"]+)"') or "Default",
        model_name = content:match('"model_name"%s*:%s*"([^"]+)"') or "Basic",
        extraction_mode = content:match('"extraction_mode"%s*:%s*"([^"]+)"') or "audio_snapshot_video",
        video_crf = tonumber(content:match('"video_crf"%s*:%s*(%d+)')) or 24,
        video_preset = content:match('"video_preset"%s*:%s*"([^"]+)"') or "veryfast",
        audio_bitrate = content:match('"audio_bitrate"%s*:%s*"([^"]+)"') or "128k",
        snapshot_quality = tonumber(content:match('"snapshot_quality"%s*:%s*(%d+)')) or 3,
        show_window = (content:match('"show_window"%s*:%s*(%a+)') == "true")
    }
end

local function writeConfig(config_path, deck_name, model_name, extraction_mode, video_crf, video_preset, audio_bitrate, snapshot_quality, show_window)
    local file = io.open(config_path, "r")
    if not file then
        return false
    end

    local content = file:read("*a")
    file:close()

    -- 行级替换，保留注释和格式
    content = content:gsub('"deck_name"%s*:%s*"[^"]*"', '"deck_name": "' .. deck_name .. '"')
    content = content:gsub('"model_name"%s*:%s*"[^"]*"', '"model_name": "' .. model_name .. '"')
    content = content:gsub('"extraction_mode"%s*:%s*"[^"]*"', '"extraction_mode": "' .. extraction_mode .. '"')
    content = content:gsub('"video_crf"%s*:%s*%d+', '"video_crf": ' .. video_crf)
    content = content:gsub('"video_preset"%s*:%s*"[^"]*"', '"video_preset": "' .. video_preset .. '"')
    content = content:gsub('"audio_bitrate"%s*:%s*"[^"]*"', '"audio_bitrate": "' .. audio_bitrate .. '"')
    content = content:gsub('"snapshot_quality"%s*:%s*%d+', '"snapshot_quality": ' .. snapshot_quality)
    content = content:gsub('"show_window"%s*:%s*%a+', '"show_window": ' .. tostring(show_window))

    file = io.open(config_path, "w")
    if not file then
        return false
    end

    file:write(content)
    file:close()

    return true
end

local function showConfigDialog(config_path)
    local config = readConfig(config_path)
    if not config then
        aegisub.debug.out("错误：无法读取配置文件\n")
        return nil
    end

    -- 构建对话框
    local dialog_config = {
        {class="label", label="牌组名称:", x=0, y=0, width=1, height=1},
        {class="edit", name="deck_name", value="", x=1, y=0, width=3, height=1,
         hint="留空则使用当前配置: " .. config.deck_name},

        {class="label", label="模板名称:", x=0, y=1, width=1, height=1},
        {class="edit", name="model_name", value="", x=1, y=1, width=3, height=1,
         hint="留空则使用当前配置: " .. config.model_name},

        {class="label", label="提取模式:", x=0, y=2, width=1, height=1},
        {class="dropdown", name="extraction_mode", x=1, y=2, width=3, height=1,
         items={"audio_snapshot_video", "audio_snapshot", "audio"},
         value=config.extraction_mode or "audio_snapshot_video"},

        {class="label", label="", x=0, y=3, width=4, height=1},

        {class="label", label="视频CRF质量 (0-51):", x=0, y=4, width=1, height=1},
        {class="intedit", name="video_crf", value=config.video_crf, min=0, max=51, x=1, y=4, width=1, height=1},
        {class="label", label="越小质量越高，默认:24", x=2, y=4, width=2, height=1},

        {class="label", label="视频编码预设:", x=0, y=5, width=1, height=1},
        {class="dropdown", name="video_preset", value=config.video_preset,
         items={"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"},
         x=1, y=5, width=1, height=1},
        {class="label", label="越慢质量越好，默认:veryfast", x=2, y=5, width=2, height=1},

        {class="label", label="音频比特率:", x=0, y=6, width=1, height=1},
        {class="dropdown", name="audio_bitrate", value=config.audio_bitrate,
         items={"64k", "96k", "128k", "192k", "256k"},
         x=1, y=6, width=1, height=1},
        {class="label", label="越高音质越好，默认:128k", x=2, y=6, width=2, height=1},

        {class="label", label="截图质量 (1-31):", x=0, y=7, width=1, height=1},
        {class="intedit", name="snapshot_quality", value=config.snapshot_quality, min=1, max=31, x=1, y=7, width=1, height=1},
        {class="label", label="越小质量越高，默认:3", x=2, y=7, width=2, height=1},

        {class="checkbox", name="show_window", label="手动关闭CMD窗口", value=config.show_window, x=0, y=8, width=2, height=1},

        {class="label", label="提示: 留空则使用当前配置", x=0, y=9, width=4, height=1}
    }

    -- 显示对话框
    local button, result = aegisub.dialog.display(dialog_config, {"确定", "取消", "帮助"})

    if button == "帮助" then
        -- 显示帮助对话框
        local help_text = [[
配置参数说明:

【提取模式 extraction_mode】
  • audio_snapshot_video = 音频+截图+视频（完整）
  • audio_snapshot = 音频+截图（较快）
  • audio = 仅音频（最快）

【视频质量 video_crf (0-51)】
  数值越小质量越高，文件越大
  • 18 = 高质量（文件较大）
  • 24 = 标准质量（推荐，默认）
  • 28 = 较低质量（文件较小）

【视频编码预设 video_preset】
  越慢质量越好，编码时间越长
  • veryfast = 快速编码（推荐，默认）
  • fast = 平衡速度和质量
  • medium = 较慢但质量更好

【音频比特率 audio_bitrate】
  越高音质越好，文件越大
  • 128k = 标准质量（推荐，默认）
  • 192k = 高质量
  • 256k = 很高质量

【截图质量 snapshot_quality (1-31)】
  数值越小质量越高
  • 2-3 = 高质量（推荐，默认3）
  • 5 = 标准质量
  • 10+ = 较低质量

【性能说明】
  • 方案3：Lua生成批处理 + Python并行执行
  • 窗口闪烁：3次（可接受）
  • 批量速度：~0.43秒/张（349张测试）
  • 单张速度：~5秒（含启动开销）

【配置文件位置】
  C:\Users\用户名\AppData\Roaming\Aegisub\toanki_temp\config.json
]]
        local help_dialog = {
            {class="textbox", name="help", value=help_text, x=0, y=0, width=30, height=20}
        }
        aegisub.dialog.display(help_dialog, {"关闭"})
        -- 递归调用，重新显示配置对话框
        return showConfigDialog(config_path)
    end

    if not button or button == "取消" then
        return nil  -- 用户取消
    end

    -- 处理用户输入（留空则使用原配置）
    local new_deck = result.deck_name
    local new_model = result.model_name
    local new_mode = result.extraction_mode

    if new_deck == "" then
        new_deck = config.deck_name
    end
    if new_model == "" then
        new_model = config.model_name
    end

    return {
        deck_name = new_deck,
        model_name = new_model,
        extraction_mode = new_mode,
        video_crf = result.video_crf,
        video_preset = result.video_preset,
        audio_bitrate = result.audio_bitrate,
        snapshot_quality = result.snapshot_quality,
        show_window = result.show_window
    }
end

function process(subtitles, selected_lines, active_line)
    local proj = aegisub.project_properties()

    if #selected_lines == 0 then
        aegisub.debug.out("请至少选择一行字幕！")
        return
    end

    local aegisub_dir = aegisub.decode_path("?user")
    local output_dir = aegisub_dir .. "/toanki_temp/"
    ensureDirectoryExists(output_dir)

    local config_path = output_dir .. "config.json"

    -- 显示配置GUI对话框
    local user_config = showConfigDialog(config_path)
    if not user_config then
        return  -- 用户取消，不执行操作
    end

    -- 保存配置到文件
    writeConfig(config_path, user_config.deck_name, user_config.model_name,
                user_config.extraction_mode, user_config.video_crf,
                user_config.video_preset, user_config.audio_bitrate,
                user_config.snapshot_quality, user_config.show_window)

    local config = user_config

    local line_count = #selected_lines
    aegisub.debug.out("\n========================================\n")
    aegisub.debug.out(string.format("批量处理模式：选中 %d 行字幕\n", line_count))
    aegisub.debug.out(string.format("牌组: %s\n", config.deck_name))
    aegisub.debug.out(string.format("模板: %s\n", config.model_name))
    aegisub.debug.out(string.format("提取模式: %s\n", config.extraction_mode))
    aegisub.debug.out("========================================\n\n")

    -- 检查视频/音频状态
    local has_video = proj.video_file ~= nil and proj.video_file ~= ""
    local has_audio = proj.audio_file ~= nil and proj.audio_file ~= ""

    if not has_video and not has_audio then
        aegisub.debug.out("错误：未找到视频或音频文件！")
        return
    end

    if not checkFFmpeg() then
        aegisub.debug.out("错误：FFmpeg未安装或不在系统路径中！")
        return
    end

    -- 确定输入文件
    local input_file = ""
    if has_video then
        input_file = proj.video_file
    else
        input_file = proj.audio_file
    end

    -- 提取视频文件名（不含扩展名）
    local video_name = ""
    if input_file ~= "" then
        local filename = input_file:match("([^/\\]+)$")
        if filename then
            video_name = filename:match("(.+)%..+$") or filename
        end
    end

    local batch_start_time = os.time()

    aegisub.debug.out("生成批量任务...\n")
    aegisub.debug.out(string.format("提取参数: CRF=%d, preset=%s, audio=%s, snapshot=%d\n\n",
                      config.video_crf, config.video_preset,
                      config.audio_bitrate, config.snapshot_quality))
    local bat_file = output_dir .. "ffmpeg_batch.bat"
    local bat = io.open(bat_file, "w")
    bat:write("@echo off\n")

    local tasks = {}
    for i, line_index in ipairs(selected_lines) do
        local current_line = subtitles[line_index]
        local audio_path = output_dir .. "aegisub_audio_temp_" .. i .. ".mp3"
        local snapshot_path = output_dir .. "aegisub_snapshot_temp_" .. i .. ".jpg"
        local video_path = output_dir .. "aegisub_video_temp_" .. i .. ".mp4"

        local start_sec = current_line.start_time / 1000.0
        local duration = (current_line.end_time - current_line.start_time) / 1000.0

        aegisub.debug.out(string.format("[%d/%d] 添加字幕行 #%d: %s\n", i, line_count, line_index, current_line.text))

        bat:write(string.format('start "" /B /WAIT ffmpeg -y -ss %.3f -i "%s" -t %.3f -vn -c:a libmp3lame -b:a %s "%s" >nul 2>&1\n',
            start_sec, input_file, duration, config.audio_bitrate, audio_path))
        bat:write(string.format('start "" /B /WAIT ffmpeg -y -ss %.3f -i "%s" -vframes 1 -q:v %d "%s" >nul 2>&1\n',
            start_sec, input_file, config.snapshot_quality, snapshot_path))
        if config.extraction_mode == "audio_snapshot_video" then
            bat:write(string.format('start "" /B /WAIT ffmpeg -y -ss %.3f -i "%s" -t %.3f -c:v libx264 -crf %d -preset %s -pix_fmt yuv420p -c:a aac -b:a %s -ac 2 "%s" >nul 2>&1\n',
                start_sec, input_file, duration, config.video_crf, config.video_preset, config.audio_bitrate, video_path))
        end

        local meaning_escaped = current_line.text:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r')
        table.insert(tasks, {
            video_name = video_name,
            start_time = current_line.start_time,
            end_time = current_line.end_time,
            meaning = meaning_escaped,
            audio = audio_path:gsub("\\", "/"),
            snapshot = snapshot_path:gsub("\\", "/"),
            video = video_path:gsub("\\", "/"),
            extraction_mode = config.extraction_mode,
            video_crf = config.video_crf,
            video_preset = config.video_preset,
            audio_bitrate = config.audio_bitrate,
            snapshot_quality = config.snapshot_quality,
            ffmpeg_batch = bat_file:gsub("\\", "/")
        })
    end
    bat:close()

    -- 生成任务JSON
    local batch_queue_file = output_dir .. "batch_queue.json"
    local json_file = io.open(batch_queue_file, "w")
    json_file:write("[\n")
    for i, task in ipairs(tasks) do
        json_file:write("  {\n")
        json_file:write(string.format('    "video_name": "%s",\n', task.video_name))
        json_file:write(string.format('    "start_time": %d,\n', task.start_time))
        json_file:write(string.format('    "end_time": %d,\n', task.end_time))
        json_file:write(string.format('    "meaning": "%s",\n', task.meaning))
        json_file:write(string.format('    "audio": "%s",\n', task.audio))
        json_file:write(string.format('    "snapshot": "%s",\n', task.snapshot))
        json_file:write(string.format('    "video": "%s",\n', task.video))
        json_file:write(string.format('    "extraction_mode": "%s",\n', task.extraction_mode))
        json_file:write(string.format('    "video_crf": %d,\n', task.video_crf))
        json_file:write(string.format('    "video_preset": "%s",\n', task.video_preset))
        json_file:write(string.format('    "audio_bitrate": "%s",\n', task.audio_bitrate))
        json_file:write(string.format('    "snapshot_quality": %d,\n', task.snapshot_quality))
        json_file:write(string.format('    "ffmpeg_batch": "%s"\n', task.ffmpeg_batch))
        if i < #tasks then
            json_file:write("  },\n")
        else
            json_file:write("  }\n")
        end
    end
    json_file:write("]\n")
    json_file:close()

    -- 调用Python处理（只闪1次窗口）
    aegisub.debug.out("\n开始批量上传...\n")
    local py_file = output_dir .. "Aegisub_to_Anki.py"
    local exe_file = output_dir .. "Aegisub_to_Anki.exe"
    local status_file = output_dir .. "toanki_status.txt"
    local temp_stderr = output_dir .. "toanki_stderr.txt"

    local cmd = ""
    local py_exists = io.open(py_file, "r")
    if py_exists then
        py_exists:close()
        aegisub.debug.out("使用 Python 模式（开发）\n")
        if user_config.show_window then
            cmd = string.format('cmd /k "python "%s" --batch "%s" 2>&1 && pause"', py_file, batch_queue_file)
        else
            cmd = string.format('cmd /c "python "%s" --batch "%s" 2>"%s""', py_file, batch_queue_file, temp_stderr)
        end
    else
        aegisub.debug.out("使用 EXE 模式（生产）\n")
        if user_config.show_window then
            cmd = string.format('cmd /k ""%s" --batch "%s" 2>&1 && pause"', exe_file, batch_queue_file)
        else
            cmd = string.format('cmd /c ""%s" --batch "%s" 2>"%s""', exe_file, batch_queue_file, temp_stderr)
        end
    end
    os.execute(cmd)

    -- 时间格式化函数：秒 -> 时分秒
    local function format_time(seconds)
        local hours = math.floor(seconds / 3600)
        local minutes = math.floor((seconds % 3600) / 60)
        local secs = math.floor(seconds % 60)

        if hours > 0 then
            return string.format("%d小时%d分%d秒", hours, minutes, secs)
        elseif minutes > 0 then
            return string.format("%d分%d秒", minutes, secs)
        else
            return string.format("%d秒", secs)
        end
    end

    -- 读取状态文件获取结果
    local success_count = 0
    local total_count = 0
    local batch_time = 0

    local status = io.open(status_file, "r")
    if status then
        local content = status:read("*a")
        status:close()

        -- 解析成功/总数
        success_count = tonumber(content:match("success=(%d+)")) or 0
        total_count = tonumber(content:match("total=(%d+)")) or 0
        batch_time = tonumber(content:match("time=([%d%.]+)")) or 0
    end

    local fail_count = total_count - success_count
    local batch_end_time = os.time()
    local total_time = batch_end_time - batch_start_time

    -- 如果os.time()精度不够(显示0秒),使用batch_time作为最小值
    if total_time == 0 and batch_time > 0 then
        total_time = math.ceil(batch_time)
    end

    aegisub.debug.out("\n========================================\n")
    aegisub.debug.out("批量处理完成\n")
    aegisub.debug.out(string.format("成功: %d 张卡片\n", success_count))
    aegisub.debug.out(string.format("失败: %d 张卡片\n", fail_count))
    aegisub.debug.out(string.format("总计: %d 张卡片\n", line_count))
    if batch_time > 0 then
        aegisub.debug.out(string.format("制卡用时: %s\n", format_time(batch_time)))
    end
    aegisub.debug.out(string.format("总用时: %s (含媒体提取)\n", format_time(total_time)))
    aegisub.debug.out("========================================\n")

    -- 检查stderr文件判断是否制卡成功，并显示重复卡片信息
    local stderr_file = io.open(temp_stderr, "r")
    if stderr_file then
        local stderr_content = stderr_file:read("*a")
        stderr_file:close()

        -- 显示重复卡片信息（使用标记避免编码问题）
        if stderr_content then
            local dup_count = stderr_content:match("DUPLICATE_COUNT:(%d+)")
            if dup_count then
                aegisub.debug.out(string.format("\n发现 %s 张重复卡片:\n", dup_count))
                for line in stderr_content:gmatch("[^\r\n]+") do
                    local card_num, card_text = line:match("DUPLICATE_CARD:(%d+):(.+)")
                    if card_num and card_text then
                        aegisub.debug.out(string.format("  #%s: %s\n", card_num, card_text))
                    end
                    local more_count = line:match("DUPLICATE_MORE:(%d+)")
                    if more_count then
                        aegisub.debug.out(string.format("  ... 还有 %s 张\n", more_count))
                    end
                end
            end
        end

        -- 检查 FFmpeg 错误
        if stderr_content and stderr_content:match("FFMPEG_NOT_FOUND") then
            aegisub.debug.out("\n========================================\n")
            aegisub.debug.out("错误：未找到 FFmpeg\n")
            aegisub.debug.out("========================================\n")
            aegisub.debug.out("请按照以下步骤安装 FFmpeg:\n\n")
            aegisub.debug.out("方法1: 使用包管理器\n")
            aegisub.debug.out("  Windows (Chocolatey): choco install ffmpeg\n\n")
            aegisub.debug.out("方法2: 手动下载（推荐）\n")
            aegisub.debug.out("  1. 访问 https://ffmpeg.org/download.html\n")
            aegisub.debug.out("  2. 下载适合您系统的 FFmpeg\n")
            aegisub.debug.out("  3. 解压并将 ffmpeg.exe 添加到系统 PATH\n\n")
            aegisub.debug.out("方法3: 便携版\n")
            aegisub.debug.out("  将 ffmpeg.exe 放在 Python 脚本同目录\n")
            aegisub.debug.out("========================================\n")
            return
        end

        -- 如果stderr中没有"Batch created:"，说明验证失败或其他错误
        if stderr_content and not stderr_content:match("Batch created:") then
            aegisub.debug.out("\n========================================\n")
            aegisub.debug.out("制卡失败\n")
            aegisub.debug.out("========================================\n")
            aegisub.debug.out("请检查:\n")
            aegisub.debug.out("1. Anki是否正在运行\n")
            aegisub.debug.out("2. AnkiConnect插件是否已安装并启用\n")
            aegisub.debug.out("3. 牌组名称是否正确: " .. config.deck_name .. "\n")
            aegisub.debug.out("4. 模板名称是否正确: " .. config.model_name .. "\n")
            return
        end
    end

    if fail_count > 0 then
        aegisub.debug.out("\n部分卡片创建失败，请检查:\n")
        aegisub.debug.out("1. Anki是否正在运行\n")
        aegisub.debug.out("2. AnkiConnect是否已安装并启用\n")
        aegisub.debug.out("3. 配置文件是否正确\n")
        aegisub.debug.out("4. 是否有部分卡片重复制卡\n")
    end
end

aegisub.register_macro(script_name, script_description, process)
