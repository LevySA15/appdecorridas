from enum import Enum


class PaymentMethod(str, Enum):
    PIX = "pix"
    CASH = "cash"
