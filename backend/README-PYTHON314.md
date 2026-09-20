# Python 3.14 安装说明

旧依赖中 `pydantic==2.9.2` 会固定到较旧的 `pydantic-core`。在 Python 3.14 / Windows 环境里可能找不到匹配 wheel，从而触发 Rust/maturin 本地编译并失败。

本修正版依赖：
- FastAPI 0.136.1
- Pydantic 2.12.5
- Uvicorn 0.53.0
- SQLAlchemy 2.0.54

PowerShell：

```powershell
cd backend
.\\setup_backend.ps1
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8000
```

访问：
- http://127.0.0.1:8000/api/health
- http://127.0.0.1:8000/docs
