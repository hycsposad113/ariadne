"""Run real concurrent SQLite workloads outside the pytest process."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("mode", ["file", "memory", "read_only"])
def test_shared_store_threads(tmp_path, mode):
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", WORKLOAD, str(tmp_path / "state.db"), mode],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)


WORKLOAD = r'''
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urban_design.store import ProjectStateStore
path, mode = sys.argv[1:]
store = ProjectStateStore(":memory:" if mode == "memory" else path)
store.create_project({"name": "thread test"}, project_id="project")
if mode == "read_only":
    store.close()
    store = ProjectStateStore(path, read_only=True)
barrier = Barrier(8)
def worker(index):
    barrier.wait()
    for iteration in range(60):
        assert store.current("project").payload["name"] == "thread test"
        assert store.history("project")[0].revision == 1
        assert store.list_current(entity_type="Project")[0].entity_id == "project"
        assert store.replay_project("project")["project"].revision == 1
        assert store.events(target_id="project")
        assert store.connection.execute("SELECT current_revision FROM state_heads WHERE entity_id = 'project'").fetchone()[0] == 1
        assert list(store.connection.execute("SELECT entity_id FROM state_heads WHERE entity_id = 'project'"))[0][0] == "project"
        if mode != "read_only":
            store.create("Artifact", {"worker": index, "iteration": iteration},
                         entity_id=f"artifact-{index}-{iteration}", project_id="project")
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(worker, range(8)))
if mode != "read_only":
    assert len(store.list_current(entity_type="Artifact")) == 480
    assert len(store.events()) == 481
store.close()
'''


def test_locked_connection_blocks_reads_and_close(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from urban_design.store import ProjectStateStore, StoreError

    store = ProjectStateStore(tmp_path / "locked.db")
    store.create_project({"name": "test"}, project_id="project")
    started = Event()

    def read():
        started.set()
        return store.current("project")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.locked_connection() as conn:
            future = pool.submit(read)
            assert started.wait(5)
            assert not future.done()
            # Nested store access must be reentrant.
            assert store.current("project").revision == 1
            assert conn.execute("SELECT count(*) FROM ledger_events").fetchone()[0] == 1
        assert future.result(timeout=5).revision == 1
        started.clear()

        def close():
            started.set()
            store.close()

        with store.locked_connection():
            future = pool.submit(close)
            assert started.wait(5)
            assert not future.done()
        future.result(timeout=5)
    store.close()
    with pytest.raises(StoreError, match="closed"):
        store.current("project")
    with pytest.raises(StoreError, match="closed"):
        with store.locked_connection():
            pass


def test_failed_write_rolls_back_and_releases_lock(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from urban_design.store import ProjectStateStore, EntityExistsError

    with ProjectStateStore(tmp_path / "rollback.db") as store:
        store.create_project({"name": "test"}, project_id="project")
        with pytest.raises(EntityExistsError):
            store.create_project({"name": "duplicate"}, project_id="project")
        with ThreadPoolExecutor(max_workers=1) as pool:
            record = pool.submit(
                store.create, "Artifact", {"name": "after rollback"},
                entity_id="artifact", project_id="project",
            ).result(timeout=5)
        assert record.revision == 1
        assert len(store.events()) == 2
        with store.locked_connection() as conn:
            assert not conn.in_transaction
