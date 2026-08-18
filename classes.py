from abc import ABC, abstractmethod
from datetime import datetime, date
from itertools import count

from exceptions import (
    InvalidPINError,
    CardBlockedError,
    InsufficientBalanceError,
    InsufficientATMFundsError,
    InvalidAmountError,
    AccountInactiveError,
    DailyLimitExceededError,
    InvalidAccountError,
    DenominationError
)


# ============================================================
# 1. TRANSACTION HIERARCHY
# ============================================================

class Transaction(ABC):
    """Abstract base class for all transactions."""

    _id_counter = count(1001)

    def __init__(self, account, amount):
        self.transaction_id = f"TXN-{next(Transaction._id_counter)}"
        self.amount = amount
        self.timestamp = datetime.now()
        self.account = account
        self.status = "PENDING"

    @abstractmethod
    def execute(self):
        """Execute the transaction."""
        pass

    def _mark_success(self):
        self.status = "SUCCESS"

    def _mark_failed(self):
        self.status = "FAILED"

    def __str__(self):
        sign = "+" if self.amount >= 0 else ""
        transaction_type = (
            self.__class__.__name__
            .replace("Transaction", "")
            .upper()
        )

        return (
            f"{self.transaction_id} | "
            f"{transaction_type:<10} | "
            f"{sign}{self.amount:,.2f} | "
            f"{self.timestamp:%d-%b %H:%M} | "
            f"{self.status}"
        )


class DepositTransaction(Transaction):

    def execute(self):
        self.account._credit(self.amount)
        self._mark_success()


class WithdrawalTransaction(Transaction):

    def execute(self):
        self.account._debit(abs(self.amount))
        self._mark_success()


class TransferTransaction(Transaction):
    """One side of a transfer: DEBIT or CREDIT."""

    def __init__(
        self,
        account,
        amount,
        counterpart_account,
        direction
    ):
        super().__init__(account, amount)

        self.counterpart_account = counterpart_account
        self.direction = direction

    def execute(self):

        if self.direction == "DEBIT":
            self.account._debit(abs(self.amount))
        else:
            self.account._credit(abs(self.amount))

        self._mark_success()

    def __str__(self):

        sign = "+" if self.amount >= 0 else ""

        return (
            f"{self.transaction_id} | "
            f"TRANSFER({self.direction[0]}) | "
            f"{sign}{self.amount:,.2f} | "
            f"with {self.counterpart_account.account_number} | "
            f"{self.timestamp:%d-%b %H:%M} | "
            f"{self.status}"
        )


# ============================================================
# 2. ACCOUNT HIERARCHY
# ============================================================

