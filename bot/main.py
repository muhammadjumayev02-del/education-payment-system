"""Telegram adapter: all data goes through HTTP, never through database modules."""
import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation
import os
import re
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
import httpx
from pydantic import TypeAdapter, ValidationError

from app.schemas import DebtorOut, PaymentCreate, PaymentOut

router = Router()
TASHKENT = ZoneInfo("Asia/Tashkent")
PAY_HELP = 'Формат: /pay <student_id> <amount>\nПример: /pay 1 150000.50'


def today_tashkent():
    return datetime.now(TASHKENT).date()


def split_messages(text: str, limit: int = 1800):
    """1800 Unicode codepoints fit even as 3600 UTF-16 units (<4096)."""
    chunks = []
    while text:
        end = min(len(text), limit)
        if end < len(text):
            newline = text.rfind("\n", 0, end)
            if newline > 0:
                end = newline + 1
        chunks.append(text[:end])
        text = text[end:]
    return chunks


class APIError(Exception):
    pass


class APIClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.RequestError:
            raise APIError("API недоступен. Проверьте, запущен ли сервер, и повторите позже.") from None
        if response.status_code == 404:
            raise APIError("Ученик не найден. Проверьте student_id.")
        if response.status_code == 422:
            raise APIError("API отклонил данные. Проверьте id, сумму и дату.")
        if not response.is_success:
            raise APIError("Ошибка API. Попробуйте позже.")
        try:
            return response.json()
        except ValueError:
            raise APIError("API вернул некорректный ответ. Обратитесь к администратору.") from None

    async def debtors(self, month):
        data = await self.request("GET", "/debtors", params={"month": month})
        try:
            return TypeAdapter(list[DebtorOut]).validate_python(data)
        except ValidationError:
            raise APIError("API вернул некорректный список должников.") from None

    async def pay(self, payment: PaymentCreate):
        data = await self.request("POST", "/payments", json=payment.model_dump(mode="json"))
        try:
            return PaymentOut.model_validate(data)
        except ValidationError:
            raise APIError("API вернул некорректное подтверждение платежа. Проверьте платежи перед повтором.") from None


def parse_pay(text: str):
    parts = text.split()
    if len(parts) != 3 or not re.fullmatch(r"[0-9]{1,19}", parts[1]):
        raise ValueError(PAY_HELP)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", parts[2]) or len(parts[2]) > 14:
        raise ValueError('Сумма должна быть положительной, максимум 2 знака после точки.\n' + PAY_HELP)
    try:
        return PaymentCreate(student_id=int(parts[1]), amount=Decimal(parts[2]),
                             payment_date=today_tashkent().isoformat())
    except (ValidationError, InvalidOperation):
        raise ValueError('Id и сумма должны быть положительными; сумма — до 9999999999.99.\n' + PAY_HELP) from None


def format_debtors(debtors, month):
    if not debtors:
        return f"За {month} должников нет."
    lines = [f"Должники за {month}:"]
    for s in debtors:
        lines.append(f"\n#{s.id} {s.name}\nТелефон: {s.phone}; группа: {s.group_name}\n"
                     f"Тариф: {s.monthly_fee:.2f} сум; оплачено: {s.paid_amount:.2f} сум; долг: {s.debt:.2f} сум")
    return "\n".join(lines)


@router.message(CommandStart())
async def start(message: Message):
    await message.answer("Учёт платежей учебного центра.\n/debt — должники текущего месяца (Ташкент).\n" + PAY_HELP)


@router.message(Command("debt"))
async def debt(message: Message, api: APIClient):
    if len((message.text or "").split()) != 1:
        await message.answer("Формат: /debt")
        return
    month = today_tashkent().strftime("%Y-%m")
    try:
        text = format_debtors(await api.debtors(month), month)
    except APIError as exc:
        await message.answer(str(exc))
        return
    for chunk in split_messages(text):
        await message.answer(chunk)


@router.message(Command("pay"))
async def pay(message: Message, api: APIClient):
    try:
        payment = parse_pay(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return
    try:
        saved = await api.pay(payment)
    except APIError as exc:
        # POST is never automatically retried: a timeout may follow a successful commit.
        await message.answer(str(exc) + "\nЕсли запрос уже отправлен, проверьте платежи через API перед повтором, чтобы не внести его дважды.")
        return
    await message.answer(f"Платёж #{saved.id} сохранён: ученик #{saved.student_id}, "
                         f"{saved.amount:.2f} сум, дата {saved.payment_date.isoformat()}.")


@router.message()
async def unknown(message: Message):
    await message.answer("Неизвестная команда. Используйте /start, /debt или /pay 1 150000.50.")


async def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    if not token:
        raise SystemExit("Укажите BOT_TOKEN в локальном .env. API может работать без токена.")
    try:
        bot = Bot(token=token)
    except Exception:
        raise SystemExit("BOT_TOKEN имеет неверный формат. Проверьте локальный .env.") from None
    dp = Dispatcher()
    dp.include_router(router)
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10, follow_redirects=False) as client:
            # aiogram error logs may contain Telegram request URLs, so do not enable logging.
            await dp.start_polling(bot, api=APIClient(client), close_bot_session=False)
    except Exception:
        raise SystemExit("Не удалось запустить бота. Проверьте настройки и доступ к Telegram.") from None
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
