import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from bot.main import (APIClient, APIError, debt, format_debtors, parse_pay, pay,
                      split_messages, start, today_tashkent, unknown)
from app.schemas import DebtorOut


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('text', ['/pay', '/pay abc 10', '/pay 0 10', '/pay -1 10',
    '/pay 1 0', '/pay 1 -5', '/pay 1 NaN', '/pay 1 1.001', '/pay 1 1,20', '/pay 1 1e2',
    '/pay 1 10000000000', '/pay 1 10 extra', '/pay 9223372036854775808 1'])
def test_invalid_pay(text):
    with pytest.raises(ValueError, match='Формат:|Пример:'):
        parse_pay(text)


def test_pay_parser():
    payment = parse_pay('/pay@education_bot 12 125000.50')
    assert payment.student_id == 12 and str(payment.amount) == '125000.50'
    assert payment.payment_date == today_tashkent()


def test_tashkent_day_rollover():
    with patch('bot.main.datetime') as clock:
        clock.now.side_effect = lambda tz: datetime(2026, 12, 31, 20, 1, tzinfo=timezone.utc).astimezone(tz)
        assert today_tashkent().isoformat() == '2027-01-01'
        assert parse_pay('/pay 1 10').payment_date.isoformat() == '2027-01-01'


def test_long_debt_list():
    people = [DebtorOut(id=i, name='😀'*200, phone='1'*50, group_name='A'*100,
                       monthly_fee='100.00', paid_amount='20.00', debt='80.00') for i in range(100)]
    text = format_debtors(people, '2026-10')
    chunks = split_messages(text)
    assert len(chunks) > 1 and ''.join(chunks) == text
    assert all(len(c.encode('utf-16-le')) // 2 <= 4096 for c in chunks)
    assert 'должников нет' in format_debtors([], '2026-10')
    assert ''.join(split_messages('😀' * 5000)) == '😀' * 5000


@pytest.mark.parametrize('status', [404, 422, 500])
def test_http_errors(status):
    async def check():
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(
            lambda req: httpx.Response(status, json={'detail': 'internal'}))) as client:
            with pytest.raises(APIError):
                await APIClient(client).debtors('2026-10')
    run(check())


def test_network_error():
    def fail(req):
        raise httpx.ConnectError('private internal details', request=req)
    async def check():
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(APIError, match='API недоступен') as error:
                await APIClient(client).pay(parse_pay('/pay 1 10'))
            assert 'private' not in str(error.value)
    run(check())


@pytest.mark.parametrize('data', [None, {'wrong': 'shape'}, [{'id': 1}]])
def test_bad_api_schema(data):
    async def check():
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=data))) as client:
            with pytest.raises(APIError):
                await APIClient(client).debtors('2026-10')
    run(check())


def test_http_request_and_successful_payment():
    requests = []
    def respond(req):
        requests.append(req)
        return httpx.Response(201, json={'id': 5, 'student_id': 1, 'amount': '10.25', 'payment_date': '2026-10-21'})
    async def check():
        async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(respond)) as client:
            saved = await APIClient(client).pay(parse_pay('/pay 1 10.25'))
            assert str(saved.amount) == '10.25'
    run(check())
    assert requests[0].method == 'POST' and requests[0].url.path == '/payments'
    assert b'"amount":"10.25"' in requests[0].content


def test_handlers():
    async def check():
        message = AsyncMock()
        message.text = '/pay 1 10.25'
        api = AsyncMock()
        from app.schemas import PaymentOut
        api.pay.return_value = PaymentOut(id=3, student_id=1, amount='10.25', payment_date='2026-10-21')
        await pay(message, api)
        assert 'сохранён' in message.answer.call_args.args[0]
        message.text = '/pay wrong'
        api.pay.reset_mock()
        await pay(message, api)
        api.pay.assert_not_called()
        assert 'Пример:' in message.answer.call_args.args[0]
        message.text = '/pay 1 10'
        api.pay.side_effect = APIError('Ученик не найден')
        await pay(message, api)
        assert 'Ученик не найден' in message.answer.call_args.args[0]
        message.text = '/debt'
        api.debtors.return_value = []
        await debt(message, api)
        api.debtors.assert_awaited_once_with(today_tashkent().strftime('%Y-%m'))
        assert 'должников нет' in message.answer.call_args.args[0]
        api.debtors.side_effect = APIError('API недоступен')
        await debt(message, api)
        assert 'API недоступен' in message.answer.call_args.args[0]
        message.text = '/debt extra'
        await debt(message, api)
        assert message.answer.call_args.args[0] == 'Формат: /debt'
        await start(message)
        assert '/pay' in message.answer.call_args.args[0]
        await unknown(message)
        assert '/start' in message.answer.call_args.args[0]
    run(check())
