from fastapi.staticfiles import StaticFiles
from src.api.main import app
import uvicorn
import os

# Serve the UI
app.mount("/", StaticFiles(directory="src/ui", html=True), name="ui")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
