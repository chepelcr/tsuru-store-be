"""
Unit tests for the branch-types handler (service layer + DTO validation).

Branch types are the per-org catalog that replaced the hardcoded `stand`/`restaurant`
enum, so the rules worth pinning down are: codes are unique per org, `code` is
immutable once branches reference it, and a type still in use cannot be deleted.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.dtos.requests.branch_type_request_dto import (
    BranchTypeCreateRequestDTO,
    BranchTypeUpdateRequestDTO,
)
from app.models.branch_type import BranchType
from app.services import branch_type_service


def _branch_type(org_id="org-123", code="stand", name="Puesto", **over):
    bt = BranchType(
        branch_type_id=over.pop("branch_type_id", uuid.uuid4()),
        organization_id=org_id,
        code=code,
        name=name,
        icon=over.pop("icon", "store"),
        color=over.pop("color", "primary"),
        sort_order=over.pop("sort_order", 0),
        is_default=over.pop("is_default", False),
        created_by=over.pop("created_by", "user-456"),
        **over,
    )
    bt.status = 1
    bt.created_on = datetime.now(timezone.utc)
    bt.updated_on = None
    return bt


class TestGetBranchTypes:
    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_returns_catalog_in_repository_order(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_all_by_organization.return_value = [
            _branch_type(code="stand", name="Puesto"),
            _branch_type(code="restaurant", name="Restaurante", sort_order=1),
        ]
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        result = branch_type_service.get_branch_types("org-123", "user-456")

        assert [t.code for t in result.data] == ["stand", "restaurant"]
        assert result.data[0].name == "Puesto"
        assert result.data[0].icon == "store"
        # The POS contract keys off `id`, not `branch_type_id`.
        assert result.data[0].id

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_initial_catalog_contains_the_persisted_default(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_all_by_organization.return_value = [_branch_type(code="branch", name="Branch", is_default=True)]
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        result = branch_type_service.get_branch_types("org-123", "user-456")
        assert result.data[0].name == "Branch"
        assert result.data[0].is_default is True
        mock_repo.ensure_default_type.assert_called_once_with("org-123")
        mock_repo.session.commit.assert_called_once()


class TestCreateBranchType:
    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_creates_when_code_is_free(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_by_code_and_organization.return_value = None
        mock_repo.save.side_effect = lambda bt: bt
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        dto = BranchTypeCreateRequestDTO(code="food-truck", name="Food truck", icon="store")
        result = branch_type_service.create_branch_type("org-123", "user-456", dto)

        assert result.code == "food-truck"
        assert result.name == "Food truck"
        saved = mock_repo.save.call_args[0][0]
        assert saved.organization_id == "org-123"
        assert saved.created_by == "user-456"
        assert saved.sort_order == 0

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_rejects_duplicate_code_in_same_org(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_by_code_and_organization.return_value = _branch_type()
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        dto = BranchTypeCreateRequestDTO(code="stand", name="Otro puesto")
        with pytest.raises(ValueError, match="already exists"):
            branch_type_service.create_branch_type("org-123", "user-456", dto)

        mock_repo.save.assert_not_called()

    def test_code_is_normalised_to_a_slug(self):
        assert BranchTypeCreateRequestDTO(code="  Food_Truck  ", name="X").code == "food_truck"

    @pytest.mark.parametrize("bad", ["food truck", "-truck", "food/truck", ""])
    def test_rejects_non_slug_codes(self, bad):
        with pytest.raises(ValidationError):
            BranchTypeCreateRequestDTO(code=bad, name="X")


class TestUpdateBranchType:
    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_updates_presentation_fields_only(self, mock_repo_class):
        existing = _branch_type(code="stand", name="Puesto")
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing
        mock_repo.save.side_effect = lambda bt: bt
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        dto = BranchTypeUpdateRequestDTO(name="Puesto de feria", color="info", sort_order=3)
        result = branch_type_service.update_branch_type(
            "org-123", "user-456", str(existing.branch_type_id), dto
        )

        assert result.name == "Puesto de feria"
        assert result.color == "info"
        assert result.sort_order == 3
        # `code` stays put — branches reference it by value.
        assert result.code == "stand"

    def test_update_dto_has_no_code_field(self):
        assert "code" not in BranchTypeUpdateRequestDTO.model_fields

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_returns_none_for_unknown_id(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        result = branch_type_service.update_branch_type(
            "org-123", "user-456", str(uuid.uuid4()), BranchTypeUpdateRequestDTO(name="X")
        )

        assert result is None


class TestDeleteBranchType:
    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_default_cannot_be_deleted_even_when_unused(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = _branch_type(code="branch", name="Branch", is_default=True)
        mock_repo_class.return_value.__enter__.return_value = mock_repo
        with pytest.raises(ValueError, match="default branch type"):
            branch_type_service.delete_branch_type("org-123", "user-456", str(uuid.uuid4()))
        mock_repo.delete.assert_not_called()

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_deletes_when_unused(self, mock_repo_class):
        existing = _branch_type()
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing
        mock_repo.count_branches_using.return_value = 0
        mock_repo.delete.return_value = True
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        assert branch_type_service.delete_branch_type(
            "org-123", "user-456", str(existing.branch_type_id)
        ) is True
        mock_repo.delete.assert_called_once_with(str(existing.branch_type_id))

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_refuses_while_branches_still_use_the_code(self, mock_repo_class):
        existing = _branch_type()
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = existing
        mock_repo.count_branches_using.return_value = 2
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        with pytest.raises(ValueError, match="2 branch"):
            branch_type_service.delete_branch_type(
                "org-123", "user-456", str(existing.branch_type_id)
            )

        mock_repo.delete.assert_not_called()

    @patch("app.services.branch_type_service.BranchTypeRepository")
    def test_returns_false_for_unknown_id(self, mock_repo_class):
        mock_repo = MagicMock()
        mock_repo.find_by_id_and_organization.return_value = None
        mock_repo_class.return_value.__enter__.return_value = mock_repo

        assert branch_type_service.delete_branch_type(
            "org-123", "user-456", str(uuid.uuid4())
        ) is False
