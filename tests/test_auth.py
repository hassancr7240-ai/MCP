import pytest
from app.auth.roles import has_minimum_role, Role, TOOL_ROLE_REQUIREMENTS


def test_role_hierarchy_technician_below_engineer():
    assert not has_minimum_role("Technician", Role.ENGINEER)


def test_role_hierarchy_manager_meets_engineer():
    assert has_minimum_role("Manager", Role.ENGINEER)


def test_role_hierarchy_exact_match():
    assert has_minimum_role("Engineer", Role.ENGINEER)


def test_unknown_role_returns_false():
    assert not has_minimum_role("Unknown", Role.TECHNICIAN)


def test_tool_requirements_all_roles_for_check_pm():
    assert TOOL_ROLE_REQUIREMENTS["check_pm_status"] is None


def test_tool_requirements_engineer_for_generate_document():
    assert TOOL_ROLE_REQUIREMENTS["generate_document"] == Role.ENGINEER


def test_tool_requirements_technician_for_save_record():
    assert TOOL_ROLE_REQUIREMENTS["save_pm_record"] == Role.TECHNICIAN
