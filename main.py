from abc import ABC, abstractmethod
from datetime import datetime, date
from itertools import count
import customtkinter as ctk
from tkinter import messagebox

# ============================================================
# 1. CUSTOM EXCEPTIONS
# ============================================================
class InvalidPINError(Exception): pass
class CardBlockedError(Exception): pass
class InsufficientBalanceError(Exception): pass
class InsufficientATMFundsError(Exception): pass
class InvalidAmountError(Exception): pass
class AccountInactiveError(Exception): pass
class DailyLimitExceededError(Exception): pass
class InvalidAccountError(Exception): pass
class DenominationError(Exception): pass


# ============================================================
# 2. TRANSACTION HIERARCHY
# ============================================================
class Transaction(ABC):
    _id_counter = count(1001)

    def __init__(self, account, amount):
        self.transaction_id = f"TXN-{next(Transaction._id_counter)}"
        self.amount = amount
        self.timestamp = datetime.now()
        self.account = account
        self.status = "PENDING"

    @abstractmethod
    def execute(self):
        pass

    def _mark_success(self):
        self.status = "SUCCESS"

    def _mark_failed(self):
        self.status = "FAILED"

    def __str__(self):
        sign = "+" if self.amount >= 0 else ""
        transaction_type = self.__class__.__name__.replace("Transaction", "").upper()
        return (
            f"{self.transaction_id} | "
            f"{transaction_type:<12} | "
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
    def __init__(self, account, amount, counterpart_account, direction):
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
# 3. ACCOUNT HIERARCHY
# ============================================================
class Account(ABC):
    WITHDRAWAL_FEE = 50
    TRANSFER_FEE = 100
    MIN_WITHDRAWAL = 500
    DAILY_WITHDRAWAL_LIMIT = 100000
    DAILY_TRANSFER_LIMIT = 100000
    _acct_counter = count(10000001)

    def __init__(self, holder, pin, opening_balance=0.0):
        self.account_number = str(next(Account._acct_counter))
        self.holder = holder
        self._balance = float(opening_balance)
        self._pin = self._validate_pin_format(pin)
        self._status = "ACTIVE"
        self._transaction_history = []
        self._daily_withdrawn = 0.0
        self._daily_transferred = 0.0
        self._last_reset_date = date.today()

    @property
    def status(self):
        return self._status

    def _set_status(self, status):
        allowed_statuses = {"ACTIVE", "BLOCKED", "INACTIVE"}
        if status not in allowed_statuses:
            raise ValueError("Invalid account status.")
        self._status = status

    def block_account(self):
        self._set_status("BLOCKED")

    def deactivate_account(self):
        self._set_status("INACTIVE")

    def activate_account(self):
        self._set_status("ACTIVE")

    @staticmethod
    def _validate_pin_format(pin):
        if not (isinstance(pin, str) and pin.isdigit() and len(pin) == 4):
            raise InvalidPINError("PIN must be exactly 4 digits.")
        return pin

    def _check_pin(self, pin):
        return pin == self._pin

    def change_pin(self, old_pin, new_pin):
        self._ensure_active()
        if not self._check_pin(old_pin):
            raise InvalidPINError("Old PIN is incorrect.")
        self._pin = self._validate_pin_format(new_pin)

    def _ensure_active(self):
        if self._status != "ACTIVE":
            raise AccountInactiveError(f"Account {self.account_number} is {self._status}.")

    def _reset_daily_limits_if_needed(self):
        if self._last_reset_date != date.today():
            self._daily_withdrawn = 0.0
            self._daily_transferred = 0.0
            self._last_reset_date = date.today()

    def _credit(self, amount):
        if amount <= 0:
            raise InvalidAmountError("Deposit amount must be positive.")
        self._balance += amount

    def _debit(self, amount):
        if amount <= 0:
            raise InvalidAmountError("Amount must be positive.")
        self._balance -= amount

    def check_balance(self):
        self._ensure_active()
        return self._balance

    def deposit(self, amount):
        self._ensure_active()
        if amount <= 0:
            raise InvalidAmountError("Deposit amount must be positive.")
        transaction = DepositTransaction(self, amount)
        transaction.execute()
        self._transaction_history.append(transaction)
        return transaction

    @abstractmethod
    def calculate_withdrawal_limit(self):
        pass

    @abstractmethod
    def _min_balance_after_withdrawal(self, amount):
        pass

    def withdraw(self, amount, atm=None, charge_fee=True):
        self._ensure_active()
        self._reset_daily_limits_if_needed()

        if amount <= 0:
            raise InvalidAmountError("Withdrawal amount must be positive.")
        if amount < self.MIN_WITHDRAWAL:
            raise InvalidAmountError(f"Minimum withdrawal is Rs. {self.MIN_WITHDRAWAL}.")

        withdrawal_limit = self.calculate_withdrawal_limit()
        if amount > withdrawal_limit:
            raise InvalidAmountError(f"Amount exceeds per-transaction limit of Rs. {withdrawal_limit:,.0f}.")

        if self._daily_withdrawn + amount > self.DAILY_WITHDRAWAL_LIMIT:
            raise DailyLimitExceededError("Daily withdrawal limit exceeded (Max Rs. 100,000).")

        fee = self.WITHDRAWAL_FEE if charge_fee else 0
        total_deduction = amount + fee

        if not self._min_balance_after_withdrawal(total_deduction):
            raise InsufficientBalanceError("Insufficient balance for this withdrawal.")

        if atm is not None:
            atm.verify_can_dispense(amount)

        transaction = WithdrawalTransaction(self, -total_deduction)
        transaction.execute()
        self._transaction_history.append(transaction)

        if atm is not None:
            atm.dispense_cash(amount)

        self._daily_withdrawn += amount
        return transaction

    def transfer(self, target_account, amount, charge_fee=True):
        self._ensure_active()
        self._reset_daily_limits_if_needed()

        if not isinstance(target_account, Account):
            raise InvalidAccountError("Receiver account does not exist.")
        if target_account.account_number == self.account_number:
            raise InvalidAccountError("Sender and receiver cannot be the same account.")
        if amount <= 0:
            raise InvalidAmountError("Transfer amount must be positive.")

        target_account._ensure_active()
        fee = self.TRANSFER_FEE if charge_fee else 0
        total_deduction = amount + fee

        if not self._min_balance_after_withdrawal(total_deduction):
            raise InsufficientBalanceError("Insufficient balance for this transfer.")

        if self._daily_transferred + amount > self.DAILY_TRANSFER_LIMIT:
            raise DailyLimitExceededError("Daily transfer limit exceeded.")

        debit_transaction = TransferTransaction(self, -total_deduction, target_account, "DEBIT")
        debit_transaction.execute()
        self._transaction_history.append(debit_transaction)

        credit_transaction = TransferTransaction(target_account, amount, self, "CREDIT")
        credit_transaction.execute()
        target_account._transaction_history.append(credit_transaction)

        self._daily_transferred += amount
        return debit_transaction, credit_transaction

    def mini_statement(self, n=5):
        self._ensure_active()
        return list(reversed(self._transaction_history[-n:]))

    def __str__(self):
        return f"{self.__class__.__name__} #{self.account_number} | Balance: Rs. {self._balance:,.2f} | Status: {self._status}"


class SavingsAccount(Account):
    MIN_BALANCE = 5000
    WITHDRAWAL_LIMIT_PER_TXN = 50000

    def __init__(self, holder, pin, opening_balance=0.0):
        if opening_balance < self.MIN_BALANCE:
            raise InvalidAmountError("Savings Account requires minimum opening balance of Rs. 5,000.")
        super().__init__(holder, pin, opening_balance)

    def calculate_withdrawal_limit(self):
        return self.WITHDRAWAL_LIMIT_PER_TXN

    def _min_balance_after_withdrawal(self, amount):
        return self._balance - amount >= self.MIN_BALANCE


class CurrentAccount(Account):
    OVERDRAFT_LIMIT = 50000
    WITHDRAWAL_LIMIT_PER_TXN = 75000

    def calculate_withdrawal_limit(self):
        return self.WITHDRAWAL_LIMIT_PER_TXN

    def _min_balance_after_withdrawal(self, amount):
        return self._balance - amount >= -self.OVERDRAFT_LIMIT


# ============================================================
# 4. CARD, CUSTOMER, BANK, ATM
# ============================================================
class Card:
    MAX_PIN_ATTEMPTS = 3
    _card_counter = count(4000_0000_0000_0001)

    def __init__(self, account):
        self.card_number = str(next(Card._card_counter))
        self.account = account
        self._status = "ACTIVE"
        self._failed_attempts = 0

    @property
    def status(self):
        return self._status

    def _block(self):
        self._status = "BLOCKED"
        self.account.block_account()

    def unblock(self):
        self._status = "ACTIVE"
        self._failed_attempts = 0
        self.account.activate_account()

    def validate_pin(self, pin):
        # اگر کارڈ پہلے ہی بلاک ہے تو صحیح پن دینے پر بھی بلاک ہی شو کرے گا
        if self._status == "BLOCKED" or self.account.status == "BLOCKED":
            raise CardBlockedError("This card is temporarily blocked due to multiple incorrect PIN attempts.")
        
        if self.account._check_pin(pin):
            self._failed_attempts = 0
            return True

        self._failed_attempts += 1
        if self._failed_attempts >= self.MAX_PIN_ATTEMPTS:
            self._block()
            raise CardBlockedError("Card blocked temporarily after 3 incorrect PIN attempts.")

        remaining = self.MAX_PIN_ATTEMPTS - self._failed_attempts
        raise InvalidPINError(f"Incorrect PIN. {remaining} attempt(s) remaining.")

    def __str__(self):
        return f"Card {self.card_number} [{self._status}] -> Account {self.account.account_number}"


class Customer:
    _cust_counter = count(1)

    def __init__(self, name, contact):
        self.customer_id = f"CUST-{next(Customer._cust_counter):04d}"
        self.name = name
        self.contact = contact
        self.accounts = []
        self.cards = []

    def add_account(self, account):
        self.accounts.append(account)

    def add_card(self, card):
        self.cards.append(card)

    def __str__(self):
        return f"{self.customer_id} - {self.name}"


class Bank:
    def __init__(self, name):
        self.name = name
        self.customers = {}
        self.accounts = {}
        self.cards = {}

    def register_customer(self, name, contact):
        customer = Customer(name, contact)
        self.customers[customer.customer_id] = customer
        return customer

    def open_account(self, customer, account_type, pin, opening_balance=0.0):
        account_type = account_type.lower()
        if account_type == "savings":
            account = SavingsAccount(customer, pin, opening_balance)
        elif account_type == "current":
            account = CurrentAccount(customer, pin, opening_balance)
        else:
            raise ValueError("Account type must be 'savings' or 'current'.")

        customer.add_account(account)
        self.accounts[account.account_number] = account
        return account

    def issue_card(self, customer, account):
        if account not in customer.accounts:
            raise InvalidAccountError("Account does not belong to this customer.")
        card = Card(account)
        customer.add_card(card)
        self.cards[card.card_number] = card
        return card

    def find_account(self, account_number):
        account = self.accounts.get(account_number)
        if account is None:
            raise InvalidAccountError(f"Account {account_number} not found.")
        return account

    def find_card(self, card_number):
        card = self.cards.get(card_number)
        if card is None:
            raise InvalidAccountError(f"Card {card_number} not found.")
        return card

    def verify_pin_across_cards(self, pin):
        for card in self.cards.values():
            if card.status != "BLOCKED" and card.account.status != "BLOCKED" and card.account._check_pin(pin):
                return card
        return None


class ATM:
    def __init__(self, atm_id, bank, denominations=None):
        self.atm_id = atm_id
        self.bank = bank
        self.denominations = denominations or {500: 20, 1000: 30, 5000: 10}
        self.current_card = None
        self.current_account = None

    @property
    def total_cash(self):
        return sum(note * quantity for note, quantity in self.denominations.items())

    def _dispensable_combo(self, amount):
        remaining = amount
        plan = {}
        for note in sorted(self.denominations, reverse=True):
            available = self.denominations[note]
            use = min(available, remaining // note)
            if use:
                plan[note] = int(use)
                remaining -= (use * note)
        if remaining == 0:
            return plan
        return None

    def verify_can_dispense(self, amount):
        if amount > self.total_cash:
            raise InsufficientATMFundsError("ATM has insufficient cash. Please try another amount.")
        if self._dispensable_combo(amount) is None:
            raise DenominationError("Requested amount cannot be dispensed with available denominations.")

    def dispense_cash(self, amount):
        plan = self._dispensable_combo(amount)
        if plan is None:
            raise DenominationError("Cannot dispense the requested amount.")
        for note, quantity in plan.items():
            self.denominations[note] -= quantity
        return plan

    def login_with_pin(self, pin):
        card = self.bank.verify_pin_across_cards(pin)
        if card is not None:
            card.validate_pin(pin)
            self.current_card = card
            self.current_account = card.account
            return True
        
        for c in self.bank.cards.values():
            if c.account._check_pin(pin) and (c.status == "BLOCKED" or c.account.status == "BLOCKED"):
                raise CardBlockedError("This card is temporarily blocked due to multiple incorrect PIN attempts.")

        for c in self.bank.cards.values():
            if c.status != "BLOCKED" and c.account.status != "BLOCKED":
                try:
                    c.validate_pin(pin)
                except Exception as e:
                    raise e
                    
        raise InvalidPINError("Invalid PIN or Card Blocked.")

    def eject_card(self):
        self.current_card = None
        self.current_account = None


# ============================================================
# 5. HIGH-END GUI IMPLEMENTATION (CUSTOMTKINTER)
# ============================================================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class ATMApplication(ctk.CTk):
    def __init__(self, bank, atm):
        super().__init__()
        self.bank = bank
        self.atm = atm

        self.title("National Bank - Smart ATM System")
        self.geometry("1100x750")
        self.resizable(True, True)
        self.state("zoomed")

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (InsertCardView, PinLoginView, DashboardView, DepositView, WithdrawView, TransferView, ChangePinView, MiniStatementView):
            page_name = F.__name__
            frame = F(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.show_frame("InsertCardView")

    def show_frame(self, page_name, data=None):
        frame = self.frames[page_name]
        if hasattr(frame, "on_show") and data is not None:
            frame.on_show(data)
        elif hasattr(frame, "on_show"):
            frame.on_show()
        frame.tkraise()


class InsertCardView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_frame = ctk.CTkFrame(self, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_frame, text="🏛️ NATIONAL BANK OF PAKISTAN", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(0, 10))
        ctk.CTkLabel(center_frame, text="Welcome to Smart ATM System", font=ctk.CTkFont(size=16), text_color="gray").pack(pady=(0, 35))

        slot_box = ctk.CTkFrame(center_frame, width=500, height=180, corner_radius=20, fg_color=("#1e293b", "#0f172a"))
        slot_box.pack(pady=15)
        slot_box.pack_propagate(False)

        ctk.CTkLabel(slot_box, text="💳", font=ctk.CTkFont(size=40)).pack(pady=(20, 5))
        ctk.CTkLabel(slot_box, text="Please Insert Your Card to Continue", font=ctk.CTkFont(size=16, weight="bold"), text_color="#38bdf8").pack(pady=5)

        insert_btn = ctk.CTkButton(
            center_frame, text="Insert Card & Press Enter ➔", 
            font=ctk.CTkFont(size=16, weight="bold"), 
            width=320, height=52, fg_color="#2563eb", hover_color="#1d4ed8",
            command=self.proceed_to_pin
        )
        insert_btn.pack(pady=30)

        self.hint_label = ctk.CTkLabel(center_frame, text="", text_color="green", font=ctk.CTkFont(size=12, weight="bold"))
        self.hint_label.pack(pady=(5, 0))

    def on_show(self):
        if hasattr(self.controller, "demo_pin"):
            self.hint_label.configure(text=f"[Demo PIN]: {self.controller.demo_pin} (Test wrong 3 times to temporarily block card)")

    def proceed_to_pin(self):
        self.controller.show_frame("PinLoginView")


class PinLoginView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_frame = ctk.CTkFrame(self, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_frame, text="🏛️ NATIONAL BANK OF PAKISTAN", font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(0, 5))
        ctk.CTkLabel(center_frame, text="Please Enter Your 4-Digit PIN via Keypad", font=ctk.CTkFont(size=14), text_color="gray").pack(pady=(0, 15))

        self.pin_display = ctk.CTkEntry(center_frame, width=280, height=50, show="*", justify="center", font=ctk.CTkFont(size=22, weight="bold"), state="readonly")
        self.pin_display.pack(pady=10)
        self.entered_pin = ""

        keypad_frame = ctk.CTkFrame(center_frame, fg_color="transparent")
        keypad_frame.pack(pady=10)

        buttons = [
            ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
            ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
            ('C', 3, 0), ('0', 3, 1), ('OK', 3, 2)
        ]

        for (text, r, c) in buttons:
            btn = ctk.CTkButton(
                keypad_frame, text=text, width=75, height=48, 
                font=ctk.CTkFont(size=16, weight="bold"),
                command=lambda t=text: self.key_press(t)
            )
            btn.grid(row=r, column=c, padx=8, pady=6)

        back_btn = ctk.CTkButton(center_frame, text="← Eject Card / Go Back", fg_color="transparent", border_width=1, text_color=("black", "white"), width=200, height=35, command=lambda: self.controller.show_frame("InsertCardView"))
        back_btn.pack(pady=(15, 0))

    def on_show(self, data=None):
        self.entered_pin = ""
        self.update_display()

    def key_press(self, val):
        if val == 'C':
            self.entered_pin = ""
        elif val == 'OK':
            self.submit_pin()
            return
        else:
            if len(self.entered_pin) < 4:
                self.entered_pin += val
        self.update_display()

    def update_display(self):
        self.pin_display.configure(state="normal")
        self.pin_display.delete(0, 'end')
        self.pin_display.insert(0, self.entered_pin)
        self.pin_display.configure(state="readonly")

    def submit_pin(self):
        if len(self.entered_pin) != 4:
            messagebox.showerror("Error", "PIN must be exactly 4 digits.")
            return
        try:
            self.controller.atm.login_with_pin(self.entered_pin)
            self.controller.show_frame("DashboardView")
        except CardBlockedError as cbe:
            messagebox.showerror("Card Blocked", str(cbe))
            self.entered_pin = ""
            self.update_display()
            self.controller.show_frame("InsertCardView")
        except Exception as e:
            messagebox.showerror("Authentication Failed", str(e))
            self.entered_pin = ""
            self.update_display()


class DashboardView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        header = ctk.CTkFrame(self, fg_color="transparent", height=60)
        header.pack(fill="x", padx=40, pady=20)

        ctk.CTkLabel(header, text="====== ATM SYSTEM MENU ======", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        
        logout_btn = ctk.CTkButton(header, text="7. Exit / Eject Card", fg_color="#ef4444", hover_color="#dc2626", width=150, height=40, command=self.handle_logout)
        logout_btn.pack(side="right")

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.pack(expand=True)

        card_box = ctk.CTkFrame(center_content, width=860, height=170, corner_radius=20, fg_color=("#1e293b", "#0f172a"))
        card_box.pack(pady=10)
        card_box.pack_propagate(False)

        card_top = ctk.CTkFrame(card_box, fg_color="transparent")
        card_top.pack(fill="x", padx=25, pady=(15, 0))
        
        ctk.CTkLabel(card_top, text="NATIONAL BANK DEBIT", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(side="left")
        ctk.CTkLabel(card_top, text="CHIP ⬡", font=ctk.CTkFont(size=14, weight="bold"), text_color="#fbbf24").pack(side="right")

        card_mid = ctk.CTkFrame(card_box, fg_color="transparent")
        card_mid.pack(fill="x", padx=25, pady=(8, 0))
        
        self.card_num_label = ctk.CTkLabel(card_mid, text="•••• •••• •••• 0000", font=ctk.CTkFont(size=20, weight="bold"), text_color="#ffffff")
        self.card_num_label.pack(side="left")
        
        self.acc_type_label = ctk.CTkLabel(card_mid, text="SAVINGS", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1", fg_color="#334155", corner_radius=6)
        self.acc_type_label.pack(side="right", padx=5)

        card_bot = ctk.CTkFrame(card_box, fg_color="transparent")
        card_bot.pack(fill="x", padx=25, pady=(12, 0))

        holder_frame = ctk.CTkFrame(card_bot, fg_color="transparent")
        holder_frame.pack(side="left")
        ctk.CTkLabel(holder_frame, text="CARDHOLDER", font=ctk.CTkFont(size=9), text_color="#94a3b8").pack(anchor="w")
        self.holder_label = ctk.CTkLabel(holder_frame, text="EMAN FATIMA", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        self.holder_label.pack(anchor="w")

        balance_frame = ctk.CTkFrame(card_bot, fg_color="transparent")
        balance_frame.pack(side="right")
        ctk.CTkLabel(balance_frame, text="AVAILABLE BALANCE", font=ctk.CTkFont(size=9), text_color="#94a3b8").pack(anchor="e")
        self.balance_label = ctk.CTkLabel(balance_frame, text="Rs. 0.00", font=ctk.CTkFont(size=18, weight="bold"), text_color="#38bdf8")
        self.balance_label.pack(anchor="e")

        grid_frame = ctk.CTkFrame(center_content, fg_color="transparent")
        grid_frame.pack(pady=20)

        w, h = 380, 52
        ctk.CTkButton(grid_frame, text="1. Check Balance", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=self.show_balance).grid(row=0, column=0, padx=20, pady=12)
        ctk.CTkButton(grid_frame, text="2. Deposit Money", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=lambda: self.controller.show_frame("DepositView")).grid(row=0, column=1, padx=20, pady=12)
        ctk.CTkButton(grid_frame, text="3. Withdraw Money", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=lambda: self.controller.show_frame("WithdrawView")).grid(row=1, column=0, padx=20, pady=12)
        ctk.CTkButton(grid_frame, text="4. Transfer Money", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=lambda: self.controller.show_frame("TransferView")).grid(row=1, column=1, padx=20, pady=12)
        ctk.CTkButton(grid_frame, text="5. Change PIN", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=lambda: self.controller.show_frame("ChangePinView")).grid(row=2, column=0, padx=20, pady=12)
        ctk.CTkButton(grid_frame, text="6. Mini Statement (Last 5)", font=ctk.CTkFont(size=15, weight="bold"), width=w, height=h, command=lambda: self.controller.show_frame("MiniStatementView")).grid(row=2, column=1, padx=20, pady=12)

    def on_show(self):
        acc = self.controller.atm.current_account
        card = self.controller.atm.current_card
        if acc and card:
            self.holder_label.configure(text=acc.holder.name.upper())
            self.acc_type_label.configure(text=acc.__class__.__name__.replace("Account", "").upper())
            
            c_num = card.card_number
            formatted_card = f"{c_num[:4]} •••• •••• {c_num[-4:]}"
            self.card_num_label.configure(text=formatted_card)
            
            try:
                bal = acc.check_balance()
                self.balance_label.configure(text=f"Rs. {bal:,.2f}")
            except Exception:
                self.balance_label.configure(text="Rs. 0.00")

    def show_balance(self):
        acc = self.controller.atm.current_account
        bal = acc.check_balance()
        messagebox.showinfo("Account Balance", f"Account #{acc.account_number}\nCurrent Balance: Rs. {bal:,.2f}")

    def handle_logout(self):
        self.controller.atm.eject_card()
        self.controller.show_frame("InsertCardView")


class DepositView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_content, text="2. Deposit Money", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 20))
        self.amt_entry = ctk.CTkEntry(center_content, placeholder_text="Enter amount (e.g. 20000)", width=340, height=48, font=ctk.CTkFont(size=14))
        self.amt_entry.pack(pady=10)

        ctk.CTkButton(center_content, text="Confirm Deposit", width=240, height=48, font=ctk.CTkFont(size=15, weight="bold"), command=self.process_deposit).pack(pady=15)
        ctk.CTkButton(center_content, text="← Back to Menu", fg_color="transparent", border_width=1, text_color=("black", "white"), width=240, height=40, command=lambda: self.controller.show_frame("DashboardView")).pack(pady=5)

    def process_deposit(self):
        try:
            amt = float(self.amt_entry.get())
            txn = self.controller.atm.current_account.deposit(amt)
            bal = self.controller.atm.current_account.check_balance()
            
            msg = f"Deposit\n--------------------------------\nAmount: Rs. {amt:,.2f}\nTransaction ID: {txn.transaction_id}\nNew Balance: Rs. {bal:,.2f}"
            messagebox.showinfo("Deposit Successful", msg)
            self.amt_entry.delete(0, 'end')
            self.controller.show_frame("DashboardView")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid numeric amount.")
        except Exception as e:
            messagebox.showerror("Error", str(e))


class WithdrawView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_content, text="3. Withdraw Money", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 10))
        ctk.CTkLabel(center_content, text="Fee: Rs. 50 | Min: Rs. 500 | Max/Txn: Rs. 50,000", font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(0, 20))
        
        self.amt_entry = ctk.CTkEntry(center_content, placeholder_text="Enter amount to withdraw", width=340, height=48, font=ctk.CTkFont(size=14))
        self.amt_entry.pack(pady=10)

        ctk.CTkButton(center_content, text="Confirm Withdrawal", width=240, height=48, font=ctk.CTkFont(size=15, weight="bold"), command=self.process_withdrawal).pack(pady=15)
        ctk.CTkButton(center_content, text="← Back to Menu", fg_color="transparent", border_width=1, text_color=("black", "white"), width=240, height=40, command=lambda: self.controller.show_frame("DashboardView")).pack(pady=5)

    def process_withdrawal(self):
        try:
            amt = float(self.amt_entry.get())
            self.controller.atm.current_account.withdraw(amt, atm=self.controller.atm)
            bal = self.controller.atm.current_account.check_balance()
            messagebox.showinfo("Success", f"Please collect your cash: Rs. {amt:,.2f}\n(Fee applied: Rs. 50)\nNew Balance: Rs. {bal:,.2f}")
            self.amt_entry.delete(0, 'end')
            self.controller.show_frame("DashboardView")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid amount.")
        except Exception as e:
            messagebox.showerror("Error", str(e))


class TransferView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_content, text="4. Transfer Money", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 10))
        ctk.CTkLabel(center_content, text="Transfer Fee: Rs. 100 | Target Account for Test: 10000002", font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(0, 15))

        self.target_entry = ctk.CTkEntry(center_content, placeholder_text="Target Account Number (10000002)", width=340, height=48, font=ctk.CTkFont(size=14))
        self.target_entry.pack(pady=10)
        self.amt_entry = ctk.CTkEntry(center_content, placeholder_text="Transfer Amount", width=340, height=48, font=ctk.CTkFont(size=14))
        self.amt_entry.pack(pady=10)

        ctk.CTkButton(center_content, text="Transfer Now", width=240, height=48, font=ctk.CTkFont(size=15, weight="bold"), command=self.process_transfer).pack(pady=15)
        ctk.CTkButton(center_content, text="← Back to Menu", fg_color="transparent", border_width=1, text_color=("black", "white"), width=240, height=40, command=lambda: self.controller.show_frame("DashboardView")).pack(pady=5)

    def process_transfer(self):
        try:
            target_acc_num = self.target_entry.get().strip()
            amt = float(self.amt_entry.get())
            target_acc = self.controller.bank.find_account(target_acc_num)
            
            self.controller.atm.current_account.transfer(target_acc, amt)
            bal = self.controller.atm.current_account.check_balance()
            
            messagebox.showinfo("Transfer Successful", f"Successfully transferred Rs. {amt:,.2f} to Account #{target_acc_num}\nNew Balance: Rs. {bal:,.2f}")
            self.target_entry.delete(0, 'end')
            self.amt_entry.delete(0, 'end')
            self.controller.show_frame("DashboardView")
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numeric details.")
        except Exception as e:
            messagebox.showerror("Error", str(e))


class ChangePinView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_content, text="5. Change PIN", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(0, 20))
        
        self.old_pin_entry = ctk.CTkEntry(center_content, placeholder_text="Current 4-Digit PIN", show="*", width=340, height=48, font=ctk.CTkFont(size=14))
        self.old_pin_entry.pack(pady=10)
        
        self.new_pin_entry = ctk.CTkEntry(center_content, placeholder_text="New 4-Digit PIN", show="*", width=340, height=48, font=ctk.CTkFont(size=14))
        self.new_pin_entry.pack(pady=10)

        ctk.CTkButton(center_content, text="Update PIN", width=240, height=48, font=ctk.CTkFont(size=15, weight="bold"), command=self.process_change_pin).pack(pady=15)
        ctk.CTkButton(center_content, text="← Back to Menu", fg_color="transparent", border_width=1, text_color=("black", "white"), width=240, height=40, command=lambda: self.controller.show_frame("DashboardView")).pack(pady=5)

    def process_change_pin(self):
        try:
            old_p = self.old_pin_entry.get().strip()
            new_p = self.new_pin_entry.get().strip()
            
            self.controller.atm.current_account.change_pin(old_p, new_p)
            messagebox.showinfo("Success", "PIN changed successfully!")
            self.old_pin_entry.delete(0, 'end')
            self.new_pin_entry.delete(0, 'end')
            self.controller.show_frame("DashboardView")
        except Exception as e:
            messagebox.showerror("Error", str(e))


