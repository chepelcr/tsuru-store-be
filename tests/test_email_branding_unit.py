from app.services.email_service import _build_delivery_email_html, _build_plain_text_body


def test_delivery_email_uses_shared_theme_and_keeps_supplier_details():
    html = _build_delivery_email_html('07/10/2026', '19596')
    assert 'email-header.png' in html
    assert 'email-header-dark.png' in html
    assert 'email-footer-waves-compact.png' in html
    assert 'email-footer-waves-dark.png' in html
    assert 'prefers-color-scheme: dark' in html
    assert 'Modas Laura' in html
    assert 'Vilma Corella Artavia' in html
    assert '07/10/2026' in html and '19596' in html
    assert html.count('id="tsuru-email-theme"') == 1
    assert '07/10/2026' in _build_plain_text_body('07/10/2026', '19596')


def test_delivery_email_escapes_dynamic_fields():
    html = _build_delivery_email_html('<date>', '<provider>')
    assert '&lt;date&gt;' in html and '&lt;provider&gt;' in html
    assert '<date>' not in html and '<provider>' not in html
