from pydantic import BaseModel
from typing import Optional


class ChatMessage(BaseModel):
    message: str
    session_id: str
    user_name: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    session_id: str
    step: Optional[int] = None


class ExcelDownloadRequest(BaseModel):
    session_id: str


class HealthResponse(BaseModel):
    status: str
    engine: str
    model: str