class MiniStatementView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        center_content = ctk.CTkFrame(self, fg_color="transparent")
        center_content.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center_content, text="6. Mini Statement (Last 5 Transactions)", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 15))
        
        self.textbox = ctk.CTkTextbox(center_content, width=860, height=350, font=ctk.CTkFont(family="Courier", size=13))
        self.textbox.pack(pady=10)
        self.textbox.configure(state="disabled")

        ctk.CTkButton(center_content, text="← Back to Menu", width=240, height=42, command=lambda: self.controller.show_frame("DashboardView")).pack(pady=15)

    def on_show(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("0.0", "end")
        try:
            acc = self.controller.atm.current_account
            transactions = acc.mini_statement(5)
            
            header_text = f"========== MINI STATEMENT ==========\nAccount: {acc.account_number}\nDate / Time            Type         Amount      Status\n--------------------------------------------------------------------\n"
            self.textbox.insert("end", header_text)
            
            if not transactions:
                self.textbox.insert("end", "No recent transactions found.\n")
            else:
                for txn in transactions:
                    self.textbox.insert("end", str(txn) + "\n")
            
            bal_text = f"\n--------------------------------------------------------------------\nCurrent Balance: Rs. {acc.check_balance():,.2f}"
            self.textbox.insert("end", bal_text)
        except Exception as e:
            self.textbox.insert("end", f"Error loading statement: {e}")
            
        self.textbox.configure(state="disabled")


# ============================================================
# 6. MAIN EXECUTION
# ============================================================
if __name__ == "__main__":
    my_bank = Bank("National Bank of Pakistan")
    my_atm = ATM("ATM-001", my_bank, denominations={500: 20, 1000: 30, 5000: 10})

    cust1 = my_bank.register_customer("Eman Fatima", "03001234567")
    acc1 = my_bank.open_account(cust1, "savings", "1234", opening_balance=50000.0)
    card1 = my_bank.issue_card(cust1, acc1)

    cust2 = my_bank.register_customer("Ali Khan", "03007654321")
    acc2 = my_bank.open_account(cust2, "current", "5678", opening_balance=25000.0)
    card2 = my_bank.issue_card(cust2, acc2)

    app = ATMApplication(my_bank, my_atm)
    app.demo_pin = "1234"
    app.mainloop()