class Account(ABC):
    """
    Abstract base Account class.

    Demonstrates:
    - Encapsulation
    - Abstraction
    - Inheritance
    - Polymorphism
    """

    WITHDRAWAL_FEE = 50
    TRANSFER_FEE = 100

    MIN_WITHDRAWAL = 500

    DAILY_WITHDRAWAL_LIMIT = 100000
    DAILY_TRANSFER_LIMIT = 100000

    _acct_counter = count(10000001)

    def __init__(
        self,
        holder,
        pin,
        opening_balance=0.0
    ):

        self.account_number = str(
            next(Account._acct_counter)
        )

        self.holder = holder

        # Encapsulation
        self._balance = float(opening_balance)
        self._pin = self._validate_pin_format(pin)
        self._status = "ACTIVE"

        self._transaction_history = []

        self._daily_withdrawn = 0.0
        self._daily_transferred = 0.0

        self._last_reset_date = date.today()

    # ========================================================
    # STATUS
    # ========================================================

    @property
    def status(self):
        return self._status

    def _set_status(self, status):

        allowed_statuses = {
            "ACTIVE",
            "BLOCKED",
            "INACTIVE"
        }

        if status not in allowed_statuses:
            raise ValueError(
                "Invalid account status."
            )

        self._status = status

    def block_account(self):
        self._set_status("BLOCKED")

    def deactivate_account(self):
        self._set_status("INACTIVE")

    def activate_account(self):
        self._set_status("ACTIVE")

    # ========================================================
    # PIN
    # ========================================================

    @staticmethod
    def _validate_pin_format(pin):

        if not (
            isinstance(pin, str)
            and pin.isdigit()
            and len(pin) == 4
        ):
            raise InvalidPINError(
                "PIN must be exactly 4 digits."
            )

        return pin

    def _check_pin(self, pin):
        return pin == self._pin

    def change_pin(self, old_pin, new_pin):

        self._ensure_active()

        if not self._check_pin(old_pin):
            raise InvalidPINError(
                "Old PIN is incorrect."
            )

        self._pin = self._validate_pin_format(
            new_pin
        )

    # ========================================================
    # ACCOUNT VALIDATION
    # ========================================================

    def _ensure_active(self):

        if self._status != "ACTIVE":
            raise AccountInactiveError(
                f"Account {self.account_number} "
                f"is {self._status}."
            )

    # ========================================================
    # DAILY LIMITS
    # ========================================================

    def _reset_daily_limits_if_needed(self):

        if self._last_reset_date != date.today():

            self._daily_withdrawn = 0.0
            self._daily_transferred = 0.0

            self._last_reset_date = date.today()

    # ========================================================
    # BALANCE
    # ========================================================

    def _credit(self, amount):

        if amount <= 0:
            raise InvalidAmountError(
                "Credit amount must be positive."
            )

        self._balance += amount

    def _debit(self, amount):

        if amount <= 0:
            raise InvalidAmountError(
                "Debit amount must be positive."
            )

        self._balance -= amount

    def check_balance(self):

        self._ensure_active()

        return self._balance

    # ========================================================
    # DEPOSIT
    # ========================================================

    def deposit(self, amount):

        self._ensure_active()

        if amount <= 0:
            raise InvalidAmountError(
                "Deposit amount must be positive."
            )

        transaction = DepositTransaction(
            self,
            amount
        )

        transaction.execute()

        self._transaction_history.append(
            transaction
        )

        return transaction

    # ========================================================
    # POLYMORPHISM
    # ========================================================

    @abstractmethod
    def calculate_withdrawal_limit(self):
        """
        Different account types have
        different withdrawal limits.
        """
        pass

    @abstractmethod
    def _min_balance_after_withdrawal(
        self,
        amount
    ):
        """
        Account-specific balance rules.
        """
        pass

    # ========================================================
    # WITHDRAW
    # ========================================================

    def withdraw(
        self,
        amount,
        atm=None,
        charge_fee=True
    ):

        self._ensure_active()

        self._reset_daily_limits_if_needed()

        if amount <= 0:
            raise InvalidAmountError(
                "Withdrawal amount must be positive."
            )

        if amount < self.MIN_WITHDRAWAL:
            raise InvalidAmountError(
                f"Minimum withdrawal is "
                f"Rs. {self.MIN_WITHDRAWAL}."
            )

        withdrawal_limit = (
            self.calculate_withdrawal_limit()
        )

        if amount > withdrawal_limit:
            raise InvalidAmountError(
                f"Amount exceeds per-transaction "
                f"limit of Rs. "
                f"{withdrawal_limit:,.0f}."
            )

        if (
            self._daily_withdrawn + amount
            > self.DAILY_WITHDRAWAL_LIMIT
        ):
            raise DailyLimitExceededError(
                "Daily withdrawal limit exceeded."
            )

        fee = (
            self.WITHDRAWAL_FEE
            if charge_fee
            else 0
        )

        total_deduction = amount + fee

        if not self._min_balance_after_withdrawal(
            total_deduction
        ):
            raise InsufficientBalanceError(
                "Insufficient balance for "
                "this withdrawal."
            )

        # Check ATM before changing balance
        if atm is not None:
            atm.verify_can_dispense(amount)

        transaction = WithdrawalTransaction(
            self,
            -total_deduction
        )

        transaction.execute()

        self._transaction_history.append(
            transaction
        )

        if atm is not None:
            atm.dispense_cash(amount)

        self._daily_withdrawn += amount

        return transaction

    # ========================================================
    # TRANSFER
    # ========================================================

    def transfer(
        self,
        target_account,
        amount,
        charge_fee=True
    ):

        self._ensure_active()

        self._reset_daily_limits_if_needed()

        if not isinstance(
            target_account,
            Account
        ):
            raise InvalidAccountError(
                "Receiver account does not exist."
            )

        if (
            target_account.account_number
            == self.account_number
        ):
            raise InvalidAccountError(
                "Sender and receiver cannot "
                "be the same account."
            )

        if amount <= 0:
            raise InvalidAmountError(
                "Transfer amount must be positive."
            )

        target_account._ensure_active()

        fee = (
            self.TRANSFER_FEE
            if charge_fee
            else 0
        )

        total_deduction = amount + fee

        if not self._min_balance_after_withdrawal(
            total_deduction
        ):
            raise InsufficientBalanceError(
                "Insufficient balance for "
                "this transfer."
            )

        if (
            self._daily_transferred + amount
            > self.DAILY_TRANSFER_LIMIT
        ):
            raise DailyLimitExceededError(
                "Daily transfer limit exceeded."
            )

        # Sender transaction
        debit_transaction = TransferTransaction(
            self,
            -total_deduction,
            target_account,
            "DEBIT"
        )

        debit_transaction.execute()

        self._transaction_history.append(
            debit_transaction
        )

        # Receiver transaction
        credit_transaction = TransferTransaction(
            target_account,
            amount,
            self,
            "CREDIT"
        )

        credit_transaction.execute()

        target_account._transaction_history.append(
            credit_transaction
        )

        self._daily_transferred += amount

        return (
            debit_transaction,
            credit_transaction
        )

    # ========================================================
    # MINI STATEMENT
    # ========================================================

    def mini_statement(self, n=5):

        self._ensure_active()

        return list(
            reversed(
                self._transaction_history[-n:]
            )
        )

    # ========================================================
    # STRING
    # ========================================================

    def __str__(self):

        return (
            f"{self.__class__.__name__} "
            f"#{self.account_number} | "
            f"Balance: Rs. "
            f"{self._balance:,.2f} | "
            f"Status: {self._status}"
        )


