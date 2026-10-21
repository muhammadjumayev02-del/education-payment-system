from datetime import date
from decimal import Decimal
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from app.database import Base


class Money(TypeDecorator):
    """Exact Decimal <-> integer tiyin. SQLite never stores money as REAL."""
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("Money must be a finite Decimal")
        tiyin = value * 100
        if tiyin != tiyin.to_integral_value():
            raise ValueError("Money must have at most two decimal places")
        return int(tiyin)

    def process_result_value(self, value, dialect):
        return None if value is None else (Decimal(value) / 100).quantize(Decimal("0.01"))


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (CheckConstraint("monthly_fee > 0", name="positive_fee"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50))
    group_name: Mapped[str] = mapped_column(String(100))
    monthly_fee: Mapped[Decimal] = mapped_column(Money())


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        Index("ix_payment_student_date", "student_id", "payment_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Money())
    payment_date: Mapped[date] = mapped_column(Date)
