from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Settlement, Expense, ExpenseSplit, GroupMember, User
from app.schemas import SettlementCreate, SettlementOut, GroupBalancesOut, BalanceItem as BalanceItemSchema, UserOut
from app.auth import get_current_user
from app.debt_engine import compute_group_stats
from app.routers.groups import require_member

router = APIRouter(tags=["settlements & balances"])


# ── Settlements ───────────────────────────────────────────────────────────────

@router.post(
    "/groups/{group_id}/settlements",
    response_model=SettlementOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_settlement(
    group_id: str,
    body: SettlementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)

    # Validate payee is a member
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == body.paid_to)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Payee is not a member of this group")

    if body.paid_to == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot settle with yourself")

    settlement = Settlement(
        group_id=group_id,
        paid_by=current_user.id,
        paid_to=body.paid_to,
        amount=body.amount,
        note=body.note,
    )
    db.add(settlement)
    await db.flush()

    result2 = await db.execute(
        select(Settlement)
        .where(Settlement.id == settlement.id)
        .options(selectinload(Settlement.payer), selectinload(Settlement.payee))
    )
    return result2.scalar_one()


@router.get("/groups/{group_id}/settlements", response_model=list[SettlementOut])
async def list_settlements(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)

    result = await db.execute(
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .options(selectinload(Settlement.payer), selectinload(Settlement.payee))
        .order_by(Settlement.settled_at.desc())
    )
    return result.scalars().all()


# ── Balances ──────────────────────────────────────────────────────────────────

@router.get("/groups/{group_id}/balances", response_model=GroupBalancesOut)
async def get_balances(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)

    # Load all expenses with splits
    exp_result = await db.execute(
        select(Expense)
        .where(Expense.group_id == group_id)
        .options(selectinload(Expense.splits))
    )
    expenses = exp_result.scalars().all()

    # Load all settlements
    set_result = await db.execute(
        select(Settlement).where(Settlement.group_id == group_id)
    )
    settlements = set_result.scalars().all()

    # Load all group members
    mem_result = await db.execute(
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
    )
    users_list = mem_result.scalars().all()
    users_dict = {u.id: u for u in users_list}

    stats = compute_group_stats(expenses, settlements, users_dict, current_user.id)

    return GroupBalancesOut(
        balances=[
            BalanceItemSchema(
                from_user=UserOut.model_validate(b.from_user),
                to_user=UserOut.model_validate(b.to_user),
                amount=b.amount,
            )
            for b in stats["balances"]
        ],
        total_group_spend=stats["total_group_spend"],
        my_total_paid=stats["my_total_paid"],
        i_owe=stats["i_owe"],
        owed_to_me=stats["owed_to_me"],
        net=stats["net"],
    )