# ============================================================
# 3. SAVINGS ACCOUNT
# ============================================================

class SavingsAccount(Account):
    """
    Savings Account:
    - Minimum balance: Rs. 5,000
    - Maximum withdrawal per transaction: Rs. 50,000
    """

    MIN_BALANCE = 5000
    WITHDRAWAL_LIMIT_PER_TXN = 50000

    def __init__(
        self,
        holder,
        pin,
        opening_balance=0.0
    ):

        if opening_balance < self.MIN_BALANCE:
            raise InvalidAmountError(
                "Savings Account requires minimum "
                "opening balance of Rs. 5,000."
            )

        super().__init__(
            holder,
            pin,
            opening_balance
        )

    def calculate_withdrawal_limit(self):

        return self.WITHDRAWAL_LIMIT_PER_TXN

    def _min_balance_after_withdrawal(
        self,
        amount
    ):

        return (
            self._balance - amount
            >= self.MIN_BALANCE
        )


# ============================================================
# 4. CURRENT ACCOUNT
# ============================================================

class CurrentAccount(Account):
    """
    Current Account:
    - Overdraft limit: Rs. 50,000
    - Withdrawal limit per transaction: Rs. 75,000
    """

    OVERDRAFT_LIMIT = 50000
    WITHDRAWAL_LIMIT_PER_TXN = 75000

    def calculate_withdrawal_limit(self):

        return self.WITHDRAWAL_LIMIT_PER_TXN

    def _min_balance_after_withdrawal(
        self,
        amount
    ):

        return (
            self._balance - amount
            >= -self.OVERDRAFT_LIMIT
        )


# ============================================================
# 5. CARD
# ============================================================

class Card:

    MAX_PIN_ATTEMPTS = 3

    _card_counter = count(
        4000_0000_0000_0001
    )

    def __init__(self, account):

        self.card_number = str(
            next(Card._card_counter)
        )

        self.account = account

        # Encapsulated card status
        self._status = "ACTIVE"

        self._failed_attempts = 0

    # ========================================================
    # CARD STATUS
    # ========================================================

    @property
    def status(self):
        return self._status

    def _block(self):

        self._status = "BLOCKED"

        # Block linked account too
        self.account.block_account()

    def unblock(self):

        self._status = "ACTIVE"

        self._failed_attempts = 0

        self.account.activate_account()

    # ========================================================
    # PIN VALIDATION
    # ========================================================

    def validate_pin(self, pin):

        if self._status == "BLOCKED":

            raise CardBlockedError(
                "This card is blocked. "
                "Please contact your bank."
            )

        if self.account._check_pin(pin):

            self._failed_attempts = 0

            return True

        self._failed_attempts += 1

        if (
            self._failed_attempts
            >= self.MAX_PIN_ATTEMPTS
        ):

            self._block()

            raise CardBlockedError(
                "Card blocked after "
                "3 incorrect PIN attempts."
            )

        remaining = (
            self.MAX_PIN_ATTEMPTS
            - self._failed_attempts
        )

        raise InvalidPINError(
            f"Incorrect PIN. "
            f"{remaining} attempt(s) remaining."
        )

    def __str__(self):

        return (
            f"Card {self.card_number} "
            f"[{self._status}] -> "
            f"Account "
            f"{self.account.account_number}"
        )


# ============================================================
# 6. CUSTOMER
# ============================================================

class Customer:

    _cust_counter = count(1)

    def __init__(
        self,
        name,
        contact
    ):

        self.customer_id = (
            f"CUST-"
            f"{next(Customer._cust_counter):04d}"
        )

        self.name = name
        self.contact = contact

        # One customer can have multiple accounts
        self.accounts = []

        # One customer can have multiple cards
        self.cards = []

    def add_account(self, account):

        self.accounts.append(account)

    def add_card(self, card):

        self.cards.append(card)

    def __str__(self):

        return (
            f"{self.customer_id} - "
            f"{self.name}"
        )


