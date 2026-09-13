from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dtos.files import ImageDTO
from app.enums.hacienda_codes import (
    DiscountType,
    ExemptionCode,
    IvaCollectedFactory,
    TaxRateCode,
    TaxType,
)
from app.enums.product_type import ProductType


# ---------------------------------------------------------------------------
# Fiscal / Hacienda e-invoicing nested DTOs (input only — no computed fields)
# ---------------------------------------------------------------------------

class TaxRateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(None)
    percentage: float = Field(...)
    # Hacienda Nota 8.1 rate code (01–11). Optional on input because legacy
    # payloads predate the catalog; new payloads should send it.
    code: Optional[str] = Field(None)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {m.value for m in TaxRateCode}
        if value not in allowed:
            raise ValueError(
                f"tax_rate.code {value!r} is not a valid Hacienda Nota 8.1 code."
            )
        return value


class ExemptionInstitutionDTO(BaseModel):
    """Issuing institution of an exoneration (Nota 10.1)."""

    model_config = ConfigDict(populate_by_name=True)

    code: Optional[str] = Field(None, max_length=4)
    name: Optional[str] = Field(None, max_length=160)


class TaxExemptionDTO(BaseModel):
    """`Exoneracion` on a single tax — mirrors sales-be's `ExemptionDTO`.

    Per-TAX rather than per-line, exactly as the document models it: a line can
    carry an exonerated IVA alongside a fully-payable excise, and the XML hangs
    `Exoneracion` off each `Impuesto`.

    The product's own `exemption_authorization_code` / `exempted_rate` /
    `exemption_amount` columns are the CATALOG default for a product that is
    always exonerated; they are copied onto the IVA row of an imported line. This
    DTO is what travels once the exemption is on a line, so an operator can grant
    one per sale without editing the product.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: Nota 10.1 authorization document type (01-11, 99).
    type: Optional[str] = Field(None, max_length=4)
    #: Required when type = 99.
    other_type: Optional[str] = Field(None, max_length=100)
    number: Optional[str] = Field(None, max_length=40)
    institution: Optional[ExemptionInstitutionDTO] = Field(None)
    article: Optional[str] = Field(None, max_length=20)
    section: Optional[str] = Field(None, max_length=20)
    issue_date: Optional[str] = Field(None)
    #: `TarifaExonerada` — the percentage of the tax that is forgiven.
    percentage: Optional[float] = Field(None, ge=0, le=100)
    #: `MontoExonerado`. An OUTPUT the biller derives as tax × percentage/100;
    #: accepted for round-tripping and never trusted as an input.
    amount: Optional[float] = Field(None, ge=0)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return value
        allowed = {m.value for m in ExemptionCode}
        if str(value) not in allowed:
            raise ValueError(
                f"exemption.type {value!r} is not a valid Hacienda Nota 10.1 "
                f"exemption/authorization code."
            )
        return value

    @model_validator(mode="after")
    def _require_other_type_for_99(self) -> "TaxExemptionDTO":
        if (self.type or "").strip() == ExemptionCode.OTHER.value and not (
            self.other_type or ""
        ).strip():
            raise ValueError("exemption.other_type is required when type=99")
        return self


class TaxFactorDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(...)
    factor: float = Field(...)


class TaxAmountDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(...)
    amount: float = Field(...)


class TaxSpecialFieldsDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    quantity: Optional[float] = Field(None)
    percentage: Optional[float] = Field(None)
    proportion: Optional[float] = Field(None)
    volume_consumption: Optional[float] = Field(None)
    tax_amount: Optional[TaxAmountDTO] = Field(None)


class ProductCodeDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code_type_id: str = Field(...)
    number: str = Field(...)


class ProductDiscountDTO(BaseModel):
    """Discount input. `amount` is None on inbound requests — the BE calc sets
    it before persistence so the JSONB row carries the computed value.

    `reason` is the single canonical free-form descriptor:
    - codes 01 / 02 / 03 (Royalty / Royalty-bonus-VAT-to-customer / Bonus):
      the FE auto-fills it from the discount-type label.
    - code 99 (Otros): the user enters the Nota-20 nature text — required.
    """

    model_config = ConfigDict(populate_by_name=True)

    discount_type_id: str = Field(...)
    percentage: Optional[float] = Field(None)
    reason: Optional[str] = Field(None)
    is_amount: Optional[bool] = Field(None)
    amount: Optional[float] = Field(None)

    @model_validator(mode="after")
    def _validate_reason(self) -> "ProductDiscountDTO":
        if self.discount_type_id == DiscountType.OTHER.value:
            reason = (self.reason or "").strip()
            if not reason:
                raise ValueError(
                    "Discount type 99 (Otros) requires a non-empty reason."
                )
        return self


#: The IVA family — the codes whose percentage comes from the rate CODE rather
#: than from a supplied rate (sales-api `TaxService._IVA_CODES`).
_IVA_FAMILY_CODES = frozenset(
    {TaxType.IVA.value, TaxType.IVACE.value, TaxType.IVARBU.value}
)


class ProductTaxDTO(BaseModel):
    """Tax input. `amount` is None on inbound requests — the BE calc sets it
    before persistence so the JSONB row carries the computed value.

    `special_fields` is validated per Hacienda Nota 7 for the codes that
    consume per-unit/per-volume parameters:
    - IUC (03), IPT (06), ISEC (12): `quantity` + `tax_amount.id` required.
    - ISEBA (04): `quantity` + `percentage` + `tax_amount.id` required.
    - ISEBEC (05): `quantity` + `volume_consumption` + `tax_amount.id`
      required. The alcoholic-CABYS `percentage` requirement is enforced in
      the service layer where the CABYS row is available.
    """

    model_config = ConfigDict(populate_by_name=True)

    tax_type_id: str = Field(...)
    tax_rate: Optional[TaxRateDTO] = Field(None)
    tax_factor: Optional[TaxFactorDTO] = Field(None)
    other_tax_type: Optional[str] = Field(None)
    special_fields: Optional[TaxSpecialFieldsDTO] = Field(None)
    #: `Exoneracion` for THIS tax. Mirrors the document, where the block hangs
    #: off each `Impuesto` rather than off the line.
    exemption: Optional[TaxExemptionDTO] = Field(None)
    is_amount: Optional[bool] = Field(None)
    amount: Optional[float] = Field(None)

    @model_validator(mode="after")
    def _require_rate_code_for_iva(self) -> "ProductTaxDTO":
        """An IVA-family tax must carry its Nota 8.1 rate CODE, not just a rate.

        `TaxRateDTO.code` is optional on its own because legacy payloads predate
        the catalog, but for codes 01 / 07 / 08 it is the only thing that
        identifies the treatment, and the downstream consequence of omitting it
        is severe and invisible here:

          * sales-api derives the percentage from the code alone for the IVA
            family — `tax.rate` is read for nothing — so a tax with a rate and no
            code cannot be priced, and the document is rejected with
            `tax.rate_code is required when tax.code='01'`.
          * an imported order line copies this product's taxes verbatim, so a
            product saved without the code makes every pedido built from it
            unbillable, long after the save that caused it.
          * the percentage cannot stand in for the code: exento (10), no sujeto
            (11) and crédito pleno (01) are all "0%", so inferring one back from
            the rate can declare the wrong tax treatment.

        Failing here, at the point the data is entered, is the only place the
        person who can fix it is present.
        """
        if self.tax_type_id not in _IVA_FAMILY_CODES:
            return self
        if self.tax_rate is None or not (self.tax_rate.code or "").strip():
            raise ValueError(
                f"tax_rate.code (Hacienda Nota 8.1 rate code) is required for "
                f"tax_type_id {self.tax_type_id!r}; the percentage alone does "
                f"not identify the tax treatment."
            )
        return self

    @model_validator(mode="after")
    def _validate_special_fields(self) -> "ProductTaxDTO":
        code = self.tax_type_id
        # Per-Hacienda-code required-key map for special_fields.
        required_keys_by_code: dict[str, tuple[str, ...]] = {
            TaxType.IUC.value: ("quantity", "tax_amount_id"),
            TaxType.IPT.value: ("quantity", "tax_amount_id"),
            TaxType.ISEC.value: ("quantity", "tax_amount_id"),
            TaxType.ISEBA.value: ("quantity", "percentage", "tax_amount_id"),
            TaxType.ISEBEC.value: (
                "quantity",
                "volume_consumption",
                "tax_amount_id",
            ),
        }
        required = required_keys_by_code.get(code)
        if not required:
            return self
        sf = self.special_fields
        if sf is None:
            raise ValueError(
                f"Tax code {code} requires special_fields with "
                f"keys {required}."
            )
        missing: list[str] = []
        for key in required:
            if key == "tax_amount_id":
                if sf.tax_amount is None or not sf.tax_amount.id:
                    missing.append("tax_amount.id")
            else:
                value = getattr(sf, key, None)
                if value is None:
                    missing.append(key)
        if missing:
            raise ValueError(
                f"Tax code {code} is missing required special_fields: "
                f"{missing}."
            )
        return self


# ---------------------------------------------------------------------------
# Main request DTO
# ---------------------------------------------------------------------------

class ProductRequestDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Basic product fields
    name: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    units_per_box: Optional[int] = Field(None)
    price: Optional[int] = Field(None)
    category_id: Optional[str] = Field(None)
    image: Optional[ImageDTO] = Field(None)
    # Preferred path: an already-uploaded asset URL (org media library / S3).
    # Stored directly when provided; empty string clears it.
    image_url: Optional[str] = Field(None)

    # Inventory / catalogue fields
    stock_quantity: Optional[int] = Field(None)
    low_stock_threshold: Optional[int] = Field(None)
    track_inventory: Optional[bool] = Field(None)
    is_service: Optional[bool] = Field(None)
    # First-class product kind: product | service | program.
    type: Optional[str] = Field(None)
    on_sale: Optional[bool] = Field(None)
    # Storefront "Oferta" flag (independent of the on_sale discount mechanic).
    is_offer: Optional[bool] = Field(None)
    original_price: Optional[int] = Field(None)
    discount: Optional[int] = Field(None)

    # CABYS reference — UUID of an existing data-services cabys row.
    # The row is guaranteed to exist because the FE's CABYS picker calls
    # data-services first, which upserts the row before returning it.
    cabys_id: Optional[str] = Field(None)
    # Hacienda unit-of-measure code (e.g. "Unid", "Sp", "kg").
    unit_measure: Optional[str] = Field(None)
    commercial_unit_measure: Optional[str] = Field(None)
    is_packaged: Optional[bool] = Field(None)
    quantity: Optional[float] = Field(None)
    unit_price: Optional[float] = Field(None)
    customs_part: Optional[str] = Field(None)
    codes: Optional[List[ProductCodeDTO]] = Field(None)
    discounts: Optional[List[ProductDiscountDTO]] = Field(None)
    taxes: Optional[List[ProductTaxDTO]] = Field(None)
    # Manual override for IVACE-07 only; not required in other scenarios
    base_amount: Optional[float] = Field(None)
    # salePrice is NEVER a request field — always computed by the backend

    # ---- Exemption block (Hacienda v4.4 Exoneracion) -----------------------
    # `Exoneracion.TipoDocumento` 01–11 (Nota 10.1). Optional everywhere.
    exemption_authorization_code: Optional[str] = Field(None)
    # `Exoneracion.TarifaExonerada` Decimal(4,2)
    exempted_rate: Optional[float] = Field(None)
    # `Exoneracion.MontoExoneracion` Decimal(18,5)
    exemption_amount: Optional[float] = Field(None)
    # `IVACobradoFabrica` (01 / 02). Validated against the enum.
    iva_collected_factory: Optional[str] = Field(None)
    # data-services FK for the factory-tax-charge row. Round-tripped from the
    # FE so the canonical id-on-product survives a save/edit cycle. Distinct
    # from the line-level `factory_tax` code derived at cart-add time.
    factory_tax_charge_id: Optional[int] = Field(None)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not ProductType.is_valid(value):
            raise ValueError(
                f"type {value!r} is not a valid product type "
                f"(allowed: {ProductType.values()})."
            )
        return value

    @field_validator("iva_collected_factory")
    @classmethod
    def _validate_iva_collected_factory(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {m.value for m in IvaCollectedFactory}
        if value not in allowed:
            raise ValueError(
                f"iva_collected_factory {value!r} not in IvaCollectedFactory enum."
            )
        return value
