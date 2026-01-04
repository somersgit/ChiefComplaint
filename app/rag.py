import os
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader
import chromadb
from chromadb.utils import embedding_functions

# You can switch to OpenAIEmbeddings if desired
USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))

class RAGService:
    def __init__(self, chroma_dir: str, namespace: str):
        self.client = chromadb.PersistentClient(path=chroma_dir)
        self.ns = namespace
        self.collection = None
        self._ensure_collection()

    def _ensure_collection(self):
        if USE_OPENAI:
            ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=os.getenv("OPENAI_API_KEY"),
                model_name="text-embedding-3-small"
            )
        else:
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
        self.collection = self.client.get_or_create_collection(
            name=f"case_{self.ns}",
            embedding_function=ef
        )

    def ensure_index(self, source_path: str):
        if not source_path or not os.path.exists(source_path):
            return
        # If already ingested (doc id exists), skip. Use file mtime as version.
        fid = f"{self.ns}:{os.path.basename(source_path)}:{int(os.path.getmtime(source_path))}"
        existing = self.collection.get(ids=[fid])
        if existing and existing.get("ids"):
            return

        # (Re)ingest
        if source_path.lower().endswith(".txt"):
            loader = TextLoader(source_path, encoding="utf-8")
        else:
            loader = PyPDFLoader(source_path)
        pages = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        docs = text_splitter.split_documents(pages)

        # Clear previous docs for this namespace
        # Note: simplest approach—use prefix filter by metadata
        # (Chroma doesn't support prefix delete directly; we store doc ids uniquely per version).
        ids, texts, metas = [], [], []
        for i, d in enumerate(docs):
            ids.append(f"{fid}:{i}")
            texts.append(d.page_content)
            page = d.metadata.get("page")
            if page is None:
                page = 0
            metas.append({"source": source_path, "ns": self.ns, "page": page})

        # Clean older versions of same PDF namespace
        # (Optional: in production, track versions; here we let embeddings accumulate as files change)
        self.collection.add(ids=ids, documents=texts, metadatas=metas)

    def search(self, query: str, k: int = 4) -> str:
        if not query:
            return ""
        res = self.collection.query(query_texts=[query], n_results=k)
        docs = res.get("documents",[[]])[0]
        snippets = []
        for i, doc in enumerate(docs or []):
            if not doc: continue
            snippets.append(f"[{i+1}] " + doc.strip())
        return "\n\n".join(snippets)
