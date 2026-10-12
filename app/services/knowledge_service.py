"""RAG 知识库：文档解析 → 切分 → 向量化 → 相似度检索。

用 Chroma 做本地向量库，OpenAI Embeddings 做向量化；
两者均懒加载，缺少 API Key 时（如跑测试）不会在导入期崩溃。
"""
from io import BytesIO
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# 文本切分器不依赖 API Key，可顶层创建
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

SUPPORTED_EXTENSIONS = frozenset({"txt", "md", "pdf", "docx"})

_embeddings = None
_vector_store = None


def get_embeddings():
    """延迟创建并缓存嵌入模型。"""
    global _embeddings
    if _embeddings is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("未配置 OPENAI_API_KEY，请在 .env 中填入大模型 API Key")
        _embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _embeddings


def get_vector_store():
    """延迟创建并缓存向量库。"""
    global _vector_store
    if _vector_store is None:
        _vector_store = Chroma(
            persist_directory=settings.CHROMA_PERSIST_DIR,
            embedding_function=get_embeddings(),
            collection_name="knowledge",
        )
    return _vector_store


def validate_filename(filename: str) -> str:
    """校验文件名并返回小写扩展名，不支持的类型抛 ValueError。"""
    if not filename or "." not in filename:
        raise ValueError("不支持的文件类型，仅支持 txt / md / pdf / docx")
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型：{ext}")
    return ext


def parse_file(filename: str, content: bytes) -> str:
    """把上传文件解析为纯文本，支持 txt / md / pdf / docx。"""
    ext = validate_filename(filename)
    if ext in ("txt", "md"):
        return content.decode("utf-8", errors="ignore")
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == "docx":
        from docx import Document

        doc = Document(BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"不支持的文件类型：{ext}")


def add_document(filename: str, content: bytes, owner_id: int) -> int:
    """解析文档并替换该用户同名文档的向量块，返回切分块数量。"""
    text = parse_file(filename, content)
    if not text.strip():
        raise ValueError("文档内容为空或无法提取文本")

    chunks = [chunk for chunk in splitter.split_text(text) if chunk.strip()]
    if not chunks:
        raise ValueError("文档内容为空或无法切分出有效文本")

    # 先按 租户+文件名 清理旧块：固定 chunk id 在块数变少时会遗留旧数据
    vector_store = get_vector_store()
    vector_store.delete(
        where={
            "$and": [
                {"owner_id": {"$eq": owner_id}},
                {"source": {"$eq": filename}},
            ]
        }
    )

    vector_store.add_texts(
        chunks,
        metadatas=[{"source": filename, "owner_id": owner_id} for _ in chunks],
        ids=[f"{owner_id}-{filename}-{i}" for i in range(len(chunks))],
    )
    return len(chunks)


def retrieve_for_query(query: str, owner_id: int, k: int = 3) -> str:
    """检索当前用户的知识片段；强制按 owner_id 隔离，不提供跨租户检索。"""
    if not isinstance(owner_id, int) or isinstance(owner_id, bool) or owner_id <= 0:
        raise ValueError("owner_id 必须是有效的正整数")
    if not query.strip():
        return ""
    if k < 1 or k > settings.MAX_KNOWLEDGE_K:
        raise ValueError(f"k 必须在 1 到 {settings.MAX_KNOWLEDGE_K} 之间")
    results = get_vector_store().similarity_search(
        query, k=k, filter={"owner_id": owner_id}
    )
    return "\n\n".join(doc.page_content for doc in results)
