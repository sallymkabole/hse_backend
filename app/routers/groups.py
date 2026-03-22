from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Group, GroupMember, User
from app.schemas import GroupCreate, GroupOut, InviteMemberRequest
from app.auth import get_current_user

router = APIRouter(prefix="/groups", tags=["groups"])


async def get_group_or_404(group_id: str, db: AsyncSession) -> Group:
    result = await db.execute(
        select(Group)
        .where(Group.id == group_id)
        .options(selectinload(Group.members).selectinload(GroupMember.user))
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def require_member(group_id: str, user_id: str, db: AsyncSession) -> GroupMember:
    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")
    return member


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = Group(name=body.name, currency=body.currency)
    db.add(group)
    await db.flush()

    # Creator becomes admin
    membership = GroupMember(group_id=group.id, user_id=current_user.id, role="admin")
    db.add(membership)
    await db.flush()

    return await get_group_or_404(group.id, db)


@router.get("", response_model=list[GroupOut])
async def list_my_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == current_user.id)
        .options(selectinload(Group.members).selectinload(GroupMember.user))
    )
    return result.scalars().all()


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await require_member(group_id, current_user.id, db)
    return await get_group_or_404(group_id, db)


@router.post("/{group_id}/members", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    group_id: str,
    body: InviteMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only admins can invite
    membership = await require_member(group_id, current_user.id, db)
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can invite members")

    # Find user by email
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="No user with that email. They must register first.")

    # Check not already a member
    result2 = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user.id)
    )
    if result2.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member")

    db.add(GroupMember(group_id=group_id, user_id=user.id, role=body.role))
    await db.flush()
    return await get_group_or_404(group_id, db)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    membership = await require_member(group_id, current_user.id, db)
    if membership.role != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")

    result = await db.execute(
        select(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(target)
