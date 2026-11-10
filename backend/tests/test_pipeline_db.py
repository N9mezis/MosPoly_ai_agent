"""Сквозной сценарий на настоящей БД: загрузка → проверка → результат (mock LLM, hashing)."""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from docx import Document as DocxDocument
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.analysis import service as analysis_service
from app.analysis.service import PipelineDeps, run_analysis
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.core.models import Document, LLMCall, RegulationVersion, RegulationVersionStatus
from app.domain.anonymizer import contains_personal_data
from app.domain.models import CheckStatus, LLMChunkResult
from app.knowledge import service as knowledge
from app.knowledge.rerank import NoReranker
from app.llm.calllog import record_call
from app.llm.client import MockLLMClient
from app.llm.embeddings import AsyncHashingEmbedder
from tests.paths import REPO_ROOT

pytestmark = pytest.mark.db

PROBLEMATIC = (
    REPO_ROOT / "data" / "contracts" / "problematic" / "problematic_01_multiple_violations.docx"
)
CORRECT = REPO_ROOT / "data" / "contracts" / "correct" / "correct_01_accountant.docx"
KB_FILE = REPO_ROOT / "data" / "regulations" / "tk_rf_core_2026-05-15.json"


def _sessionmaker():
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _ensure_kb(sessionmaker) -> None:
    async with sessionmaker() as session:
        active = await session.scalar(
            select(RegulationVersion).where(
                RegulationVersion.status == RegulationVersionStatus.ACTIVE
            )
        )
        if active is not None:
            return
        try:
            version = await knowledge.create_version(
                session, KB_FILE.read_bytes(), uploaded_by=None
            )
            await session.commit()
            version_id = version.id
        except ConflictError as error:
            version_id = uuid.UUID(error.details["version_id"])
    await knowledge.index_version(sessionmaker, version_id, AsyncHashingEmbedder())
    async with sessionmaker() as session:
        await knowledge.activate_version(session, version_id)
        await session.commit()


class SpyLLM(MockLLMClient):
    """Запоминает всё, что ушло бы во внешнюю модель."""

    provider = "spy"
    model_name = "spy-model"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    async def check_chunk(self, chunk, regulations):
        self.sent.append(chunk.text)
        self.sent.extend(item.regulation.text for item in regulations)
        record_call("chunk_check", self.provider, self.model_name, 1, 5, 200, "ok")
        if self.fail:
            raise TimeoutError("модель недоступна")
        if "испытательн" in chunk.text.lower():
            source = next((r for r in regulations if r.regulation.article == "70"), None)
            if source:
                return [
                    LLMChunkResult(
                        chunk_id=chunk.chunk_id,
                        status=CheckStatus.VIOLATION,
                        source=source.regulation.citation,
                        contract_quote=chunk.text[3:60],
                        law_quote="Срок испытания не может превышать трех месяцев",
                        comment="Срок испытания превышает три месяца.",
                        recommendation="Сократить срок испытания до трёх месяцев.",
                    )
                ]
        return []

    async def check_required_terms(self, chunks, regulations):
        self.sent.extend(chunk.text for chunk in chunks)
        return []


def _upload_and_start(client, monkeypatch, path, key=None) -> uuid.UUID:
    queued: list[uuid.UUID] = []

    async def fake_enqueue(analysis_id):
        queued.append(analysis_id)

    monkeypatch.setattr("app.api.v1.analyses.enqueue_analysis", fake_enqueue)
    if isinstance(path, bytes):
        files = {"file": ("not_contract.docx", path)}
    else:
        files = {"file": (path.name, path.read_bytes())}
    document_id = client.post("/api/v1/documents", files=files).json()["document_id"]
    headers = {"Idempotency-Key": key} if key else {}
    response = client.post("/api/v1/analyses", json={"document_id": document_id}, headers=headers)
    assert response.status_code == 202, response.text
    analysis_id = uuid.UUID(response.json()["analysis_id"])
    assert queued == [analysis_id]
    if key:
        again = client.post("/api/v1/analyses", json={"document_id": document_id}, headers=headers)
        assert again.status_code == 200
        assert again.json()["analysis_id"] == str(analysis_id)
    return analysis_id


