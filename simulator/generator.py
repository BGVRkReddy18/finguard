"""Synthetic card-transaction generator, shared by the live stream and the offline history builder.

Normal behaviour: each customer shops mostly in their home city, in their usual categories,
with amounts drawn from a log-normal distribution around a personal typical spend, and
shops much less at night.

Injected fraud patterns (labelled, so detection quality can be measured):
  * account_takeover  — large amount in a far-away city
  * impossible_travel — a home-city purchase, then minutes later one in a distant city
  * card_testing      — a burst of small online purchases seconds apart

Events are produced as ``(delay_seconds, txn)`` pairs. The caller decides what "time" means:
the live simulator uses the wall clock, the history builder uses a simulated clock. Both
therefore produce identically distributed data — no train/serve skew.
"""
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

CITIES = {
    "Hyderabad": (17.385, 78.4867), "Bengaluru": (12.9716, 77.5946), "Mumbai": (19.076, 72.8777),
    "Delhi": (28.6139, 77.209), "Chennai": (13.0827, 80.2707), "Kolkata": (22.5726, 88.3639),
    "Pune": (18.5204, 73.8567), "Ahmedabad": (23.0225, 72.5714), "Jaipur": (26.9124, 75.7873),
    "Visakhapatnam": (17.6868, 83.2185), "Guwahati": (26.1445, 91.7362), "Kochi": (9.9312, 76.2673),
}
MERCHANTS = {
    "grocery": ["BigBasket", "DMart", "Reliance Fresh", "More Supermarket"],
    "restaurants": ["Swiggy", "Zomato", "Paradise Biryani", "Haldiram's"],
    "fuel": ["Indian Oil", "HP Petrol", "Bharat Petroleum"],
    "electronics": ["Croma", "Reliance Digital", "Vijay Sales"],
    "fashion": ["Myntra", "Westside", "Lifestyle"],
    "travel": ["IRCTC", "MakeMyTrip", "IndiGo"],
    "jewellery": ["Tanishq", "Malabar Gold"],
    "gift_cards": ["Amazon Gift Card", "Flipkart Gift Card", "Google Play"],
    "utilities": ["Airtel", "Jio", "TSSPDCL"],
}
EVERYDAY = ["grocery", "restaurants", "fuel", "fashion", "utilities"]
OCCASIONAL = ["electronics", "travel", "jewellery", "gift_cards"]
FIRST = ["Aarav", "Diya", "Rohan", "Ananya", "Vikram", "Sneha", "Arjun", "Kavya", "Rahul", "Priya", "Karthik", "Meera"]
LAST = ["Reddy", "Sharma", "Iyer", "Patel", "Gupta", "Rao", "Nair", "Singh", "Das", "Kumar"]

NIGHT_LEGIT_SKIP = 0.75   # legit customers mostly sleep 00:00–05:00 IST
NIGHT_FRAUD_BOOST = 2.0   # fraudsters don't


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    home_city: str
    typical_amount: float
    favourite_categories: tuple[str, ...]
    travels: bool  # some genuine customers shop in other cities too — makes the problem realistic


def make_customers(n: int, seed: int) -> list[Customer]:
    """Deterministic for a given seed, so the live stream and the history share the same customers."""
    rng = random.Random(seed)
    return [
        Customer(
            customer_id=f"C{i:05d}",
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            home_city=rng.choice(list(CITIES)),
            typical_amount=round(rng.lognormvariate(7.0, 0.6), 2),  # median ≈ ₹1,100
            favourite_categories=tuple(rng.sample(EVERYDAY, 3)),
            travels=rng.random() < 0.15,
        )
        for i in range(n)
    ]


def is_night(ts: datetime) -> bool:
    return ts.astimezone(IST).hour < 5


