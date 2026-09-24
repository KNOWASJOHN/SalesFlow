import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerOut

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    existing = db.query(Customer).filter(
        Customer.contact_number == payload.contact_number
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "CUSTOMER_ALREADY_EXISTS",
                "message": "A customer with this contact number already exists.",
            },
        )

    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
    if not customer:
        raise HTTPException(
            status_code=404,
            detail={"error": "CUSTOMER_NOT_FOUND", "message": "No customer with this ID exists."},
        )
    return customer