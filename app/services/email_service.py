"""Email service for sending delivery notifications via AWS SES."""

from __future__ import annotations

import logging
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.configuration.app_config import AppConfig
from app.services.pdf_service import download_from_s3

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


def _build_delivery_email_html(delivery_date: str, provider_number: str) -> str:
    """Build styled HTML email body for delivery notification."""
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f0f4f8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f0f4f8; padding: 40px 20px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
          <tr>
            <td style="padding: 40px 40px 20px 40px; text-align: center;">
              <h1 style="margin: 0; font-size: 28px; color: #0E5C23; font-weight: bold;">Modas Laura</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 0 40px 20px 40px; text-align: center;">
              <h2 style="margin: 0; font-size: 24px; color: #1a1a1a;">Notificaci\u00f3n de Entrega</h2>
            </td>
          </tr>
          <tr>
            <td style="padding: 0 40px 30px 40px;">
              <p style="margin: 0 0 16px 0; font-size: 16px; color: #666666; line-height: 1.6;">
                Buen d\u00eda,
              </p>
              <p style="margin: 0 0 16px 0; font-size: 16px; color: #666666; line-height: 1.6;">
                Por este medio enviamos los reportes de excel para entrega del {delivery_date}.
              </p>
              <p style="margin: 0 0 8px 0; font-size: 16px; color: #666666; line-height: 1.6;">
                Agradeciendo su atenci\u00f3n,
              </p>
              <p style="margin: 0; font-size: 16px; color: #666666; line-height: 1.6;">
                <strong>Vilma Corella Artavia</strong><br>
                Proveedor {provider_number}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding: 20px 40px; background-color: #f8f8f8; border-radius: 0 0 16px 16px; text-align: center;">
              <p style="margin: 0; font-size: 12px; color: #999999;">
                Modas Laura &mdash; Cross-Docking
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


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
