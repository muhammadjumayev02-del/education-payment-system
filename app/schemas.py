from datetime import date
from decimal import Decimal
import re
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator


def money_input(value):
    # Require a string or integer to avoid converting an IEEE-754 float to money.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Передайте сумму строкой, например "125000.50", или целым числом')
    return value


MoneyValue = Annotated[Decimal, BeforeValidator(money_input), Field(gt=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Group = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentCreate(InputModel):
    name: Name
    phone: Phone
    group_name: Group
    monthly_fee: MoneyValue


class StudentPatch(InputModel):
    name: Name | None = None
    phone: Phone | None = None
    group_name: Group | None = None
    monthly_fee: MoneyValue | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null(cls, values):
        if isinstance(values, dict) and any(v is None for v in values.values()):
            raise ValueError("Обязательные поля нельзя заменить на null")
        return values


class StudentOut(StudentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Дата должна иметь формат YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Указана несуществующая дата") from None


class PaymentCreate(InputModel):
    student_id: Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]
    amount: MoneyValue
    payment_date: Annotated[date, BeforeValidator(calendar_date)]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: int
    amount: Decimal
    payment_date: date


class DebtorOut(StudentOut):
    paid_amount: Decimal
    debt: Decimal


class ErrorOut(BaseModel):
    detail: str
