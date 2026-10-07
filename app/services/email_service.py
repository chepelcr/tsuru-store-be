"""Email service for sending delivery notifications via AWS SES."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.configuration.app_config import AppConfig
from app.services.pdf_service import download_from_s3
from app.services.email_theme import apply_email_theme

logger = logging.getLogger(__name__)


def _get_ses_client():
    region = AppConfig.get_key("aws.region", "us-east-1")
    session = boto3.Session(
        profile_name=AppConfig.get_key("aws.profile"),
        region_name=region,
    )
    return session.client("ses", region_name=region)


def _extract_provider_number(supplier_internal_code: str) -> str:
    """Extract provider number: first 5 digits excluding leading zeros.

    Example: '019596262' -> '19596'
    """
    if not supplier_internal_code:
        return ""
    digits = supplier_internal_code.lstrip("0")
    return digits[:5]


_DELIVERY_EMAIL_TEMPLATE = (Path(__file__).resolve().parents[1] / "templates" / "emails" / "delivery.html").read_text(encoding="utf-8")


def _build_delivery_email_html(delivery_date: str, provider_number: str) -> str:
    """Render the shared Tsuru email pattern while retaining supplier details."""
    html = (_DELIVERY_EMAIL_TEMPLATE
            .replace('{{delivery_date}}', escape(str(delivery_date)))
            .replace('{{provider_number}}', escape(str(provider_number)))
            .replace('{{year}}', str(datetime.now(timezone.utc).year)))
    return apply_email_theme(html)


def _build_plain_text_body(delivery_date: str, provider_number: str) -> str:
    return (
        f"Buen d\u00eda,\n\n"
        f"Por este medio enviamos los reportes de excel para entrega del {delivery_date}.\n\n"
        f"Agradeciendo su atenci\u00f3n,\n\n"
        f"Vilma Corella Artavia\n"
        f"Proveedor {provider_number}"
    )


def send_delivery_email(
    delivery_date: str,
    provider_number: str,
    attachment_urls: list[dict],
) -> Optional[str]:
    """Send delivery notification email with Excel report attachments.

    Args:
        delivery_date: Formatted delivery date string (dd/mm/yyyy). Already
            formatted by the caller via `order_dates.as_display` — this function
            interpolates it into copy and does not parse it.
        provider_number: Provider number extracted from supplier code.
        attachment_urls: List of dicts with 'url' and 'filename' keys for Excel attachments.

    Returns:
        SES message ID if successful, None otherwise.
    """
    sender = AppConfig.get_key("email.sender", "")
    recipient = AppConfig.get_key("email.recipient", "")

    if not sender or not recipient:
        logger.error("Email sender or recipient not configured (EMAIL_SENDER / EMAIL_RECIPIENT)")
        return None

    subject = f"Entrega {delivery_date} {provider_number}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    # Body container
    msg_body = MIMEMultipart("alternative")

    # Plain text
    text_part = MIMEText(_build_plain_text_body(delivery_date, provider_number), "plain", "utf-8")
    msg_body.attach(text_part)

    # HTML
    html_part = MIMEText(_build_delivery_email_html(delivery_date, provider_number), "html", "utf-8")
    msg_body.attach(html_part)

    wrap = MIMEMultipart("related")
    wrap.attach(msg_body)
    msg.attach(wrap)

    # Attach Excel files downloaded from S3
    for att in attachment_urls:
        try:
            file_bytes = download_from_s3(att["url"])
            part = MIMEApplication(file_bytes)
            part.add_header("Content-Disposition", "attachment", filename=att["filename"])
            msg.attach(part)
        except Exception as e:
            logger.warning(f"Failed to attach {att['filename']}: {e}")

    try:
        ses = _get_ses_client()
        response = ses.send_raw_email(
            Source=sender,
            Destinations=[recipient],
            RawMessage={"Data": msg.as_string()},
        )
        message_id = response.get("MessageId")
        logger.info(f"Delivery email sent successfully, MessageId: {message_id}")
        return message_id
    except ClientError as e:
        logger.error(f"SES ClientError sending delivery email: {e}")
        return None
    except Exception as e:
        logger.error(f"Error sending delivery email: {e}")
        return None
