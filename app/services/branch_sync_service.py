"""Persist branch discovery: from Hacienda history, and the default station at registration.

Two producers share this contract (SAVE_BRANCHES): the Hacienda history sweep /
imports, which carry names, addresses, phones and consecutive maxima; and
management-be at organization registration, which sends branch 1 + terminal 1
with nothing else, so manual orders work before any fiscal information exists.

An existing branch is FILLED with whatever Hacienda sent (fields it did not
send stay as they are). Consecutives only ever go up: GREATEST(stored,
incoming), so a counter already past Hacienda's number keeps the stored one.
"""

from __future__ import annotations

from app.configuration.database_connection import DatabaseConnection
from app.dtos.requests.branch_sync_dto import BranchSyncDTO
from app.repositories.branch_repository import BranchRepository
from app.repositories.branch_type_repository import BranchTypeRepository
from app.repositories.consecutive_repository import ConsecutiveRepository
from app.repositories.document_type_repository import DocumentTypeRepository
from app.repositories.terminal_repository import TerminalRepository
from app.services.phone_country import iso_country_code, phone_digits


class BranchSyncService:
    def sync_from_hacienda(self, organization_id: str, branches: list) -> None:
        """Apply one message in one transaction; duplicate/reordered events are safe."""
        if not organization_id or not organization_id.strip():
            raise ValueError("organization_id is required")
        payload = [
            item if isinstance(item, BranchSyncDTO) else BranchSyncDTO.model_validate(item)
            for item in branches
        ]
        with DatabaseConnection() as db:
            branch_repo = BranchRepository.from_session(db.session)
            terminal_repo = TerminalRepository.from_session(db.session)
            consecutive_repo = ConsecutiveRepository.from_session(db.session)
            type_repo = BranchTypeRepository.from_session(db.session)
            document_repo = DocumentTypeRepository.from_session(db.session)
            branch_types = type_repo.find_all_by_organization(organization_id)
            default_type = branch_types[0].code if branch_types else "stand"
            document_types = {}

            # Stable lock order also avoids deadlocks if publishers reorder rows.
            for incoming in sorted(payload, key=lambda branch: branch.number):
                residence = incoming.residence
                phone = incoming.phone
                number = phone_digits(phone.number) if phone else None
                provided = {
                    "name": incoming.name,
                    "state_id": residence.province_code if residence else None,
                    "county_id": residence.canton_code if residence else None,
                    "district_id": residence.district_code if residence else None,
                    "neighborhood_id": residence.neighborhood_code if residence else None,
                    "address": residence.address if residence else None,
                    "phone_number": number,
                    "phone_country_code": (
                        iso_country_code(db.session, phone.country_code or "188") if number else None
                    ),
                }
                # Only what the event carried overwrites an existing branch.
                updates = {field: value for field, value in provided.items() if value is not None}
                branch = branch_repo.insert_from_history(
                    updates=updates,
                    organization_id=organization_id,
                    code=incoming.number,
                    type=default_type,
                    created_by="hacienda-history",
                    **{**provided, "name": incoming.name or f"Sucursal {incoming.number:03d}"},
                )
                for incoming_terminal in sorted(incoming.terminals, key=lambda terminal: terminal.number):
                    terminal = terminal_repo.insert_from_history(
                        updates={"name": incoming_terminal.name} if incoming_terminal.name else None,
                        organization_id=organization_id,
                        branch_id=branch.branch_id,
                        code=incoming_terminal.number,
                        name=incoming_terminal.name or f"Terminal {incoming_terminal.number}",
                    )
                    for counter in sorted(incoming_terminal.consecutives, key=lambda item: item.document_type):
                        if counter.document_type not in document_types:
                            doc_type = document_repo.find_by_code(counter.document_type)
                            if doc_type is None:
                                raise ValueError(f"Unknown document type {counter.document_type}")
                            document_types[counter.document_type] = doc_type.id
                        consecutive_repo.raise_from_history(
                            organization_id,
                            str(terminal.terminal_id),
                            document_types[counter.document_type],
                            counter.current_number,
                        )

            # The legacy context manager logs and swallows commit failures. Commit
            # here so a failed write reaches Powertools and the message is retried.
            db.session.commit()
