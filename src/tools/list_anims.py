"""列出 pycozmo 动画资源中的动画名（离线读本地资源，不需连接机器人）。

用法：
  uv run python src/tools/list_anims.py            # 全部动画名
  uv run python src/tools/list_anims.py wake react # 按关键词过滤（OR，忽略大小写）

资源未就绪时先运行：.venv/bin/pycozmo_resources.py download
"""

import sys


def main() -> int:
    import pycozmo

    keywords = [k.lower() for k in sys.argv[1:]]
    cli = pycozmo.Client()  # 不 start/connect，仅用 load_anims 读本地资源元数据
    try:
        cli.load_anims()
    except Exception as e:
        print(f"动画资源未就绪：{e}", file=sys.stderr)
        print("先运行：.venv/bin/pycozmo_resources.py download", file=sys.stderr)
        return 1
    for name in sorted(cli.get_anim_names()):
        if not keywords or any(k in name.lower() for k in keywords):
            print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
