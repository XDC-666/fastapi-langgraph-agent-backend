"""知识库路由：上传文档、基于知识库检索问答。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.knowledge_service import add_document, retrieve_for_query

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/knowledge", tags=["knowledge"])


class KnowledgeAsk(BaseModel):
    """知识库检索请求。"""

    query: str
    k: int = 3


@router.post("/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文档（txt/md/pdf/docx），解析并写入向量库。"""
    content = await file.read()
    try:
        chunks = add_document(file.filename, content, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"filename": file.filename, "chunks": chunks}


@router.post("/ask")
def ask_knowledge(
    payload: KnowledgeAsk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """基于当前用户上传的知识库做相似度检索，返回上下文。"""
    context = retrieve_for_query(payload.query, owner_id=current_user.id, k=payload.k)
    return {"query": payload.query, "context": context}
