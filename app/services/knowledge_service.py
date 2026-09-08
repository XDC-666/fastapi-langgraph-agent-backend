"""RAG 知识库：文档解析 → 切分 → 向量化 → 相似度检索。

使用 Chroma 作为轻量本地向量库，OpenAI Embeddings 做向量化。
嵌入模型与向量库均懒加载，避免在缺少 API Key 时（如运行测试）就崩溃。
"""
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

# 确保本地数据目录存在
Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# 文本切分器（不依赖 API Key，可顶层创建）
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

# 懒加载缓存
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


def parse_file(filename: str, content: bytes) -> str:
    """把上传文件解析为纯文本，支持 txt / md / pdf / docx。"""
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ("txt", "md"):
        return content.decode("utf-8", errors="ignore")
    if ext == "pdf":
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == "docx":
        from io import BytesIO

        from docx import Document

        doc = Document(BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"不支持的文件类型：{ext}")


def add_document(filename: str, content: bytes, owner_id: int) -> int:
    """解析并向量化一个文档，返回切分块数量。"""
    text = parse_file(filename, content)
    chunks = splitter.split_text(text)
    metadatas = [{"source": filename, "owner_id": owner_id} for _ in chunks]
    ids = [f"{owner_id}-{filename}-{i}" for i in range(len(chunks))]
    get_vector_store().add_texts(chunks, metadatas=metadatas, ids=ids)
    return len(chunks)


def retrieve_for_query(query: str, owner_id: int | None = None, k: int = 3) -> str:
    """检索与 query 最相关的知识片段，拼接为上下文字符串。"""
    if not query.strip():
        return ""
    if owner_id is not None:
        results = get_vector_store().similarity_search(query, k=k, filter={"owner_id": owner_id})
    else:
        results = get_vector_store().similarity_search(query, k=k)
    return "\n\n".join(doc.page_content for doc in results)
