"""用脚本方式启动 uvicorn（等价于 python -m uvicorn app.main:app --reload --port 8000）。

提供这个文件是为了让 PyCharm 的 Run Configuration 不依赖"模块模式"，
解释器配好后点一下就能跑。依赖：pip install -r backend/requirements.txt
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402  ← 未安装 fastapi/uvicorn 时此处会报 ImportError，请先用零依赖配置

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
