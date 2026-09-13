"""Hacienda catalog code enums for Costa Rica e-invoicing (v4.4).

Scope: codes referenced by the product surface only. Sale-side enums
(DocumentType, SaleConditionCode, PaymentMethodCode, ReferenceDocType,
ReferenceCode, IdentificationTypeCode, OtherChargeCode) belong to the
sales service and are not duplicated here.
"""

from enum import Enum


class ProductCodeType(str, Enum):
    VENDOR = "01"         # Código del producto del vendedor
    BUYER = "02"          # Código del producto del comprador
    MANUFACTURER = "03"   # Código del producto asignado por el fabricante
    INTERNAL = "04"       # Código uso interno
    OTHER = "99"          # Otros


class DiscountType(str, Enum):
    """Discount nature codes per Hacienda Nota 20.

    Labels mirror the spec names so business logic reads naturally; the
    string values stay stable to preserve persisted JSONB payloads.

    Mirrors the `discount_types` catalog served by data-be (country 188).
    Only 01/03 re-route IVA to the factory — see
    FACTORY_ASSUMED_DISCOUNT_NATURES below — and only 99 requires a free-text
    reason, which is why COMMERCIAL (07) is the right default for an imported
    line that carries a discount but no type.
    """

    ROYALTY = "01"                     # Descuento por Regalía
    ROYALTY_BONUS_VAT_CUSTOMER = "02"  # Regalía / bonificación, IVA cobrado al cliente
    BONUS = "03"                       # Descuento por Bonificación
    VOLUME = "04"                      # Descuento por volumen
    SEASONAL = "05"                    # Descuento por Temporada (estacional)
    PROMOTIONAL = "06"                 # Descuento promocional
    COMMERCIAL = "07"                  # Descuento Comercial
    FREQUENCY = "08"                   # Descuento por frecuencia
    SUSTAINED = "09"                   # Descuento sostenido
    OTHER = "99"                       # Otros (requires reason)


class TaxType(str, Enum):
    IVA = "01"    # Impuesto al Valor Agregado
    ISC = "02"    # Impuesto Selectivo de Consumo
    IUC = "03"    # Impuesto Único a los Combustibles
    ISEBA = "04"  # Impuesto Específico de Bebidas Alcohólicas
    ISEBEC = "05" # Impuesto Específico sobre Bebidas Envasadas
    IPT = "06"    # Impuesto a los Productos de Tabaco
    IVACE = "07"  # IVA Cálculo Especial
    IVARBU = "08" # IVA Régimen de Bienes Usados
    ISEC = "12"   # Impuesto Específico al Cemento
    OTHERS = "99" # Otros


class TaxRateCode(str, Enum):
    """IVA rate codes per Hacienda Nota 8.1."""

    EXEMPT_FULL_CREDIT = "01"          # 0% — derecho a crédito pleno (Art. 32 RLIVA)
    REDUCED_1 = "02"                   # 1%
    REDUCED_2 = "03"                   # 2%
    REDUCED_4 = "04"                   # 4%
    TRANSITIONAL_0 = "05"              # 0% transitorio (NC/ND only)
    TRANSITIONAL_4 = "06"              # 4% transitorio (NC/ND only)
    TRANSITIONAL_8 = "07"              # 8% transitorio (NC/ND only, disabled)
    GENERAL_13 = "08"                  # 13% — tarifa general
    REDUCED_HALF = "09"                # 0.5%
    EXEMPT = "10"                      # 0% — exento (Ley 9635 Art. 8)
    NOT_SUBJECT = "11"                 # 0% — no sujeto, sin derecho de crédito


class ExemptionCode(str, Enum):
    """Exemption / authorization document types per Hacienda Nota 10.1.

    Not to be confused with the reference ACTION codes (Anula / Corrige /
    Sustituye…), which are a different two-digit table on the same document. The
    POS had these two tables under one name until TSR-126.

    Two of these are **LOCAL** authorizations — 04 and 11 — and a Factura
    granting one MUST also carry an `InformacionReferencia`, per the analysis
    doc's "Obligatorio en … FE con exoneraciones locales".
    """

    DGT_AUTHORIZED_PURCHASE = "01"          # Exclusive use NC/ND
    DIPLOMAT_EXEMPTION = "02"
    SPECIAL_LAW_AUTHORIZATION = "03"
    DGH_GENERIC_LOCAL_EXEMPTION = "04"      # LOCAL
    TRANSITIONAL_ARCHITECTURE = "05"        # NC/ND only
    TRANSITIONAL_ICT = "06"                 # NC/ND only
    TRANSITIONAL_RECYCLING = "07"           # NC/ND only
    FREE_TRADE_ZONE = "08"
    COMPLEMENTARY_EXPORT_SERVICES = "09"
    MUNICIPAL_CORPORATION_BODY = "10"
    DGH_SPECIFIC_LOCAL_EXEMPTION = "11"     # LOCAL
    OTHER = "99"


