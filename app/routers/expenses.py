from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Expense, ExpenseSplit, GroupMember, User
from app.schemas import ExpenseCreate, ExpenseOut
from app.auth import get_current_user
from app.routers.groups import require_member

router = APIRouter(prefix="/groups/{group_id}/expenses", tags=["expenses"])


async def load_expense(expense_id: str, db: AsyncSession) -> Expense:
    result = await db.execute(
        select(Expense)
        .where(Expense.id == expense_id)
        .options(
            selectinload(Expense.splits).selectinload(ExpenseSplit.user),
            selectinload(Expense.paid_by_user),
        )
    )
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    return exp


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_expense(
    group_id: str,
    body: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)

    # Validate split user_ids are all members
    member_result = await db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    member_ids = {row for row in member_result.scalars().all()}
    split_ids = {s.user_id for s in body.splits}
    if not split_ids.issubset(member_ids):
        raise HTTPException(status_code=400, detail="All split users must be group members")

    # Validate split amounts add up (within 1 unit rounding tolerance)
    total_splits = sum(s.share_amount for s in body.splits)
    if abs(total_splits - body.amount) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({total_splits}) do not match expense amount ({body.amount})"
        )

    expense = Expense(
        group_id=group_id,
        paid_by=current_user.id,
        description=body.description,
        category=body.category,
        amount=body.amount,
        expense_date=body.expense_date,
        notes=body.notes,
    )
    db.add(expense)
    await db.flush()

    for split in body.splits:
        db.add(ExpenseSplit(
            expense_id=expense.id,
            user_id=split.user_id,
            share_amount=split.share_amount,
            is_paid=(split.user_id == current_user.id),
        ))

    await db.flush()
    return await load_expense(expense.id, db)


@router.get("", response_model=list[ExpenseOut])
async def list_expenses(
    group_id: str,
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)

    q = (
        select(Expense)
        .where(Expense.group_id == group_id)
        .options(
            selectinload(Expense.splits).selectinload(ExpenseSplit.user),
            selectinload(Expense.paid_by_user),
        )
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
    )
    if category:
        q = q.where(Expense.category == category)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{expense_id}", response_model=ExpenseOut)
async def get_expense(
    group_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)
    exp = await load_expense(expense_id, db)
    if exp.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    return exp


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    group_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)
    result = await db.execute(select(Expense).where(Expense.id == expense_id))
    expense = result.scalar_one_or_none()
    if not expense or expense.group_id != group_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    if expense.paid_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the payer can delete this expense")
    await db.delete(expense)
