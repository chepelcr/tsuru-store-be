from __future__ import annotations

import logging
from typing import Optional
import uuid

from app.dtos.requests.client_request_dto import ClientRequestDTO
from app.dtos.responses.client_dto import (
    ClientListResponse,
    ClientResponse,
    IdentificationResponse,
    PhoneResponse,
    ResidenceResponse,
)
from app.dtos.responses.pagination_dto import PaginationResponse
from app.enums.client_search_filters import ClientSearchFilters
from app.models.client import Client
from app.repositories.client_repository import ClientRepository
from app.utils.search_utils import SearchUtils

logger = logging.getLogger(__name__)


def get_clients(
    company_id: str,
    page: int = 1,
    page_size: int = 12,
    search: str = None,
) -> ClientListResponse:
    """Get paginated clients for a company with optional search filters."""
    search_filters = None
    order_by = None

    if search:
        filters, order_result = SearchUtils.parse_search_filter(
            search, Client, ClientSearchFilters
        )
        if filters:
            search_filters = filters
        if order_result:
            order_by = order_result

    with ClientRepository() as repo:
        clients, total = repo.find_all_by_company(
            company_id,
            search_filters=search_filters,
            order_by=order_by,
            page=page,
            page_size=page_size,
        )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    return ClientListResponse(
        data=[_map_client(c) for c in clients],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_elements=total,
            total_pages=total_pages,
        ),
    )


def get_client(company_id: str, client_id: uuid.UUID) -> Optional[ClientResponse]:
    """Get a single client by ID."""
    with ClientRepository() as repo:
        client = repo.find_by_id_and_company(client_id, company_id)
    if not client:
        return None
    return _map_client(client)


def create_client(
    company_id: str,
    dto: "ClientRequestDTO",
) -> ClientResponse:
    """Create a new client or reactivate deleted one."""
    with ClientRepository() as repo:
        # Check if deleted client exists with same unique key
        existing = None
        if dto.client_gln and dto.nationality:
            existing = repo.find_by_unique_key(company_id, dto.client_gln, dto.nationality)
        
        if existing:
            # Reactivate and update deleted client
            existing.client_name = dto.client_name
            existing.customer_type = dto.customer_type
            existing.client_gln = dto.client_gln
            existing.status = 1
            existing.identification_code = dto.identification.code if dto.identification else None
            existing.identification_number = dto.identification.number if dto.identification else None
            existing.business_name = dto.business_name
            existing.nationality = dto.nationality
            existing.email = dto.email
            existing.phone_country_code = dto.phone.country_code if dto.phone else None
            existing.phone_area_code = dto.phone.area_code if dto.phone else None
            existing.phone_number = dto.phone.number if dto.phone else None
            existing.phone_description = dto.phone.description if dto.phone else None
            existing.state_id = dto.residence.state_id if dto.residence else None
            existing.county_id = dto.residence.county_id if dto.residence else None
            existing.district_id = dto.residence.district_id if dto.residence else None
            existing.neighborhood_id = dto.residence.neighborhood_id if dto.residence else None
            existing.address = dto.residence.address if dto.residence else None
            client = repo.save(existing)
        else:
            # Create new client
            client = Client(
                company_id=company_id,
                customer_type=dto.customer_type,
                client_name=dto.client_name,
                client_gln=dto.client_gln,
                status=1,
                identification_code=dto.identification.code if dto.identification else None,
                identification_number=dto.identification.number if dto.identification else None,
                business_name=dto.business_name,
                nationality=dto.nationality,
                email=dto.email,
                phone_country_code=dto.phone.country_code if dto.phone else None,
                phone_area_code=dto.phone.area_code if dto.phone else None,
                phone_number=dto.phone.number if dto.phone else None,
                phone_description=dto.phone.description if dto.phone else None,
                state_id=dto.residence.state_id if dto.residence else None,
                county_id=dto.residence.county_id if dto.residence else None,
                district_id=dto.residence.district_id if dto.residence else None,
                neighborhood_id=dto.residence.neighborhood_id if dto.residence else None,
                address=dto.residence.address if dto.residence else None,
                notes=dto.notes,
            )
            client = repo.save(client)

    return _map_client(client)


