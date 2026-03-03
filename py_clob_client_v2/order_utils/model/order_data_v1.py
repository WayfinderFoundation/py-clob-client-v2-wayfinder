from dataclasses import dataclass
from typing import Optional

from .side import Side
from .signature_type_v1 import SignatureTypeV1


@dataclass
class OrderDataV1:
    """Input data for building a V1 order."""

    maker: str
    taker: str
    tokenId: str
    makerAmount: str
    takerAmount: str
    side: Side
    feeRateBps: str = "0"
    nonce: str = "0"
    signer: Optional[str] = None
    expiration: Optional[str] = None
    signatureType: Optional[SignatureTypeV1] = None


@dataclass
class OrderV1:
    """An unsigned V1 order ready for EIP712 signing."""

    salt: str
    maker: str
    signer: str
    taker: str
    tokenId: str
    makerAmount: str
    takerAmount: str
    expiration: str
    nonce: str
    feeRateBps: str
    side: Side
    signatureType: SignatureTypeV1


@dataclass
class SignedOrderV1(OrderV1):
    """A signed V1 order including the EIP712 signature."""

    signature: str = ""
