
from pydantic import BaseModel


class ChatMessage(BaseModel):
    message: str
    session_id: str
    user_name: str | None = None


class ChatResponse(BaseModel):
    content: str
    session_id: str
    step: int | None = None


class ExcelDownloadRequest(BaseModel):
    session_id: str


class HealthResponse(BaseModel):
    status: str
    engine: str
    model: str
