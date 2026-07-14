"""app 入口: uvicorn app.main:app --reload """
from os import name

from app.api.server import app

__all__ = ["app"]

if __name__ == '__main__':
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)