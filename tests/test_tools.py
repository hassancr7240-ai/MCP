import pytest
from unittest.mock import MagicMock, patch
from app.auth.azure_ad import AuthenticatedUser
from app.tools import router as tool_router
from fastapi import HTTPException


def _make_user(role: str = "Engineer") -> AuthenticatedUser:
    user = MagicMock(spec=AuthenticatedUser)
    user.primary_role = role
    user.email = "test@org.com"
    user.name = "Test User"
    return user


def test_dispatch_unknown_tool_raises():
    user = _make_user()
    with pytest.raises(ValueError, match="Unknown tool"):
        tool_router.dispatch("nonexistent_tool", {}, user)


def test_dispatch_insufficient_role_raises():
    user = _make_user(role="Technician")
    with pytest.raises(HTTPException) as exc_info:
        tool_router.dispatch("generate_document", {}, user)
    assert exc_info.value.status_code == 403


def test_dispatch_check_pm_any_role():
    user = _make_user(role="Technician")
    with patch("app.tools.pm_tools.sql_db.fetch_pm_status", return_value=[]):
        result = tool_router.dispatch("check_pm_status", {"machine_id": "M001"}, user)
    assert result["machine_id"] == "M001"


def test_dispatch_get_machine_list():
    user = _make_user(role="Technician")
    with patch("app.tools.pm_tools.sql_db.fetch_machine_list", return_value=[]):
        result = tool_router.dispatch("get_machine_list", {}, user)
    assert "machines" in result
