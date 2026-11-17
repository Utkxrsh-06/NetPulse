"""
NetPulse Backend Server Launcher
Starts the FastAPI backend at http://localhost:8000
"""

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("Starting NetPulse Intelligent Backend Server")
    print("Listening at: http://localhost:8000")
    print("API Documentation: http://localhost:8000/docs")
    print("=" * 60)
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
