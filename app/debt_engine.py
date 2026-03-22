"""
Debt engine — computes net balances across all expenses and settlements.

Algorithm:
1. For each expense split, the non-payer owes the payer their share.
2. For each settlement, reduce the debt from payer → payee.
3. Cancel out mutual debts (A owes B 100, B owes A 60 → A owes B 40).
4. Return the minimal list of transactions to clear all debts.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from app.models import Expense, Settlement, User


@dataclass
class BalanceItem:
    from_user: User
    to_user: User
    amount: float


def compute_balances(
    expenses: list[Expense],
    settlements: list[Settlement],
    users: dict[str, User],
) -> list[BalanceItem]:
    """
    Returns the minimum set of payments to settle all debts.
    net[A][B] = how much A owes B (before netting)
    """
    net: DefaultDict[str, DefaultDict[str, float]] = defaultdict(lambda: defaultdict(float))

    # Step 1 — accrue debts from expense splits
    for expense in expenses:
        for split in expense.splits:
            if split.user_id == expense.paid_by:
                continue  # payer's own share — no debt
            net[split.user_id][expense.paid_by] += float(split.share_amount)

    # Step 2 — reduce debts from settlements
    for s in settlements:
        net[s.paid_by][s.paid_to] = max(0.0, net[s.paid_by][s.paid_to] - float(s.amount))

    # Step 3 — cancel out mutual debts pairwise
    result: list[BalanceItem] = []
    seen: set[frozenset] = set()

    for uid_a in list(net.keys()):
        for uid_b in list(net[uid_a].keys()):
            pair = frozenset({uid_a, uid_b})
            if pair in seen:
                continue
            seen.add(pair)

            ab = net[uid_a][uid_b]  # A owes B
            ba = net[uid_b][uid_a]  # B owes A
            diff = ab - ba

            if abs(diff) < 1:  # below 1 RWF — treat as settled
                continue

            if diff > 0:
                from_id, to_id, amount = uid_a, uid_b, diff
            else:
                from_id, to_id, amount = uid_b, uid_a, -diff

            from_user = users.get(from_id)
            to_user = users.get(to_id)
            if from_user and to_user:
                result.append(BalanceItem(from_user=from_user, to_user=to_user, amount=round(amount, 2)))

    # Sort: largest debts first
    result.sort(key=lambda b: b.amount, reverse=True)
    return result


def compute_group_stats(
    expenses: list[Expense],
    settlements: list[Settlement],
    users: dict[str, User],
    current_user_id: str,
) -> dict:
    balances = compute_balances(expenses, settlements, users)
    total_spend = sum(float(e.amount) for e in expenses)
    my_paid = sum(float(e.amount) for e in expenses if e.paid_by == current_user_id)
    i_owe = sum(b.amount for b in balances if b.from_user.id == current_user_id)
    owed_to_me = sum(b.amount for b in balances if b.to_user.id == current_user_id)
    return {
        "balances": balances,
        "total_group_spend": round(total_spend, 2),
        "my_total_paid": round(my_paid, 2),
        "i_owe": round(i_owe, 2),
        "owed_to_me": round(owed_to_me, 2),
        "net": round(owed_to_me - i_owe, 2),
    }