def _run(analysis_id: uuid.UUID, llm) -> None:
    async def go():
        sessionmaker = _sessionmaker()
        await _ensure_kb(sessionmaker)
        deps = PipelineDeps(
            settings=get_settings(),
            sessionmaker=sessionmaker,
            llm=llm,
            embedder=AsyncHashingEmbedder(),
            reranker=NoReranker(),
        )
        await run_analysis(deps, analysis_id)

    asyncio.run(go())


def test_full_pipeline_problematic_contract(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC, key=str(uuid.uuid4()))
    llm = SpyLLM()
    _run(analysis_id, llm)

    status = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert status["status"] == "completed", status
    assert status["progress"] == 1.0

    result = client.get(f"/api/v1/analyses/{analysis_id}/result").json()
    articles = {
        f["regulation"]["article"] for f in result["findings"] if f["category"] == "critical"
    }
    assert {"91", "115", "136"} <= articles
    categories = [f["category"] for f in result["findings"]]
    assert categories == sorted(categories, key={"critical": 0, "recommended": 1, "info": 2}.get)
    for finding in result["findings"]:
        if finding["contract_quote"]:
            assert finding["law_quote"], "у замечания нет цитаты нормы"
    highlighted = [f for f in result["findings"] if f["highlights"]]
    assert highlighted, "нет ни одной подсветки"
    blocks = {b["block_id"]: b["text"] for b in result["blocks"]}
    for finding in highlighted:
        span = finding["highlights"][0]
        assert blocks[span["block_id"]][span["start"] : span["end"]]

    # НФТ-6: в модель и в сохранённый текст не попали ПДн.
    assert llm.sent
    assert not any(contains_personal_data(text) for text in llm.sent)
    assert not any(contains_personal_data(b["text"]) for b in result["blocks"])

    history = client.get("/api/v1/analyses").json()
    assert any(item["id"] == str(analysis_id) for item in history["items"])

    async def check_db():
        sessionmaker = _sessionmaker()
        async with sessionmaker() as session:
            analysis = await session.get(analysis_service.Analysis, analysis_id)
            document = await session.get(Document, analysis.document_id)
            calls = list(
                await session.scalars(select(LLMCall).where(LLMCall.analysis_id == analysis_id))
            )
            return document, analysis, calls

    document, analysis, calls = asyncio.run(check_db())
    assert document.storage_key is None and document.purged_at is not None  # НФ-04
    assert analysis.snapshot["regulation_versions"]
    assert calls, "журнал вызовов LLM пуст"


def test_llm_outage_gives_partial_result(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC)
    _run(analysis_id, SpyLLM(fail=True))
    result = client.get(f"/api/v1/analyses/{analysis_id}/result").json()
    assert result["is_partial"] is True
    assert result["technical_issues"]
    assert any(f["origin"] == "rule" for f in result["findings"]), "правила должны сохраниться"


def test_not_employment_contract_is_rejected(client, monkeypatch):
    doc = DocxDocument()
    doc.add_paragraph("Счёт на оплату № 15")
    doc.add_paragraph("1.1 Поставщик поставляет канцелярские товары.")
    buffer = io.BytesIO()
    doc.save(buffer)
    analysis_id = _upload_and_start(client, monkeypatch, buffer.getvalue())
    _run(analysis_id, SpyLLM())
    status = client.get(f"/api/v1/analyses/{analysis_id}").json()
    assert status["status"] == "failed"
    assert status["error_code"] == "not_employment_contract"
    assert client.get(f"/api/v1/analyses/{analysis_id}/result").status_code == 409


def test_correct_contract_has_no_critical_findings(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, CORRECT)
    _run(analysis_id, SpyLLM())
    result = client.get(f"/api/v1/analyses/{analysis_id}/result").json()
    assert result["status"] == "completed"
    assert not [f for f in result["findings"] if f["origin"] == "rule"]
