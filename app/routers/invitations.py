import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.database import get_db
from app.models import Invitation, Group, GroupMember, User
from app.schemas import InviteRequest, InvitationOut, AcceptInviteRequest, TokenResponse
from app.auth import get_current_user, hash_password, create_access_token
from app.config import settings
from app.routers.groups import require_member, get_group_or_404

router = APIRouter(prefix="/groups/{group_id}/invitations", tags=["invitations"])


def send_invite_email(to_email: str, inviter_name: str, group_name: str, token: str):
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    invite_link = f"{frontend_url}/invite?token={token}"

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=f"You've been invited to join {group_name} on HouseSplit",
        html_content=f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
            <h2>You're invited!</h2>
            <p><strong>{inviter_name}</strong> has invited you to join <strong>{group_name}</strong> on HouseSplit.</p>
            <p>Click the button below to accept the invitation:</p>
            <a href="{invite_link}" style="
                display: inline-block;
                padding: 12px 24px;
                background: #6ee7b7;
                color: #0a1a12;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
                margin: 16px 0;
            ">Accept Invitation</a>
            <p style="color: #666; font-size: 12px;">This link expires in 7 days.</p>
        </div>
        """
    )
    sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
    sg.send(message)


@router.post("", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    group_id: str,
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Any member can invite
    await require_member(group_id, current_user.id, db)
    group = await get_group_or_404(group_id, db)

    email = body.email.lower()

    # If user already exists, add them directly
    result = await db.execute(select(User).where(User.email == email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        # Check not already a member
        result2 = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == existing_user.id,
            )
        )
        if result2.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="User is already a member")

        db.add(GroupMember(group_id=group_id, user_id=existing_user.id, role="member"))
        await db.flush()

    # Always create an invitation record and send email
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    invitation = Invitation(
        group_id=group_id,
        invited_by=current_user.id,
        email=email,
        token=token,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.flush()

    try:
        send_invite_email(email, current_user.name, group.name, token)
    except Exception:
        pass  # Don't fail if email fails

    return invitation


@router.get("/token/{token}", response_model=dict)
async def get_invitation(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted:
        raise HTTPException(status_code=400, detail="Invitation already accepted")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invitation expired")

    group = await get_group_or_404(invitation.group_id, db)
    return {"email": invitation.email, "group_name": group.name, "group_id": group.id}


@router.post("/token/{token}/accept", response_model=TokenResponse)
async def accept_invitation(
    token: str,
    body: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted:
        raise HTTPException(status_code=400, detail="Invitation already accepted")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invitation expired")

    # Check if user already exists
    result2 = await db.execute(select(User).where(User.email == invitation.email))
    user = result2.scalar_one_or_none()

    if not user:
        # Register new user
        from app.routers.auth import AVATAR_COLORS
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

    # Add to group if not already a member
    result3 = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == invitation.group_id,
            GroupMember.user_id == user.id,
        )
    )
    if not result3.scalar_one_or_none():
        db.add(GroupMember(group_id=invitation.group_id, user_id=user.id, role="member"))

    invitation.accepted = True
    await db.flush()

    jwt = create_access_token(user.id)
    return TokenResponse(access_token=jwt)