def _txn(c: Customer, rng: random.Random, *, city=None, amount=None, category=None, channel=None,
         label=False, pattern="") -> dict:
    city = city or c.home_city
    category = category or rng.choice(c.favourite_categories)
    base = CITIES[city]
    return {
        "txn_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "customer_id": c.customer_id,
        "customer_name": c.name,
        "home_city": c.home_city,
        "amount": round(amount if amount is not None else max(20.0, rng.lognormvariate(0, 0.5) * c.typical_amount), 2),
        "currency": "INR",
        "merchant": rng.choice(MERCHANTS[category]),
        "merchant_category": category,
        "city": city,
        "lat": round(base[0] + rng.uniform(-0.05, 0.05), 5),
        "lon": round(base[1] + rng.uniform(-0.05, 0.05), 5),
        "channel": channel or rng.choices(["POS", "ONLINE", "ATM"], weights=[60, 32, 8])[0],
        # Ground truth — the scoring service ignores these fields
        "label_is_fraud": label,
        "fraud_pattern": pattern,
    }


def legit_events(c: Customer, rng: random.Random) -> list[tuple[float, dict]]:
    """Genuine behaviour deliberately overlaps with fraud signals (hard negatives), as in real data."""
    roll = rng.random()
    if roll < 0.06:  # occasional big-ticket purchase: new phone, flight, gold
        return [(0.0, _txn(c, rng, category=rng.choice(OCCASIONAL), amount=c.typical_amount * rng.uniform(2, 10)))]
    if roll < 0.09:  # genuine small online gift-card / voucher purchase
        return [(0.0, _txn(c, rng, category="gift_cards", channel="ONLINE", amount=rng.uniform(100, 2000)))]
    if roll < (0.19 if c.travels else 0.11):  # genuine travel, sometimes spending more than usual
        return [(0.0, _txn(c, rng, city=rng.choice([x for x in CITIES if x != c.home_city]),
                           amount=c.typical_amount * rng.uniform(0.5, 4)))]
    if roll < 0.22:  # several genuine purchases in a row (shopping trip, food court)
        return [(i * rng.uniform(30, 240), _txn(c, rng)) for i in range(rng.randint(2, 5))]
    return [(0.0, _txn(c, rng))]


FRAUD_PATTERNS = ["account_takeover", "impossible_travel", "card_testing", "card_not_present"]


def fraud_events(c: Customer, rng: random.Random) -> list[tuple[float, dict]]:
    pattern = rng.choice(FRAUD_PATTERNS)
    far_city = rng.choice([x for x in CITIES if x != c.home_city])

    if pattern == "account_takeover":
        # Remote: fraudster in another city. Online: stolen credentials used from the home city.
        remote = rng.random() < 0.6
        return [(0.0, _txn(c, rng, city=far_city if remote else None, channel=None if remote else "ONLINE",
                           amount=c.typical_amount * rng.uniform(2, 15),
                           category=rng.choice(["electronics", "jewellery", "travel", "fashion"]),
                           label=True, pattern=pattern))]
    if pattern == "impossible_travel":
        return [
            (0.0, _txn(c, rng)),  # genuine home-city purchase
            (rng.uniform(5, 90) * 60, _txn(c, rng, city=far_city, amount=c.typical_amount * rng.uniform(0.8, 6),
                                           label=True, pattern=pattern)),
        ]
    if pattern == "card_testing":
        delay, events = 0.0, []
        for _ in range(rng.randint(3, 8)):
            events.append((delay, _txn(c, rng, amount=rng.uniform(10, 500), channel="ONLINE",
                                       category=rng.choice(["gift_cards", "restaurants", "fashion", "utilities"]),
                                       label=True, pattern=pattern)))
            delay += rng.uniform(5, 180)
        return events
    # card_not_present: stolen card details used online, mimicking normal spend — intentionally hard to catch
    return [(0.0, _txn(c, rng, channel="ONLINE", amount=c.typical_amount * rng.uniform(0.8, 3),
                       label=True, pattern=pattern))]


def next_events(customers: list[Customer], rng: random.Random, now: datetime,
                fraud_rate: float) -> list[tuple[float, dict]]:
    """Draw the events triggered at time ``now`` (possibly none, at night)."""
    customer = rng.choice(customers)
    night = is_night(now)
    if rng.random() < fraud_rate * (NIGHT_FRAUD_BOOST if night else 1.0):
        return fraud_events(customer, rng)
    if night and rng.random() < NIGHT_LEGIT_SKIP:
        return []
    return legit_events(customer, rng)
