"""用脚本方式启动 uvicorn（等价于 python -m uvicorn app.main:app --port 8000）。

提供这个文件是为了让 PyCharm 的 Run Configuration 不依赖"模块模式"，
解释器配好后点一下就能跑。依赖：pip install -r backend/requirements.txt

端口：默认 8000，可用环境变量 PORT 改（例：PORT=8001）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402  ← 未安装 fastapi/uvicorn 时会在这里报 ImportError

PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=False)
    except OSError as e:
        print(
            f"\n[启动失败] 端口 {PORT} 被占用：{e}\n"
            f"  · 看看是否已经有别的服务在跑（PyCharm 里另一个配置、或之前的进程没关掉）\n"
            f"  · 或者换端口：在本配置的 Environment variables 里加 PORT=8001\n"
            f"  · 也可以直接用「零依赖 serve.py」那套配置，它不需要 fastapi\n"
        )
        sys.exit(1)
