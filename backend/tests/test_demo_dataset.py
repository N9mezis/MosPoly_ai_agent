from app.documents.parser import parse_document
from app.domain.chunker import chunk_document
from app.domain.classifier import is_supported_employment_contract
from app.evals.evaluation import load_dataset
from tests.paths import REPO_ROOT


def test_demo_dataset_contains_twenty_supported_unique_contracts() -> None:
    dataset = load_dataset(REPO_ROOT / "evals" / "demo_cases.json")
    paths = [case.path for case in dataset.cases]

    assert len(paths) == 20
    assert len(set(paths)) == 20
    assert sum(path.startswith("correct/") for path in paths) == 10
    assert sum(path.startswith("problematic/") for path in paths) == 10

    for case in dataset.cases:
        path = REPO_ROOT / "data" / "contracts" / case.path
        assert path.is_file()
        document = parse_document(path)
        assert is_supported_employment_contract(document)
        chunk_ids = {chunk.chunk_id for chunk in chunk_document(document)}
        assert all(finding.chunk_id in chunk_ids for finding in case.expected_findings)
