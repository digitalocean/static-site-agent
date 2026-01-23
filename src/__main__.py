import logging
import uuid
import click
import uvicorn
from datetime import datetime
from typing import List, Optional, Any, Dict, Union, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

from agent import Agent
from models import JsonRpcRequest, JsonRpcResponse, Message, Task, TaskStatus, Artifact, ArtifactPart

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("static-site-agent")

app = FastAPI()

# Serve static files for the chat interface
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize the agent
agent = Agent()

@app.get("/", response_class=HTMLResponse)
async def serve_chat_interface():
    """Serve the chat interface."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Static Site Agent</h1><p>Chat interface not found.</p>")

@app.post("/")
async def handle_rpc(request: JsonRpcRequest):
    """Handle JSON-RPC requests."""
    
    if request.method == "message/send":
        try:
            # 1. Parse Input
            params = request.params
            message_data = params.get("message", {})
            user_message = Message(**message_data)
            
            # Extract text
            input_text = ""
            for part in user_message.parts:
                if part.kind == "text" and part.text:
                    input_text += part.text
            
            logger.info(f"Received message: {input_text}")
            
            # 2. Invoke Agent Logic
            response_text = agent.process_message(input_text)
            
            # 3. Construct Response
            task_id = str(uuid.uuid4())
            context_id = str(uuid.uuid4())
            
            artifact = Artifact(
                parts=[ArtifactPart(text=response_text)]
            )
            
            task = Task(
                id=task_id,
                status=TaskStatus(
                    state="completed",
                    timestamp=datetime.now().isoformat()
                ),
                artifacts=[artifact],
                contextId=context_id
            )
            
            return JsonRpcResponse(
                id=request.id,
                result=task
            )
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    else:
        raise HTTPException(status_code=404, detail=f"Method {request.method} not found")

if __name__ == "__main__":
    import click

    @click.command()
    @click.option('--host', 'host', default='0.0.0.0')
    @click.option('--port', 'port', default=8000)
    def main(host: str, port: int):
        uvicorn.run(app, host=host, port=port)

    main()
