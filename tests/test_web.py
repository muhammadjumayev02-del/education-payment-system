def test_website_and_assets(client):
    html = client.get('/')
    assert html.status_code == 200
    assert 'lang="uz"' in html.text
    assert 'data-today=' in html.text
    assert 'BOT_TOKEN' not in html.text
    for path in ['/static/app.js', '/static/style.css']:
        assert client.get(path).status_code == 200


def test_summary_exact_and_month_scoped(client):
    ids = [client.post('/students', json={'name': n, 'phone': '1', 'group_name': 'A',
            'monthly_fee': '100.00'}).json()['id'] for n in ['No payment', 'Partial', 'Full', 'Over']]
    for sid, amount in zip(ids[1:], ['0.30', '100', '120.20']):
        assert client.post('/payments', json={'student_id': sid, 'amount': amount,
                                            'payment_date': '2026-10-01'}).status_code == 201
    assert client.get('/summary?month=2026-10').json() == {
        'month': '2026-10', 'paid_amount': '220.50', 'debt': '199.70', 'debtor_count': 2}
    assert client.get('/summary?month=2026-11').json() == {
        'month': '2026-11', 'paid_amount': '0.00', 'debt': '400.00', 'debtor_count': 4}
    assert client.get('/summary?month=wrong').status_code == 422


def test_empty_summary(client):
    assert client.get('/summary?month=2026-10').json() == {
        'month': '2026-10', 'paid_amount': '0.00', 'debt': '0.00', 'debtor_count': 0}
