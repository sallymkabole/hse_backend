from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Users ─────────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    avatar_color: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar_color: Optional[str] = None


# ── Groups ────────────────────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    name: str
    currency: str = "RWF"


class GroupOut(BaseModel):
    id: str
    name: str
    currency: str
    created_at: datetime
    members: list["GroupMemberOut"] = []

    model_config = {"from_attributes": True}


class GroupMemberOut(BaseModel):
    id: str
    user_id: str
    role: str
    joined_at: datetime
    user: UserOut

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class InviteRequest(BaseModel):
    email: EmailStr


class InvitationOut(BaseModel):
    id: str
    group_id: str
    email: str
    accepted: bool
    expires_at: datetime

    model_config = {"from_attributes": True}


class AcceptInviteRequest(BaseModel):
    name: str
    password: str


# ── Expenses ──────────────────────────────────────────────────────────────────

class SplitIn(BaseModel):
    user_id: str
    share_amount: float


class ExpenseCreate(BaseModel):
    description: str
    category: str = "Other"
    amount: float
    expense_date: date
    notes: Optional[str] = None
    splits: list[SplitIn]

    @field_validator("splits")
    @classmethod
    def splits_must_not_be_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("Expense must have at least one split")
        return v

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class SplitOut(BaseModel):
    id: str
    user_id: str
    share_amount: float
    is_paid: bool
    user: UserOut

    model_config = {"from_attributes": True}


class ExpenseOut(BaseModel):
    id: str
    group_id: str
    paid_by: str
    description: str
    category: str
    amount: float
    expense_date: date
    notes: Optional[str]
    created_at: datetime
    splits: list[SplitOut] = []
    paid_by_user: UserOut

    model_config = {"from_attributes": True}


# ── Settlements ───────────────────────────────────────────────────────────────

class SettlementCreate(BaseModel):
    paid_to: str
    amount: float
    note: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class SettlementOut(BaseModel):
    id: str
    group_id: str
    paid_by: str
    paid_to: str
    amount: float
    note: Optional[str]
    settled_at: datetime
    payer: UserOut
    payee: UserOut

    model_config = {"from_attributes": True}


# ── Balances ──────────────────────────────────────────────────────────────────

class BalanceItem(BaseModel):
    from_user: UserOut
    to_user: UserOut
    amount: float


class GroupBalancesOut(BaseModel):
    balances: list[BalanceItem]
    total_group_spend: float
    my_total_paid: float
    i_owe: float
    owed_to_me: float
    net: float
