from app.dtos.requests.client_request_dto import ClientRequestDTO
from app.dtos.requests.branch_sync_dto import BranchPhoneDTO


def test_client_save_payload_contains_only_raw_domestic_numbers():
    dto = ClientRequestDTO(client_name="Example", identification={"code":"01","number":"1-1234-0567"}, phone={"country_code":"188","number":"8888-7777","area_code":"(01)"})
    payload = dto.model_dump()
    assert payload["identification"]["number"] == "112340567"
    assert payload["phone"]["number"] == "88887777"
    assert payload["phone"]["area_code"] == "01"


def test_foreign_identifier_keeps_its_letters():
    dto = ClientRequestDTO(client_name="Example", identification={"code":"05","number":"AB-012345"})
    assert dto.identification.number == "AB-012345"


def test_branch_sync_removes_phone_display_separators():
    assert BranchPhoneDTO(number="2222-3333").number == "22223333"
