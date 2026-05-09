from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db
from app.routers import scrape, export, auth

app = FastAPI(title="Threads 留言撈取工具", version="1.0.0")


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(auth.router)
app.include_router(scrape.router)
app.include_router(export.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
