"""PyInstaller 入口。

直接以脚本方式执行包内 __main__.py 会破坏相对导入，
因此打包时使用这个顶层入口，通过绝对导入找到 context_cli 包。
"""

from context_cli.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
