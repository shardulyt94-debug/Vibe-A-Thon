from dataclasses import dataclass, field

from .clock import FakeClock
from .models import Batch, Donor, Event, Need, Portion, Rider, Shelter


@dataclass
class Store:
    clock: FakeClock = field(default_factory=FakeClock)
    donors: dict[str, Donor] = field(default_factory=dict)
    batches: dict[str, Batch] = field(default_factory=dict)
    shelters: dict[str, Shelter] = field(default_factory=dict)
    needs: dict[str, Need] = field(default_factory=dict)
    riders: dict[str, Rider] = field(default_factory=dict)
    portions: dict[str, Portion] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
