"""Сквозной сценарий на настоящей БД: загрузка → проверка → результат (mock LLM, hashing)."""

from __future__ import annotations

import asyncio
import io
import json
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
KB_FILE = REPO_ROOT / "data" / "regulations" / "legacy" / "tk_rf_core_2026-05-15.json"


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
        assert queued == [analysis_id, analysis_id]  # ARQ deduplicates the retry by job ID.
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
    assert result["snapshot"]["prompt_hashes"]["chunk_check"]
    assert result["snapshot"]["llm_model"] == "spy-model"
    cited = next(f for f in result["findings"] if f["regulation"]["version_id"])
    assert cited["regulation"]["full_text"]
    assert cited["regulation"]["update_status"] == "unchanged"
    cancel = client.post(f"/api/v1/analyses/{analysis_id}/cancel")
    assert (
        cancel.status_code == 409 and cancel.json()["error"]["code"] == "analysis_not_cancellable"
    )
    assert client.get(f"/api/v1/analyses/{analysis_id}/result").status_code == 200


def test_cancel_queued_keeps_record_and_purges_file(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC)

    async def document_for_run():
        async with _sessionmaker()() as session:
            row = await session.get(analysis_service.Analysis, analysis_id)
            return await session.get(Document, row.document_id)

    before = asyncio.run(document_for_run())
    old_path = get_settings().upload_tmp_dir / before.storage_key
    assert old_path.is_file()
    url = f"/api/v1/analyses/{analysis_id}"
    assert client.post(url + "/cancel").status_code == 204
    assert client.post(url + "/cancel").status_code == 204
    _run(analysis_id, SpyLLM())
    response = client.get(url).json()
    assert response["status"] == "cancelled" and response["finished_at"]
    assert not old_path.exists()
    assert asyncio.run(document_for_run()).storage_key is None
    assert client.get(url + "/result").status_code == 409


def test_cancel_during_analysis_does_not_publish(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC)
    url = f"/api/v1/analyses/{analysis_id}"

    class CancellingLLM(SpyLLM):
        async def check_required_terms(self, chunks, regulations):
            assert client.post(url + "/cancel").status_code == 204
            return []

    _run(analysis_id, CancellingLLM())
    assert client.get(url).json()["status"] == "cancelled"
    assert client.get(url + "/result").status_code == 409


def test_report_and_history_flag_changed_citation_without_replacing_quote(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC)
    _run(analysis_id, SpyLLM())
    url = f"/api/v1/analyses/{analysis_id}/result"
    before = client.get(url).json()
    finding = next(f for f in before["findings"] if f["regulation"]["article"] == "91")
    original = uuid.UUID(finding["regulation"]["version_id"])

    async def activate_test_version():
        sessionmaker = _sessionmaker()
        async with sessionmaker() as session:
            current = await session.get(RegulationVersion, original)
            body = json.dumps(
                {
                    "source_id": current.source_id,
                    "source_title": "Test version",
                    "edition_date": "2099-01-01",
                    "chunks": [
                        {
                            "article": "91",
                            "part": finding["regulation"]["part"],
                            "text": f"Synthetic revision {uuid.uuid4()}",
                        }
                    ],
                }
            ).encode()
            version = await knowledge.create_version(session, body, uploaded_by=None)
            await session.commit()
            vid = version.id
        await knowledge.index_version(sessionmaker, vid, AsyncHashingEmbedder())
        async with sessionmaker() as session:
            await knowledge.activate_version(session, vid)
            await session.commit()

    async def restore_original():
        async with _sessionmaker()() as session:
            await knowledge.activate_version(session, original)
            await session.commit()

    try:
        asyncio.run(activate_test_version())
        after = client.get(url).json()
        matched = next(f for f in after["findings"] if f["id"] == finding["id"])
        ref = matched["regulation"]
        assert ref["update_status"] == "changed"
        assert ref["active_edition_date"] == "2099-01-01"
        assert ref["version_id"] == str(original)
        assert ref["full_text"] == finding["regulation"]["full_text"]
        history = client.get("/api/v1/analyses").json()
        assert next(item for item in history["items"] if item["id"] == str(analysis_id))[
            "has_regulation_updates"
        ]
    finally:
        asyncio.run(restore_original())


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