# ============================================================
# 7. BANK
# ============================================================

class Bank:

    def __init__(self, name):

        self.name = name

        self.customers = {}
        self.accounts = {}
        self.cards = {}

    # ========================================================
    # CUSTOMER
    # ========================================================

    def register_customer(
        self,
        name,
        contact
    ):

        customer = Customer(
            name,
            contact
        )

        self.customers[
            customer.customer_id
        ] = customer

        return customer

    # ========================================================
    # ACCOUNT
    # ========================================================

    def open_account(
        self,
        customer,
        account_type,
        pin,
        opening_balance=0.0
    ):

        account_type = account_type.lower()

        if account_type == "savings":

            account = SavingsAccount(
                customer,
                pin,
                opening_balance
            )

        elif account_type == "current":

            account = CurrentAccount(
                customer,
                pin,
                opening_balance
            )

        else:

            raise ValueError(
                "Account type must be "
                "'savings' or 'current'."
            )

        customer.add_account(account)

        self.accounts[
            account.account_number
        ] = account

        return account

    # ========================================================
    # CARD
    # ========================================================

    def issue_card(
        self,
        customer,
        account
    ):

        if account not in customer.accounts:

            raise InvalidAccountError(
                "Account does not belong "
                "to this customer."
            )

        card = Card(account)

        customer.add_card(card)

        self.cards[
            card.card_number
        ] = card

        return card

    # ========================================================
    # FIND ACCOUNT
    # ========================================================

    def find_account(
        self,
        account_number
    ):

        account = self.accounts.get(
            account_number
        )

        if account is None:

            raise InvalidAccountError(
                f"Account {account_number} "
                f"not found."
            )

        return account

    # ========================================================
    # FIND CARD
    # ========================================================

    def find_card(
        self,
        card_number
    ):

        card = self.cards.get(
            card_number
        )

        if card is None:

            raise InvalidAccountError(
                f"Card {card_number} "
                f"not found."
            )

        return card


# ============================================================
# 8. ATM
# ============================================================

class ATM:

    def __init__(
        self,
        atm_id,
        bank,
        denominations=None
    ):

        self.atm_id = atm_id
        self.bank = bank

        self.denominations = (
            denominations
            or {
                500: 10,
                1000: 20,
                5000: 10
            }
        )

        self.current_card = None
        self.current_account = None

    # ========================================================
    # TOTAL CASH
    # ========================================================

    @property
    def total_cash(self):

        return sum(
            note * quantity
            for note, quantity
            in self.denominations.items()
        )

    # ========================================================
    # FIND NOTE COMBINATION
    # ========================================================

    def _dispensable_combo(self, amount):

        remaining = amount
        plan = {}

        for note in sorted(
            self.denominations,
            reverse=True
        ):

            available = self.denominations[note]

            use = min(
                available,
                remaining // note
            )

            if use:

                plan[note] = int(use)

                remaining -= (
                    use * note
                )

        if remaining == 0:
            return plan

        return None

    # ========================================================
    # CHECK ATM CASH
    # ========================================================

    def verify_can_dispense(
        self,
        amount
    ):

        if amount > self.total_cash:

            raise InsufficientATMFundsError(
                "ATM has insufficient cash. "
                "Please try another amount."
            )

        if (
            self._dispensable_combo(amount)
            is None
        ):

            raise DenominationError(
                "Requested amount cannot be "
                "dispensed with available "
                "denominations."
            )

    # ========================================================
    # DISPENSE CASH
    # ========================================================

    def dispense_cash(self, amount):

        plan = self._dispensable_combo(
            amount
        )

        if plan is None:

            raise DenominationError(
                "Cannot dispense the "
                "requested amount."
            )

        for note, quantity in plan.items():

            self.denominations[note] -= quantity

        return plan

    # ========================================================
    # INSERT CARD
    # ========================================================

    def insert_card(
        self,
        card_number
    ):

        card = self.bank.find_card(
            card_number
        )

        if card.status == "BLOCKED":

            raise CardBlockedError(
                "This card is blocked. "
                "Please contact your bank."
            )

        self.current_card = card

        return card

    # ========================================================
    # ENTER PIN
    # ========================================================

    def enter_pin(self, pin):

        if self.current_card is None:

            raise InvalidAccountError(
                "No card inserted."
            )

        self.current_card.validate_pin(
            pin
        )

        self.current_account = (
            self.current_card.account
        )

        return True

    # ========================================================
    # EJECT CARD
    # ========================================================

    def eject_card(self):

        self.current_card = None
        self.current_account = None