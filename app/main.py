from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path as FilePath
from zoneinfo import ZoneInfo
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from decimal import Decimal
import re
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session, sessionmaker
from app.database import Base, database_url, make_engine
from app.models import Payment, Student
from app.schemas import DebtorOut, ErrorOut, PaymentCreate, PaymentOut, StudentCreate, StudentOut, StudentPatch


def get_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(get_session)]
StudentID = Annotated[int, Path(gt=0, le=9223372036854775807)]


def find_student(session: Session, student_id: int):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "Ученик не найден")
    return student


def month_bounds(month: str):
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Месяц должен иметь формат YYYY-MM, например 2026-10")
    year, number = map(int, month.split("-"))
    if year < 1 or (year == 9999 and number == 12):
        raise HTTPException(422, "Поддерживаются месяцы от 0001-01 до 9999-11")
    return date(year, number, 1), date(year + (number == 12), 1 if number == 12 else number + 1, 1)


def create_app(url: str | None = None):
    @asynccontextmanager
    async def lifespan(app):
        engine = make_engine(url or database_url())
        Base.metadata.create_all(engine)
        app.state.sessions = sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Учёт платежей учебного центра", version="1.0.0", lifespan=lifespan)
    assets = FilePath(__file__).parent
    app.mount("/static", StaticFiles(directory=assets / "static"), name="static")
    templates = Jinja2Templates(directory=assets / "templates")

    @app.get("/", include_in_schema=False)
    def website(request: Request):
        today = datetime.now(ZoneInfo("Asia/Tashkent")).date().isoformat()
        return templates.TemplateResponse(request=request, name="index.html", context={"today": today})

    @app.get("/summary")
    def summary(db: DB, month: Annotated[str, Query(description="Месяц YYYY-MM")]):
        start, end = month_bounds(month)
        tiyin = db.scalar(select(func.sum(cast(Payment.amount, Integer))).where(
            Payment.payment_date >= start, Payment.payment_date < end)) or 0
        debts = debtors(db, month)
        return {"month": month, "paid_amount": format(Decimal(tiyin) / 100, ".2f"),
                "debt": format(sum((d.debt for d in debts), Decimal("0")), ".2f"),
                "debtor_count": len(debts)}

    missing = {404: {"model": ErrorOut}}

    @app.post("/students", response_model=StudentOut, status_code=201)
    def create_student(body: StudentCreate, db: DB):
        student = Student(**body.model_dump())
        db.add(student)
        db.commit()
        db.refresh(student)
        return student

    @app.get("/students", response_model=list[StudentOut])
    def students(db: DB):
        return db.scalars(select(Student).order_by(Student.id)).all()

    @app.get("/students/{student_id}", response_model=StudentOut, responses=missing)
    def student(student_id: StudentID, db: DB):
        return find_student(db, student_id)

    @app.patch("/students/{student_id}", response_model=StudentOut, responses=missing)
    def update_student(student_id: StudentID, body: StudentPatch, db: DB):
        student = find_student(db, student_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(student, field, value)
        db.commit()
        db.refresh(student)
        return student

    @app.delete("/students/{student_id}", status_code=204, responses=missing)
    def delete_student(student_id: StudentID, db: DB):
        db.delete(find_student(db, student_id))
        db.commit()
        return Response(status_code=204)

    @app.post("/payments", response_model=PaymentOut, status_code=201, responses=missing)
    def create_payment(body: PaymentCreate, db: DB):
        find_student(db, body.student_id)
        payment = Payment(**body.model_dump())
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment

    @app.get("/students/{student_id}/payments", response_model=list[PaymentOut], responses=missing)
    def payments(student_id: StudentID, db: DB):
        find_student(db, student_id)
        return db.scalars(select(Payment).where(Payment.student_id == student_id)
                          .order_by(Payment.payment_date, Payment.id)).all()

    @app.get("/debtors", response_model=list[DebtorOut], responses={422: {"description": "Некорректный месяц"}})
    def debtors(db: DB, month: Annotated[str, Query(description="Месяц YYYY-MM")]):
        start, end = month_bounds(month)
        # SUM operates on integer tiyin, without SQLite REAL or Decimal coercion.
        paid = (select(Payment.student_id, func.sum(cast(Payment.amount, Integer)).label("tiyin"))
                .where(Payment.payment_date >= start, Payment.payment_date < end)
                .group_by(Payment.student_id).subquery())
        rows = db.execute(select(Student, paid.c.tiyin).outerjoin(paid, Student.id == paid.c.student_id)
                          .order_by(Student.id))
        result = []
        for student, tiyin in rows:
            paid_amount = (Decimal(tiyin or 0) / 100).quantize(Decimal("0.01"))
            debt = student.monthly_fee - paid_amount
            if debt > 0:
                result.append(DebtorOut(**StudentOut.model_validate(student).model_dump(),
                                        paid_amount=paid_amount, debt=debt))
        return result

    return app


app = create_app()
