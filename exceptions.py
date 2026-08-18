class ATMError(Exception):
    pass


class InvalidPINError(ATMError):
    pass


class CardBlockedError(ATMError):
    pass


class InsufficientBalanceError(ATMError):
    pass


class InsufficientATMFundsError(ATMError):
    pass


class InvalidAmountError(ATMError):
    pass


class AccountInactiveError(ATMError):
    pass


class DailyLimitExceededError(ATMError):
    pass


class InvalidAccountError(ATMError):
    pass


class DenominationError(ATMError):
    pass