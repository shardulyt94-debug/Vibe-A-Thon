from dataclasses import dataclass, field
from enum import Enum


class ShelterStatus(str, Enum):
    OPEN = "OPEN"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"


class PortionStatus(str, Enum):
    CLAIMED = "CLAIMED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class Donor:
    id: str
    name: str
    x: float
    y: float


@dataclass
class Batch:
    id: str
    donor_id: str
    item_type: str
    total_qty: int
    safe_until: float
    created_at: float


@dataclass
class Shelter:
    id: str
    name: str
    x: float
    y: float
    has_water: bool
    has_fuel: bool
    status: ShelterStatus = ShelterStatus.OPEN


@dataclass
class Need:
    id: str
    shelter_id: str
    item_type: str
    qty: int
    need_by: float


@dataclass
class Rider:
    id: str
    name: str
    x: float
    y: float
    capacity: int
    frozen: bool = False
    last_ping: float = 0.0


@dataclass
class Portion:
    id: str
    batch_id: str
    need_id: str
    shelter_id: str
    rider_id: str
    qty: int
    status: PortionStatus
    claim_expires_at: float
    traffic_msgs: int = 0
    warned: bool = False
    checkpoint_time: float = 0.0
    checkpoint_dist: float = 0.0


@dataclass
class Event:
    time: float
    text: str
