from __future__ import annotations

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dtos.requests.product_request_dto import TaxExemptionDTO
from app.enums.hacienda_codes import TaxRateCode, TaxType


class ManualOrderPartyDTO(BaseModel):
    """Denormalized client identity captured at the till."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=250)
    gln: Optional[str] = Field(None, max_length=50)
    internal_code: Optional[str] = Field(None, max_length=50)


class ManualOrderDeliveryLocationDTO(BaseModel):
    """Where the order goes — one of three shapes, never a free-text blob.

    * ``store``    — a point the client has registered (``store_id``)
    * ``receiver`` — the receiver's own address, copied as the CR cascade
    * ``custom``   — a hand-picked provincia/cantón/distrito/barrio + address
    """

    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["store", "receiver", "custom"] = "store"
    store_id: Optional[str] = None
    code: Optional[str] = Field(None, max_length=20)
    name: Optional[str] = Field(None, max_length=250)
    gln: Optional[str] = Field(None, max_length=50)
    state_id: Optional[int] = None
    county_id: Optional[int] = None
    district_id: Optional[int] = None
    neighborhood_id: Optional[int] = None
    address: Optional[str] = Field(None, max_length=500)


class ManualOrderTaxSpecialFieldsDTO(BaseModel):
    """Per-unit parameters for the specific excises (codes 03/04/05/06/12).

    These taxes are not a rate on a base — each multiplies a per-unit amount by
    a quantity, a volume or a proportion — so a line that omits them cannot be
    recomputed at all, and an invoice built from the pedido later would have to
    invent them. Mirrors `TaxSpecialFieldsDTO` on the product side, which is the
    shape these are stored and recomputed in.
    """

    model_config = ConfigDict(populate_by_name=True)

    quantity: Optional[float] = Field(None, ge=0)
    percentage: Optional[float] = Field(None, ge=0)
    proportion: Optional[float] = Field(None, ge=0)
    volume_consumption: Optional[float] = Field(None, ge=0)
    #: data-api catalog id of the per-unit amount (`tax_amounts`).
    #: Accepts an int as well as a string: the FE types it as a number (the
    #: catalog serves integer ids) while everything downstream keys on the
    #: string, and a strict `str` here rejects the POS's own payload.
    tax_amount_id: Optional[Union[str, int]] = Field(None)
    #: The per-unit amount itself, so the pedido can be recomputed offline.
    tax_unit_amount: Optional[float] = Field(None, ge=0)


#: The IVA family — codes whose percentage comes from the rate CODE, not a rate.
_IVA_FAMILY_CODES = frozenset(
    {TaxType.IVA.value, TaxType.IVACE.value, TaxType.IVARBU.value}
)

#: Per-code `special_fields` requirements (Hacienda Nota 7). Mirrors the map in
#: `ProductTaxDTO._validate_special_fields` — an order line and the product it
#: came from must demand the same parameters, or a pedido can carry an excise the
#: product form would have refused.
_SPECIAL_FIELDS_BY_CODE: dict[str, tuple[str, ...]] = {
    TaxType.IUC.value: ("quantity", "tax_amount_id"),
    TaxType.IPT.value: ("quantity", "tax_amount_id"),
    TaxType.ISEC.value: ("quantity", "tax_amount_id"),
    TaxType.ISEBA.value: ("quantity", "percentage", "tax_amount_id"),
    TaxType.ISEBEC.value: ("quantity", "volume_consumption", "tax_amount_id"),
}


class ManualOrderTaxDTO(BaseModel):
    """Per-line tax breakdown. Kept structured so the server can recompute.

    Validated to the same standard as `ProductTaxDTO`. It used not to be, which
    meant a pedido could be accepted here carrying tax data that only failed
    much later — when the pedido was billed, by which point the person who typed
    it is long gone and a consecutive may already have been allocated.
    """

    model_config = ConfigDict(populate_by_name=True)

    code: Optional[str] = Field(None, max_length=4, description="Hacienda tax type code")
    rate_code: Optional[str] = Field(None, max_length=4)
    rate: Optional[float] = Field(None, ge=0)
    amount: Optional[float] = Field(None, ge=0)
    #: Required when code = "99" (Otros).
    other_tax_type: Optional[str] = Field(None, max_length=100)
    #: `FactorCalculoIVA` for code "08" (régimen de bienes usados).
    factor: Optional[float] = Field(None, ge=0)
    special_fields: Optional[ManualOrderTaxSpecialFieldsDTO] = None
    #: `Exoneracion` for this tax (Nota 10.1). Per-TAX, as on the document.
    #: Reuses the product DTO so one definition validates both paths.
    exemption: Optional[TaxExemptionDTO] = None

    # `base` and `factory_assumed` were accepted here and then dropped on the
    # floor — `canonical_line_dtos` never read either one, so a caller sending
    # them got no error and no effect. Removed rather than implemented: the
    # taxable base is only editable in two documented cases and belongs on the
    # LINE (`base_amount`), and whether the issuer absorbs a tax is DERIVED from
    # the tax code and the discount natures, never asserted by the client.

    @field_validator("rate_code")
    @classmethod
    def _validate_rate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return value
        allowed = {m.value for m in TaxRateCode}
        if str(value) not in allowed:
            raise ValueError(
                f"rate_code {value!r} is not a valid Hacienda Nota 8.1 rate code."
            )
        return value

    @model_validator(mode="after")
    def _validate_code_requirements(self) -> "ManualOrderTaxDTO":
        """The per-code requirements, mirroring `ProductTaxDTO`.

        Same three rules the biller enforces, applied at capture time:
        the IVA family needs its rate code (the percentage is derived from the
        code alone, so without it the line cannot be priced); code 08 needs its
        factor (the factor IS the calculation); and the specific excises need the
        per-unit parameters they multiply, which cannot be recovered from a total.
        """
        code = (self.code or "").strip()
        if not code:
            return self

        if code in _IVA_FAMILY_CODES and not (self.rate_code or "").strip():
            raise ValueError(
                f"rate_code is required for tax code {code!r}; the percentage "
                f"alone does not identify the tax treatment."
            )

        if code == TaxType.IVARBU.value and self.factor is None:
            raise ValueError(
                "factor is required for tax code 08 (IVA Régimen de Bienes "
                "Usados); the factor is the calculation, not a rate modifier."
            )

        required = _SPECIAL_FIELDS_BY_CODE.get(code)
        if not required:
            return self
        sf = self.special_fields
        if sf is None:
            raise ValueError(
                f"Tax code {code} requires special_fields with keys {required}."
            )
        missing: list[str] = []
        for key in required:
            if key == "tax_amount_id":
                if sf.tax_amount_id is None or not str(sf.tax_amount_id).strip():
                    missing.append("tax_amount_id")
            elif getattr(sf, key, None) is None:
                missing.append(key)
        if missing:
            raise ValueError(
                f"Tax code {code} is missing required special_fields: {missing}."
            )
        return self


class ManualOrderDiscountDTO(BaseModel):
    """Per-line discount in the Hacienda cascade order."""

    model_config = ConfigDict(populate_by_name=True)

    code: Optional[str] = Field(None, max_length=4)
    nature: Optional[str] = Field(None, max_length=100)
    percentage: Optional[float] = Field(None, ge=0, le=100)
    amount: Optional[float] = Field(None, ge=0)


class ManualOrderLineCodeDTO(BaseModel):
    """One product code on a line, per Hacienda Nota 6.

    01 vendedor · 02 comprador · 03 fabricante · 04 uso interno · 99 otros.
    """

    model_config = ConfigDict(populate_by_name=True)

    code_type_id: str = Field(..., max_length=2)
    number: str = Field(..., max_length=100)


class ManualOrderLineDTO(BaseModel):
    """A pedido line, shaped like the document line it may become.

    The field set mirrors `DetalleLinea` (jbiller_common `CommonDetailDTO`) on
    purpose. A pedido is not a fiscal document, but the invoice built from one
    is, and anything the POS knew that this DTO had no field for was simply lost
    at capture and had to be guessed back at billing time — from the catalog,
    which may have changed since the customer agreed to the order.
    """

    model_config = ConfigDict(populate_by_name=True)

    line_number: int = Field(..., ge=1)
    product_id: Optional[str] = Field(None, max_length=255)
    internal_code: Optional[str] = Field(None, max_length=50)
    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(..., gt=0)
    #: Unit price WITHOUT tax.
    unit_price: float = Field(..., ge=0)
    discount: float = Field(default=0, ge=0)
    tax: float = Field(default=0, ge=0)
    line_total: float = Field(default=0, ge=0)
    #: Kept even though a pedido is not fiscal — it is what makes billing it
    #: later possible without guessing a rate.
    cabys: Optional[str] = Field(None, max_length=13)
    taxes: Optional[List[ManualOrderTaxDTO]] = None
    discounts: Optional[List[ManualOrderDiscountDTO]] = None
    #: The line's own codes. `internal_code` above stays for the crossdocking
    #: reports that read it directly; this is the full canonical set.
    codes: Optional[List[ManualOrderLineCodeDTO]] = None
    #: Hacienda `UnidadMedida` — required on every document line, so a pedido
    #: that omits it forces a fallback to "Unid" when it is billed.
    unit_measure: Optional[str] = Field(None, max_length=20)
    commercial_unit_measure: Optional[str] = Field(None, max_length=50)
    customs_part: Optional[str] = Field(None, max_length=50)
    #: Editable taxable base — legal only alongside tax code 07 or
    #: `iva_collected_factory == "01"`.
    base_amount: Optional[float] = Field(None, ge=0)
    #: `IVACobradoFabrica`: "01" settled at factory, "02" exempt by regime.
    iva_collected_factory: Optional[str] = Field(None, max_length=2)


class ManualOrderPaymentDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(..., max_length=4, description="Hacienda payment code")
    other_type: Optional[str] = Field(None, max_length=100)
    amount: float = Field(..., ge=0)


class ManualOrderTotalsDTO(BaseModel):
    """Client-side totals. A HINT only — the server recomputes (see service)."""

    model_config = ConfigDict(populate_by_name=True)

    total_lines: int = Field(default=0, ge=0)
    total_quantity_ordered: float = Field(default=0, ge=0)
    subtotal: float = Field(default=0, ge=0)
    discounts: float = Field(default=0, ge=0)
    taxes: float = Field(default=0, ge=0)
    grand_total: float = Field(default=0, ge=0)


class CreateManualOrderDTO(BaseModel):
    """A pedido captured by hand in the POS document editor.

    Discriminated from the anonymous storefront pedido by ``source='manual'``
    on the shared ``POST /orders`` route: the storefront body has no ``source``.
    """

    model_config = ConfigDict(populate_by_name=True)

    source: Literal["manual"]
    #: Internal editor doc type ('PM'), never a Hacienda code.
    document_type: str = Field(default="PM", max_length=8)
    #: 'work_order' for a taller OT; None for a plain pedido. NEVER '73' —
    #: that is the cross-docking flow.
    order_type: Optional[str] = Field(None, max_length=20)

    #: User-writable. Omit to draw from the organization's PM sequence.
    document_number: Optional[str] = Field(None, max_length=50)
    #: Save as a cotización — the order opens in 'quote' status.
    is_quote: bool = False

    client_id: Optional[str] = None
    client: ManualOrderPartyDTO

    #: Captured so a later factura reuses what the cashier chose.
    sale_condition: Optional[str] = Field(None, max_length=10)
    activity_code: Optional[str] = Field(None, max_length=20)
    credit_term: Optional[str] = Field(None, max_length=10)

    delivery_date: Optional[str] = Field(None, max_length=20)
    delivery_location: Optional[ManualOrderDeliveryLocationDTO] = None
    department_id: Optional[str] = None

    #: Taller (work_order) fields — the per-visit facts, not the asset itself.
    asset_id: Optional[str] = None
    odometer: Optional[int] = Field(None, ge=0)
    reported_issue: Optional[str] = Field(None, max_length=500)

    event: Optional[str] = Field(None, max_length=50)
    comment: Optional[str] = Field(None, max_length=500)

    currency_code: str = Field(default="CRC", max_length=3)
    exchange_rate: float = Field(default=1, gt=0)

    assignment_id: Optional[str] = Field(None, max_length=255)
    branch_number: Optional[int] = None
    terminal_number: Optional[int] = None

    #: May be empty: a pedido is normally settled after delivery.
    payments: List[ManualOrderPaymentDTO] = Field(default_factory=list)
    lines: List[ManualOrderLineDTO] = Field(..., min_length=1)
    totals: Optional[ManualOrderTotalsDTO] = None
