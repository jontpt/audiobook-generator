import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException

from api.routes.books import _resolve_rework_source_revision  # noqa: E402


def test_resolve_rework_source_revision_returns_anchor_when_none_selected():
    anchor = {"id": "rev3", "revision_number": 3}
    revisions = [{"id": "rev1"}, {"id": "rev2"}, {"id": "rev3"}]

    resolved = _resolve_rework_source_revision(anchor, revisions, None)
    assert resolved["id"] == "rev3"


def test_resolve_rework_source_revision_accepts_selected_prior_revision():
    anchor = {"id": "rev3", "revision_number": 3}
    revisions = [{"id": "rev1"}, {"id": "rev2"}, {"id": "rev3"}]

    resolved = _resolve_rework_source_revision(anchor, revisions, "rev1")
    assert resolved["id"] == "rev1"


def test_resolve_rework_source_revision_rejects_missing_revision():
    anchor = {"id": "rev3", "revision_number": 3}
    revisions = [{"id": "rev1"}, {"id": "rev2"}, {"id": "rev3"}]

    with pytest.raises(HTTPException) as exc:
        _resolve_rework_source_revision(anchor, revisions, "rev-missing")
    assert exc.value.status_code == 404


def test_resolve_rework_source_revision_rejects_current_revision_selection():
    anchor = {"id": "rev3", "revision_number": 3}
    revisions = [{"id": "rev1"}, {"id": "rev2"}, {"id": "rev3"}]

    with pytest.raises(HTTPException) as exc:
        _resolve_rework_source_revision(anchor, revisions, "rev3")
    assert exc.value.status_code == 422