def update_client(
    company_id: str,
    client_id_str: str,
    dto: "ClientRequestDTO",
) -> Optional[ClientResponse]:
    """Update an existing client. Cannot update deleted clients."""
    client_id = uuid.UUID(client_id_str)

    with ClientRepository() as repo:
        client = repo.find_by_id_and_company(client_id, company_id)
        if not client:
            return None
        
        if client.status == 3:
            raise ValueError("Cannot update deleted client. Use POST to reactivate.")

        if dto.client_name is not None:
            client.client_name = dto.client_name
        if dto.customer_type is not None:
            client.customer_type = dto.customer_type
        if dto.client_gln is not None:
            client.client_gln = dto.client_gln
        if dto.identification:
            if dto.identification.code is not None:
                client.identification_code = dto.identification.code
            if dto.identification.number is not None:
                client.identification_number = dto.identification.number
        if dto.business_name is not None:
            client.business_name = dto.business_name
        if dto.nationality is not None:
            client.nationality = dto.nationality
        if dto.email is not None:
            client.email = dto.email
        if dto.phone:
            if dto.phone.country_code is not None:
                client.phone_country_code = dto.phone.country_code
            if dto.phone.area_code is not None:
                client.phone_area_code = dto.phone.area_code
            if dto.phone.number is not None:
                client.phone_number = dto.phone.number
            if dto.phone.description is not None:
                client.phone_description = dto.phone.description
        if dto.residence:
            if dto.residence.state_id is not None:
                client.state_id = dto.residence.state_id
            if dto.residence.county_id is not None:
                client.county_id = dto.residence.county_id
            if dto.residence.district_id is not None:
                client.district_id = dto.residence.district_id
            if dto.residence.neighborhood_id is not None:
                client.neighborhood_id = dto.residence.neighborhood_id
            if dto.residence.address is not None:
                client.address = dto.residence.address
        if dto.notes is not None:
            client.notes = dto.notes

        if client.status == 0:
            client.status = 1

        client = repo.save(client)

    return _map_client(client)


def update_client_status(
    company_id: str,
    client_id_str: str,
    status: int,
) -> Optional[ClientResponse]:
    """Update a client's status. Cannot update deleted clients."""
    client_id = uuid.UUID(client_id_str)

    with ClientRepository() as repo:
        client = repo.find_by_id_and_company(client_id, company_id)
        if not client:
            return None
        
        if client.status == 3:
            raise ValueError("Cannot update deleted client. Use POST to reactivate.")

        client.status = status
        client = repo.save(client)

    return _map_client(client)


def _map_client(client: Client) -> ClientResponse:
    identification = None
    if client.identification_number:
        identification = IdentificationResponse(
            code=client.identification_code,
            number=client.identification_number,
        )
    
    phone = None
    if client.phone_number:
        phone = PhoneResponse(
            country_code=client.phone_country_code,
            dial_code=(client.phone_country.dial_code if client.phone_country
                       else client.phone_country_code),
            dial_area=client.phone_country.dial_area if client.phone_country else None,
            area_code=client.phone_area_code,
            number=client.phone_number,
            description=client.phone_description,
        )
    
    residence = None
    if client.state_id or client.county_id or client.district_id or client.neighborhood_id or client.address:
        residence = ResidenceResponse(
            state_id=client.state_id,
            county_id=client.county_id,
            district_id=client.district_id,
            neighborhood_id=client.neighborhood_id,
            address=client.address,
        )
    
    return ClientResponse(
        client_id=str(client.client_id),
        company_id=client.company_id,
        customer_type=client.customer_type,
        client_name=client.client_name,
        client_gln=client.client_gln,
        status=client.status,
        identification=identification,
        business_name=client.business_name,
        nationality=client.nationality,
        email=client.email,
        phone=phone,
        residence=residence,
        notes=client.notes,
    )
