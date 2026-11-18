"""Storage. MongoRepo is the real backend (MongoDB Atlas). MemoryRepo has the
same methods and is used for tests and for quick local runs without a database.
Every document, chunk and summary lookup is scoped by user_id."""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DuplicateEmail(Exception):
    pass


class MemoryRepo:
    kind = "memory"

    def __init__(self):
        self.users: Dict[str, Dict] = {}
        self.documents: Dict[str, Dict] = {}
        self.chunks: List[Dict] = []
        self.summaries: List[Dict] = []
        self.audits: Dict[str, Dict] = {}

    # users
    def create_user(self, name: str, email: str, pw_hash: str) -> Dict:
        if self.find_user_by_email(email):
            raise DuplicateEmail(email)
        uid = uuid.uuid4().hex
        self.users[uid] = {"id": uid, "name": name, "email": email, "pw_hash": pw_hash, "created": now_iso()}
        return self.users[uid]

    def find_user_by_email(self, email: str) -> Optional[Dict]:
        return next((u for u in self.users.values() if u["email"] == email), None)

    def get_user(self, user_id: str) -> Optional[Dict]:
        return self.users.get(user_id)

    # documents
    def add_document(self, doc: Dict) -> str:
        doc_id = uuid.uuid4().hex
        self.documents[doc_id] = {**doc, "id": doc_id}
        return doc_id

    def get_document(self, user_id: str, doc_id: str) -> Optional[Dict]:
        d = self.documents.get(doc_id)
        return d if d and d["user_id"] == user_id else None

    def list_documents(self, user_id: str) -> List[Dict]:
        docs = [{k: v for k, v in d.items() if k != "text"}
                for d in self.documents.values() if d["user_id"] == user_id]
        return sorted(docs, key=lambda d: d["created"], reverse=True)

    def delete_document(self, user_id: str, doc_id: str) -> bool:
        if not self.get_document(user_id, doc_id):
            return False
        del self.documents[doc_id]
        self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
        self.summaries = [s for s in self.summaries if s["doc_id"] != doc_id]
        return True

    # chunks
    def add_chunks(self, chunks: List[Dict]) -> None:
        self.chunks.extend(chunks)

    def get_chunks(self, user_id: str, doc_id: str) -> List[Dict]:
        rows = [c for c in self.chunks if c["user_id"] == user_id and c["doc_id"] == doc_id]
        return sorted(rows, key=lambda c: c["idx"])

    # summaries
    def add_summary(self, rec: Dict) -> None:
        self.summaries.append(rec)

    def list_summaries(self, user_id: str) -> List[Dict]:
        return [s for s in self.summaries if s["user_id"] == user_id]

    # audits
    def save_audit(self, user_id: str, result: Dict) -> None:
        self.audits[user_id] = result

    def latest_audit(self, user_id: str) -> Optional[Dict]:
        return self.audits.get(user_id)


class MongoRepo:
    kind = "mongodb"

    def __init__(self, uri: str, db_name: str):
        from pymongo import ASCENDING, DESCENDING, MongoClient
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.client.admin.command("ping")  # fail fast with a clear error
        self.db = self.client[db_name]
        self.db.users.create_index("email", unique=True)
        self.db.documents.create_index([("user_id", ASCENDING), ("created", DESCENDING)])
        self.db.chunks.create_index([("user_id", ASCENDING), ("doc_id", ASCENDING), ("idx", ASCENDING)])
        self.db.summaries.create_index([("user_id", ASCENDING), ("created", DESCENDING)])

    @staticmethod
    def _oid(value: str):
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            return ObjectId(value)
        except (InvalidId, TypeError):
            return None

    @staticmethod
    def _out(doc: Optional[Dict]) -> Optional[Dict]:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return doc

    # users
    def create_user(self, name: str, email: str, pw_hash: str) -> Dict:
        from pymongo.errors import DuplicateKeyError
        rec = {"name": name, "email": email, "pw_hash": pw_hash, "created": now_iso()}
        try:
            res = self.db.users.insert_one(rec)
        except DuplicateKeyError:
            raise DuplicateEmail(email)
        return {**rec, "id": str(res.inserted_id)}

    def find_user_by_email(self, email: str) -> Optional[Dict]:
        return self._out(self.db.users.find_one({"email": email}))

    def get_user(self, user_id: str) -> Optional[Dict]:
        oid = self._oid(user_id)
        return self._out(self.db.users.find_one({"_id": oid})) if oid else None

    # documents
    def add_document(self, doc: Dict) -> str:
        return str(self.db.documents.insert_one(dict(doc)).inserted_id)

    def get_document(self, user_id: str, doc_id: str) -> Optional[Dict]:
        oid = self._oid(doc_id)
        return self._out(self.db.documents.find_one({"_id": oid, "user_id": user_id})) if oid else None

    def list_documents(self, user_id: str) -> List[Dict]:
        cur = self.db.documents.find({"user_id": user_id}, {"text": 0}).sort("created", -1)
        return [self._out(d) for d in cur]

    def delete_document(self, user_id: str, doc_id: str) -> bool:
        oid = self._oid(doc_id)
        if not oid or not self.db.documents.find_one({"_id": oid, "user_id": user_id}, {"_id": 1}):
            return False
        self.db.documents.delete_one({"_id": oid, "user_id": user_id})
        self.db.chunks.delete_many({"doc_id": doc_id, "user_id": user_id})
        self.db.summaries.delete_many({"doc_id": doc_id, "user_id": user_id})
        return True

    # chunks
    def add_chunks(self, chunks: List[Dict]) -> None:
        if chunks:
            self.db.chunks.insert_many([dict(c) for c in chunks])

    def get_chunks(self, user_id: str, doc_id: str) -> List[Dict]:
        return list(self.db.chunks.find({"user_id": user_id, "doc_id": doc_id}).sort("idx", 1))

    # summaries
    def add_summary(self, rec: Dict) -> None:
        self.db.summaries.insert_one(dict(rec))

    def list_summaries(self, user_id: str) -> List[Dict]:
        return list(self.db.summaries.find({"user_id": user_id}, {"text": 0}))

    # audits
    def save_audit(self, user_id: str, result: Dict) -> None:
        self.db.audits.replace_one({"user_id": user_id}, {"user_id": user_id, **result}, upsert=True)

    def latest_audit(self, user_id: str) -> Optional[Dict]:
        doc = self.db.audits.find_one({"user_id": user_id}, {"_id": 0, "user_id": 0})
        return doc
