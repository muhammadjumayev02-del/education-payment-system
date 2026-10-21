from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def add_payment(client, sid, amount, day='2026-10-15'):
    return client.post('/payments', json={'student_id': sid, 'amount': amount, 'payment_date': day})


def test_crud_and_partial_patch(client):
    body = {'name': '  Али  ', 'phone': ' +99890 ', 'group_name': 'Python', 'monthly_fee': '100.50'}
    result = client.post('/students', json=body)
    assert result.status_code == 201
    student = result.json()
    sid = student['id']
    assert student['name'] == 'Али'
    assert student['phone'] == '+99890'
    assert client.get('/students').json() == [student]
    assert client.get(f'/students/{sid}').json() == student
    assert client.patch(f'/students/{sid}', json={}).json() == student
    changed = client.patch(f'/students/{sid}', json={'group_name': 'Backend'}).json()
    assert changed == {**student, 'group_name': 'Backend'}
    updated = client.patch(f'/students/{sid}', json={'monthly_fee': '75.25', 'name': 'Вали', 'phone': '123'})
    assert updated.status_code == 200
    assert updated.json()['monthly_fee'] == '75.25'
    deleted = client.delete(f'/students/{sid}')
    assert deleted.status_code == 204 and deleted.content == b''
    assert client.get(f'/students/{sid}').status_code == 404
    assert client.get('/students').json() == []


def test_payments_and_exact_storage(client, student):
    sid = student['id']
    assert client.get(f'/students/{sid}/payments').json() == []
    a = add_payment(client, sid, '0.10')
    b = add_payment(client, sid, '0.20')
    assert a.status_code == b.status_code == 201
    assert a.json()['amount'] == '0.10'
    assert len(client.get(f'/students/{sid}/payments').json()) == 2
    debt = client.get('/debtors?month=2026-10').json()[0]
    assert debt['paid_amount'] == '0.30' and debt['debt'] == '99.70'
    with client.app.state.sessions() as db:
        assert db.execute(text('SELECT amount, typeof(amount) FROM payments ORDER BY id')).all() == [(10, 'integer'), (20, 'integer')]
        assert db.execute(text('SELECT monthly_fee FROM students')).scalar_one() == 10000


def test_all_payment_cases(client):
    ids = []
    for name in ['Нет оплаты', 'Частично', 'Полностью', 'Переплата']:
        ids.append(client.post('/students', json={'name': name, 'phone': '1', 'group_name': 'A', 'monthly_fee': '100'}).json()['id'])
    for sid, amounts in zip(ids[1:], [['20.10', '30.20'], ['100'], ['120']]):
        for amount in amounts:
            assert add_payment(client, sid, amount).status_code == 201
    result = client.get('/debtors?month=2026-10').json()
    assert [x['id'] for x in result] == ids[:2]
    assert [(x['paid_amount'], x['debt']) for x in result] == [('0.00', '100.00'), ('50.30', '49.70')]
    assert set(result[0]) == {'id', 'name', 'phone', 'group_name', 'monthly_fee', 'paid_amount', 'debt'}
    november = client.get('/debtors?month=2026-11').json()
    assert len(november) == 4 and all(x['debt'] == '100.00' for x in november)


@pytest.mark.parametrize('month,dates', [
    ('2026-10', ['2026-09-30', '2026-10-01', '2026-10-31', '2026-11-01']),
    ('2026-12', ['2026-11-30', '2026-12-01', '2026-12-31', '2027-01-01']),
    ('2027-01', ['2026-12-31', '2027-01-01', '2027-01-31', '2027-02-01']),
    ('2024-02', ['2024-01-31', '2024-02-01', '2024-02-29', '2024-03-01']),
])
def test_month_boundaries(client, student, month, dates):
    for day, amount in zip(dates, ['90', '10.10', '20.20', '90']):
        assert add_payment(client, student['id'], amount, day).status_code == 201
    response = client.get('/debtors', params={'month': month})
    assert response.status_code == 200
    assert response.json()[0]['paid_amount'] == '30.30'
    assert response.json()[0]['debt'] == '69.70'


def test_current_fee_applies_to_past_month(client, student):
    sid = student['id']
    add_payment(client, sid, '25', '2020-01-01')
    client.patch(f'/students/{sid}', json={'monthly_fee': '50'})
    assert client.get('/debtors?month=2020-01').json()[0]['debt'] == '25.00'


@pytest.mark.parametrize('field,value', [
    ('name', ''), ('name', '  '), ('phone', ''), ('phone', 123), ('group_name', '\t'),
    ('name', None), ('phone', None), ('group_name', None), ('monthly_fee', None),
    ('monthly_fee', '0'), ('monthly_fee', '-1'), ('monthly_fee', '0.001'),
    ('monthly_fee', 'NaN'), ('monthly_fee', 'Infinity'), ('monthly_fee', True),
    ('monthly_fee', 12.34), ('monthly_fee', '10000000000'), ('unknown', 'x'),
])
def test_student_validation(client, student, field, value):
    body = {'name': 'Али', 'phone': '1', 'group_name': 'A', 'monthly_fee': '100'}
    assert client.post('/students', json={**body, field: value}).status_code == 422
    response = client.patch(f"/students/{student['id']}", json={field: value})
    assert response.status_code == 422 and response.json()['detail']
    assert client.get(f"/students/{student['id']}").json() == student


@pytest.mark.parametrize('amount', ['0', '-1', '0.001', 'NaN', 'Infinity', None, True, 0.1, '10000000000'])
def test_invalid_payment_amount(client, student, amount):
    assert add_payment(client, student['id'], amount).status_code == 422


@pytest.mark.parametrize('day', ['2026-02-30', '2026-13-01', '21.10.2026', '2026-1-1', '2026-10-01T00:00:00', 0, None])
def test_invalid_date(client, student, day):
    assert add_payment(client, student['id'], '1', day).status_code == 422


@pytest.mark.parametrize('month', ['2026-00', '2026-13', '2026-1', '0000-01', '9999-12', 'bad', '2026-10-01'])
def test_invalid_month(client, month):
    assert client.get('/debtors', params={'month': month}).status_code == 422


def test_missing_students_and_bad_ids(client):
    for method, path, kwargs in [
        ('get', '/students/999', {}), ('patch', '/students/999', {'json': {'name': 'X'}}),
        ('delete', '/students/999', {}), ('get', '/students/999/payments', {}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404 and response.json()['detail'] == 'Ученик не найден'
    assert add_payment(client, 999, '10').status_code == 404
    for sid in [0, -1, True, '1', 9223372036854775808]:
        assert add_payment(client, sid, '10').status_code == 422
    assert client.get('/students/9223372036854775808').status_code == 422
    assert client.get('/debtors').status_code == 422


def test_cascade_and_foreign_key_enforcement(client, student):
    sid = student['id']
    add_payment(client, sid, '10')
    with client.app.state.sessions() as db:
        assert db.execute(text('PRAGMA foreign_keys')).scalar() == 1
        with pytest.raises(IntegrityError):
            db.execute(text("INSERT INTO payments(student_id,amount,payment_date) VALUES (999,100,'2026-10-01')"))
        db.rollback()
    assert client.delete(f'/students/{sid}').status_code == 204
    with client.app.state.sessions() as db:
        assert db.execute(text('SELECT COUNT(*) FROM payments')).scalar() == 0


def test_swagger(client):
    assert client.get('/docs').status_code == 200
    schema = client.get('/openapi.json').json()
    assert set(schema['paths']) == {'/students', '/students/{student_id}', '/payments', '/students/{student_id}/payments', '/debtors', '/summary'}