#: Nota 10.1 codes that are LOCAL authorizations, which pull a mandatory
#: `InformacionReferencia` onto a Factura. Mirrors sales-be's
#: `LOCAL_EXEMPTION_CODES`.
LOCAL_EXEMPTION_CODES = frozenset(
    {
        ExemptionCode.DGH_GENERIC_LOCAL_EXEMPTION.value,
        ExemptionCode.DGH_SPECIFIC_LOCAL_EXEMPTION.value,
    }
)


class IvaCollectedFactory(str, Enum):
    """`IVACobradoFabrica` indicator per Hacienda v4.4."""

    PRE_DETERMINED = "01"  # IVA pre-determinado a nivel de fábrica
    EXEMPT_BY_FACTORY = "02"  # Exento por régimen especial de fábrica


class CabysSpecialPrefix(str, Enum):
    """CABYS code prefixes that trigger special-tax branching.

    Used by `tax_calculation_service.apply_isebec` to pick between the toilet-
    soap formula (per gram) and the packaged-beverage one (per volume).

    The previous values — "2202" and "3401" — are Harmonized System headings,
    NOT CABYS. No CABYS code begins with either, so both branches were dead and
    every code-05 line fell through to the soap formula, including beverages.
    Verified against the live catalog (20 501 rows); mirrors
    `fe/pos-system/src/lib/specialTaxes.ts`.

    CABYS is its own 13-digit taxonomy::

        3532101010101  Jabón medicinal de tocador, en barras...
        3532101010199  Jabón de tocador n.c.p., en barras...
        3532101010200  Jabón PARA LAVAR   <- same family, NOT "de tocador"
        2449001000000  Bebidas gaseosas azucaradas, edulcoradas...

    Note the third row: a short "3532" prefix over-matches into laundry soap,
    which the excise does not cover, so the soap prefix is the narrower
    ``35321010101``.
    """

    #: Jabón de tocador — ISEBEC (05) priced per GRAM.
    ISEBEC_TOILET_SOAP = "35321010101"
    #: Bebidas envasadas no alcohólicas — ISEBEC (05) priced per volume.
    ISEBEC_PACKAGED_BEVERAGE = "2449"


# Discount natures that re-route the line's IVA into
# `ImpuestoAsumidoEmisorFabrica` (Hacienda Nota 20). Mirrors the FE
# `FACTORY_ASSUMED_DISCOUNT_NATURES` constant.
FACTORY_ASSUMED_DISCOUNT_NATURES: tuple[str, ...] = (
    DiscountType.ROYALTY.value,
    DiscountType.BONUS.value,
)


# Specific excises the ISSUER absorbs rather than charging the customer.
# Hacienda -476 spells out what `ImpuestoAsumidoEmisorFabrica` must add up to:
#
#   "la sumatoria de los impuestos calculados a productos definidos como
#    regalias o bonificaciones o impuestos especificos a los combustibles,
#    Bebidas Alcoholicas, sin contenido alcoholico, jabon y cemento"
#
# That enumerates combustibles (03), bebidas alcohólicas (04), bebidas sin
# contenido alcohólico y jabón (05) and cemento (12). It does NOT include the
# selectivo de consumo (02) or tabaco (06), which are ordinary collected taxes
# — and empirically those two are exactly the ones Hacienda accepted while
# 03/04/05/12 were rejected with -476 and -488.
#
# Assumption is per TAX ROW, not per line: a line can carry an issuer-assumed
# excise and a customer-paid IVA at the same time.
FACTORY_ASSUMED_EXCISES: tuple[str, ...] = (
    TaxType.IUC.value,
    TaxType.ISEBA.value,
    TaxType.ISEBEC.value,
    TaxType.ISEC.value,
)


# The excises Hacienda folds into `BaseImponible` before IVA is applied (-454):
# "el cálculo del monto Base Imponible no concuerda con 'Subtotal', más el ISC
# (02), ISEBA (04) e ISEBEC (05) ... según corresponda". 12 (cemento) belongs
# here too — a cement line with BaseImponible == Subtotal is rejected by that
# same check. 03 (combustibles) and 06 (tabaco) do NOT.
BASE_BUILDING_EXCISES: tuple[str, ...] = (
    TaxType.ISC.value,
    TaxType.ISEBA.value,
    TaxType.ISEBEC.value,
    TaxType.ISEC.value,
)
