"""知识库路由：上传文档、基于知识库检索问答。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.knowledge_service import (
    add_document,
    retrieve_for_query,
    validate_filename,
)

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/knowledge", tags=["knowledge"])


class KnowledgeAsk(BaseModel):
    """知识库检索请求。"""

    query: str
    k: int = Field(3, ge=1, le=settings.MAX_KNOWLEDGE_K)


@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传受限大小的 txt/md/pdf/docx 文档并写入当前用户向量库。"""
    filename = file.filename or ""
    try:
        # 先拒绝扩展名，避免对不支持类型做任何大文件读取/解析。
        validate_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    max_bytes = settings.MAX_KNOWLEDGE_UPLOAD_BYTES
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大允许 {max_bytes} 字节",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    try:
        chunks = await run_in_threadpool(add_document, filename, content, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"filename": filename, "chunks": chunks}


@router.post("/ask")
def ask_knowledge(
    payload: KnowledgeAsk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于当前用户上传的知识库做相似度检索，返回上下文。"""
    context = retrieve_for_query(payload.query, owner_id=current_user.id, k=payload.k)
    return {"query": payload.query, "context": context}
