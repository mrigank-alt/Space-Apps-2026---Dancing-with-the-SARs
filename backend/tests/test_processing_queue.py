from backend.app.processing import GUNWProcessingService
from backend.app.repository import InMemorySelectionRepository
from backend.tests.test_repository import selection


def test_repeated_request_reuses_active_run(tmp_path, monkeypatch):
    repo = InMemorySelectionRepository()
    saved = selection()
    repo.save(saved)
    service = GUNWProcessingService(repo, str(tmp_path))
    submitted = []
    monkeypatch.setattr(service, "submit", submitted.append)
    try:
        first = service.queue(saved.selection_id)
        second = service.queue(saved.selection_id)
        assert first.run_id == second.run_id
        assert submitted == [first.run_id]
        assert len(repo.list_processing_runs(saved.selection_id)) == 1
        assert "queue position 1" in service.get(first.run_id).stage
        repo.save_processing_run(first.model_copy(update={"status": "running"}))
        assert service.queue(saved.selection_id).run_id == first.run_id
    finally:
        service.close()


def test_queue_reports_order_without_starting_another_job(tmp_path, monkeypatch):
    repo = InMemorySelectionRepository()
    saved = selection()
    repo.save(saved)
    other = saved.model_copy(update={"selection_id": "sel_other"})
    repo.save(other)
    service = GUNWProcessingService(repo, str(tmp_path))
    monkeypatch.setattr(service, "submit", lambda _run_id: None)
    try:
        first = service.queue(saved.selection_id)
        second = service.queue(other.selection_id)
        assert "queue position 2" in service.get(second.run_id).stage
        repo.save_processing_run(first.model_copy(update={"status": "running"}))
        assert "queue position 1" in service.get(second.run_id).stage
    finally:
        service.close()
