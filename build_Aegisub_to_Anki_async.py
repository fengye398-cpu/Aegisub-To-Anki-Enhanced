#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aegisub_to_Anki_async打包配置脚本
使用PyInstaller打包Aegisub_to_Anki_async为单文件exe
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


class Aegisub_to_Anki_asyncBuilder:
    """Aegisub_to_Anki_async打包配置管理器"""

    def __init__(self):
        self.app_name = "Aegisub_to_Anki_async"
        self.version = "1.0.0"
        self.base_dir = Path(__file__).parent
        self.dist_dir = self.base_dir / "dist"
        self.build_dir = self.base_dir / "build"
        self.spec_file = self.base_dir / f"{self.app_name}.spec"

    def get_pyinstaller_args(self, show_console=True):
        """获取PyInstaller打包参数

        Args:
            show_console: 是否显示控制台窗口(True=显示, False=隐藏)
        """
        args = [
            "pyinstaller",
            "--name", self.app_name,
            "--onefile",  # 打包成单个exe文件
            "--clean",    # 清理临时文件
        ]

        # 控制台显示设置
        if show_console:
            args.append("--console")  # 显示控制台
        else:
            args.append("--noconsole")  # 隐藏控制台(也可用--windowed)

        # 图标设置
        icon_file = self.base_dir / "Aegisub_to_Anki_async.ico"
        if icon_file.exists():
            args.extend(["--icon", str(icon_file)])

        # 主程序入口
        args.append(str(self.base_dir / "Aegisub_to_Anki_async.py"))

        return args

    def check_dependencies(self):
        """检查打包依赖"""
        print("检查打包依赖...")

        # 检查PyInstaller
        try:
            import PyInstaller
            print(f"[OK] PyInstaller: {PyInstaller.__version__}")
        except ImportError:
            print("[ERROR] PyInstaller未安装，请运行: pip install pyinstaller")
            return False

        # 检查图标文件
        icon_file = self.base_dir / "Aegisub_to_Anki_async.ico"
        if icon_file.exists():
            print(f"[OK] 图标文件: {icon_file}")
        else:
            print(f"[WARN] 图标文件不存在: {icon_file} (将使用默认图标)")

        # 检查主程序
        main_file = self.base_dir / "Aegisub_to_Anki_async.py"
        if main_file.exists():
            print(f"[OK] 主程序: {main_file}")
        else:
            print(f"[ERROR] 主程序不存在: {main_file}")
            return False

        return True

    def clean_build_files(self):
        """清理构建文件"""
        print("清理构建文件...")

        dirs_to_clean = [self.build_dir, self.dist_dir]
        files_to_clean = [self.spec_file]

        for dir_path in dirs_to_clean:
            if dir_path.exists():
                shutil.rmtree(dir_path)
                print(f"[OK] 已删除目录: {dir_path}")

        for file_path in files_to_clean:
            if file_path.exists():
                file_path.unlink()
                print(f"[OK] 已删除文件: {file_path}")

    def build_application(self, show_console=True):
        """构建应用程序

        Args:
            show_console: 是否显示控制台窗口(True=显示, False=隐藏)
        """
        print(f"开始构建 {self.app_name} v{self.version}")
        print("=" * 60)

        # 检查依赖
        if not self.check_dependencies():
            print("依赖检查失败，无法继续构建")
            return False

        print()

        try:
            # 使用命令行参数构建
            cmd = self.get_pyinstaller_args(show_console=show_console)

            console_mode = "显示控制台" if show_console else "隐藏控制台(无窗口)"
            print(f"打包模式: 单文件exe, {console_mode}")
            print(f"执行命令: {' '.join(cmd)}")
            print()

            # 执行构建
            result = subprocess.run(cmd, cwd=self.base_dir)

            if result.returncode == 0:
                print("\n" + "=" * 60)
                print("构建成功！")
                print("=" * 60)

                # 检查输出文件
                exe_file = self.dist_dir / f"{self.app_name}.exe"
                if exe_file.exists():
                    size_mb = exe_file.stat().st_size / (1024 * 1024)
                    print(f"\n输出文件: {exe_file}")
                    print(f"文件大小: {size_mb:.1f} MB")
                    print(f"控制台模式: {console_mode}")

                    # 检查图标
                    icon_file = self.base_dir / "Aegisub_to_Anki_async.ico"
                    if icon_file.exists():
                        print("图标状态: 已嵌入自定义图标")
                    else:
                        print("图标状态: 使用默认图标")

                    print(f"\n反馈邮箱: 1490226031@qq.com")
                    return True
                else:
                    print(f"输出文件不存在: {exe_file}")
                    return False
            else:
                print("\n构建失败！")
                return False

        except Exception as e:
            print(f"构建过程中出错: {e}")
            return False


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Aegisub_to_Anki_async打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python build_Aegisub_to_Anki_async.py              # 打包带控制台的exe
  python build_Aegisub_to_Anki_async.py --no-console # 打包无控制台的exe
  python build_Aegisub_to_Anki_async.py --clean      # 清理构建文件
  python build_Aegisub_to_Anki_async.py --check      # 仅检查依赖
        """
    )
    parser.add_argument(
        "--no-console",
        action="store_true",
        help="隐藏控制台窗口(默认显示)"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理构建文件"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查依赖"
    )

    args = parser.parse_args()

    builder = Aegisub_to_Anki_asyncBuilder()

    if args.clean:
        builder.clean_build_files()
        return

    if args.check:
        builder.check_dependencies()
        return

    # 构建应用程序
    show_console = not args.no_console
    success = builder.build_application(show_console=show_console)

    if success:
        print("\n打包完成！")
    else:
        print("\n打包失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()
