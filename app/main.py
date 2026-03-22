from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers import auth, groups, expenses, settlements
from app.routers import invitations


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="HouseManagement API",
    version="1.0.0",
    description="Shared expense tracking for housemates",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(expenses.router)
app.include_router(settlements.router)
app.include_router(invitations.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "housesmanagement-api"}


from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Invitation, Group, GroupMember, User
from app.auth import hash_password, create_access_token
from app.schemas import AcceptInviteRequest, TokenResponse
from datetime import datetime, timezone


@app.get("/invitations/{token}")
async def get_invitation_by_token(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted:
        raise HTTPException(status_code=400, detail="Invitation already accepted")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invitation expired")
    result2 = await db.execute(select(Group).where(Group.id == invitation.group_id))
    group = result2.scalar_one_or_none()
    return {"email": invitation.email, "group_name": group.name, "group_id": group.id}


@app.post("/invitations/{token}/accept", response_model=TokenResponse)
async def accept_invitation_by_token(token: str, body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    from app.routers.auth import AVATAR_COLORS
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted:
        raise HTTPException(status_code=400, detail="Invitation already accepted")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invitation expired")

    result2 = await db.execute(select(User).where(User.email == invitation.email))
    user = result2.scalar_one_or_none()

    if not user:
        count_result = await db.execute(select(User))
        count = len(count_result.scalars().all())
        color = AVATAR_COLORS[count % len(AVATAR_COLORS)]
        user = User(
            name=body.name,
            email=invitation.email,
            hashed_password=hash_password(body.password),
            avatar_color=color,
        )
        db.add(user)
        await db.flush()

    result3 = await db.execute(
        select(GroupMember).where(GroupMember.group_id == invitation.group_id, GroupMember.user_id == user.id)
    )
    if not result3.scalar_one_or_none():
        db.add(GroupMember(group_id=invitation.group_id, user_id=user.id, role="member"))

    invitation.accepted = True
    await db.flush()
    return TokenResponse(access_token=create_access_token(user.id))
