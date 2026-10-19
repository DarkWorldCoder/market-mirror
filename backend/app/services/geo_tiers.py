"""Where people live: metros, second-tier cities, small towns and villages per country.

A market is not only its two biggest cities. When a segment names a few metros and asks for many people, the
planner spreads them over settlement types the way buyers are actually spread: some in the named metros,
some in second-tier cities, some in small towns and some in rural areas. Each person carries a `settlement`
label (metro | city | town | rural) that the persona prompt uses (data plan, prices, distances, habits).

The lists are illustrative examples of real places, not a sampling frame; give your own `cities` and
`geo_spread: "cities"` to keep people in exactly those places. Shares are defaults, not census figures; pass
`settlement_mix` per segment to override.
"""

import random
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_MIX = {"metro": 0.45, "city": 0.30, "town": 0.15, "rural": 0.10}

# country -> {"metro": [...], "city": [...], "town": [...], "rural": [...]}  (rural = village/area near a town)
PLACES: Dict[str, Dict[str, List[str]]] = {
    "india": {"metro": ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad"],
              "city": ["Jaipur", "Lucknow", "Indore", "Nagpur", "Coimbatore", "Kochi", "Bhopal", "Surat", "Chandigarh", "Visakhapatnam", "Patna", "Guwahati"],
              "town": ["Nashik", "Mysuru", "Udaipur", "Dehradun", "Siliguri", "Hubballi", "Thrissur", "Ajmer"],
              "rural": ["a village near Nashik", "a village in Bihar's Gaya district", "a village near Coimbatore", "a village in Uttar Pradesh near Varanasi"]},
    "philippines": {"metro": ["Quezon City", "Manila", "Makati", "Pasig", "Taguig", "Cebu City", "Davao City"],
                    "city": ["Iloilo City", "Bacolod", "Cagayan de Oro", "Baguio", "Zamboanga City", "General Santos", "Angeles City"],
                    "town": ["Tagbilaran", "Dumaguete", "Legazpi", "Puerto Princesa", "Vigan", "Tuguegarao"],
                    "rural": ["a barangay in Nueva Ecija", "a fishing barangay in Leyte", "a barangay in Iloilo province", "a barangay in Bukidnon"]},
    "kenya": {"metro": ["Nairobi", "Mombasa"],
              "city": ["Kisumu", "Nakuru", "Eldoret", "Thika"],
              "town": ["Nyeri", "Machakos", "Meru", "Kitale", "Malindi", "Kakamega"],
              "rural": ["a village in Kiambu County", "a village near Kisii", "a village in Machakos County", "a village near Kitui"]},
    "nigeria": {"metro": ["Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano"],
                "city": ["Enugu", "Benin City", "Kaduna", "Abeokuta", "Jos", "Ilorin", "Owerri"],
                "town": ["Osogbo", "Ado-Ekiti", "Calabar", "Uyo", "Akure", "Makurdi"],
                "rural": ["a village in Ogun State", "a village near Enugu", "a village in Kano State", "a village in Oyo State"]},
    "indonesia": {"metro": ["Jakarta", "Surabaya", "Bandung", "Medan", "Bekasi"],
                  "city": ["Semarang", "Makassar", "Palembang", "Yogyakarta", "Denpasar", "Malang", "Balikpapan"],
                  "town": ["Bogor", "Solo", "Cirebon", "Padang", "Manado", "Pontianak"],
                  "rural": ["a desa in Central Java", "a desa in East Java", "a desa in West Sumatra", "a desa in South Sulawesi"]},
    "pakistan": {"metro": ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad"],
                 "city": ["Multan", "Peshawar", "Hyderabad (Sindh)", "Gujranwala", "Quetta", "Sialkot"],
                 "town": ["Bahawalpur", "Sargodha", "Sukkur", "Abbottabad", "Mardan"],
                 "rural": ["a village in Punjab near Okara", "a village in Sindh near Larkana", "a village near Swat"]},
    "bangladesh": {"metro": ["Dhaka", "Chattogram"], "city": ["Khulna", "Rajshahi", "Sylhet", "Gazipur", "Narayanganj"],
                   "town": ["Cumilla", "Bogura", "Jessore", "Mymensingh", "Rangpur"], "rural": ["a village in Barishal division", "a village near Sylhet", "a village in Rajshahi division"]},
    "nepal": {"metro": ["Kathmandu", "Lalitpur"], "city": ["Pokhara", "Biratnagar", "Bharatpur", "Birgunj"],
              "town": ["Butwal", "Dharan", "Hetauda", "Janakpur", "Nepalgunj"], "rural": ["a village in Gorkha", "a village in Kailali", "a village near Ilam"]},
    "vietnam": {"metro": ["Ho Chi Minh City", "Hanoi"], "city": ["Da Nang", "Hai Phong", "Can Tho", "Bien Hoa"],
                "town": ["Hue", "Nha Trang", "Vung Tau", "Buon Ma Thuot", "Quy Nhon"], "rural": ["a village in the Mekong Delta", "a village in Nghe An", "a village near Thai Nguyen"]},
    "thailand": {"metro": ["Bangkok", "Nonthaburi"], "city": ["Chiang Mai", "Khon Kaen", "Nakhon Ratchasima", "Hat Yai", "Udon Thani"],
                 "town": ["Phitsanulok", "Surat Thani", "Ubon Ratchathani", "Rayong"], "rural": ["a village in Isan near Roi Et", "a village in Chiang Rai province", "a village near Sukhothai"]},
    "malaysia": {"metro": ["Kuala Lumpur", "Petaling Jaya", "Johor Bahru"], "city": ["George Town", "Ipoh", "Kuching", "Kota Kinabalu", "Shah Alam"],
                 "town": ["Melaka", "Kuantan", "Seremban", "Alor Setar"], "rural": ["a kampung in Kelantan", "a kampung in Sabah", "a kampung near Terengganu"]},
    "sri lanka": {"metro": ["Colombo"], "city": ["Kandy", "Galle", "Negombo", "Jaffna"], "town": ["Kurunegala", "Matara", "Anuradhapura", "Batticaloa"],
                  "rural": ["a village near Nuwara Eliya", "a village in the North Central Province"]},
    "ghana": {"metro": ["Accra", "Kumasi"], "city": ["Tamale", "Takoradi", "Tema"], "town": ["Cape Coast", "Ho", "Koforidua", "Sunyani"],
              "rural": ["a village in the Volta Region", "a village near Tamale"]},
    "south africa": {"metro": ["Johannesburg", "Cape Town", "Durban", "Pretoria"], "city": ["Port Elizabeth (Gqeberha)", "Bloemfontein", "East London", "Pietermaritzburg"],
                     "town": ["Polokwane", "Nelspruit (Mbombela)", "Kimberley", "Rustenburg"], "rural": ["a village in the Eastern Cape", "a village in Limpopo"]},
    "egypt": {"metro": ["Cairo", "Giza", "Alexandria"], "city": ["Mansoura", "Tanta", "Port Said", "Asyut"], "town": ["Luxor", "Aswan", "Ismailia", "Damietta"],
              "rural": ["a village in the Nile Delta near Zagazig", "a village in Upper Egypt near Sohag"]},
    "turkey": {"metro": ["Istanbul", "Ankara", "Izmir"], "city": ["Bursa", "Antalya", "Adana", "Konya", "Gaziantep"], "town": ["Eskisehir", "Trabzon", "Samsun", "Denizli"],
               "rural": ["a village near Kayseri", "a village on the Black Sea coast"]},
    "brazil": {"metro": ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Brasília"], "city": ["Salvador", "Fortaleza", "Curitiba", "Recife", "Porto Alegre", "Manaus"],
               "town": ["Campina Grande", "Juiz de Fora", "Londrina", "Feira de Santana"], "rural": ["a small town in the interior of Minas Gerais", "a rural area in Bahia"]},
    "mexico": {"metro": ["Mexico City", "Guadalajara", "Monterrey"], "city": ["Puebla", "Tijuana", "León", "Querétaro", "Mérida"], "town": ["Oaxaca", "Morelia", "Xalapa", "Durango"],
               "rural": ["a pueblo in Chiapas", "a pueblo in Michoacán"]},
    "united states": {"metro": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Atlanta"], "city": ["Columbus", "Charlotte", "Denver", "Nashville", "Kansas City", "Sacramento"],
                      "town": ["Boise", "Chattanooga", "Lansing", "Fayetteville", "Billings"], "rural": ["rural Iowa", "a small town in West Virginia", "rural Georgia"]},
    "united kingdom": {"metro": ["London", "Manchester", "Birmingham"], "city": ["Leeds", "Glasgow", "Bristol", "Liverpool", "Newcastle"], "town": ["Norwich", "Exeter", "Inverness", "Lincoln"],
                       "rural": ["a village in Cornwall", "a village in the Yorkshire Dales"]},
    "germany": {"metro": ["Berlin", "Hamburg", "Munich", "Cologne"], "city": ["Frankfurt", "Stuttgart", "Leipzig", "Dresden", "Hanover"], "town": ["Freiburg", "Rostock", "Kassel", "Würzburg"],
                "rural": ["a village in Bavaria", "a village in Brandenburg"]},
    "france": {"metro": ["Paris", "Lyon", "Marseille"], "city": ["Toulouse", "Lille", "Bordeaux", "Nantes", "Strasbourg"], "town": ["Rennes", "Dijon", "Annecy", "Perpignan"],
               "rural": ["a village in Auvergne", "a village in Brittany"]},
    "canada": {"metro": ["Toronto", "Montreal", "Vancouver"], "city": ["Calgary", "Ottawa", "Edmonton", "Winnipeg", "Quebec City"], "town": ["Kelowna", "Moncton", "Saskatoon", "Kingston"],
               "rural": ["rural Saskatchewan", "a small town in Nova Scotia"]},
    "australia": {"metro": ["Sydney", "Melbourne", "Brisbane"], "city": ["Perth", "Adelaide", "Gold Coast", "Canberra"], "town": ["Newcastle (NSW)", "Townsville", "Ballarat", "Cairns"],
                  "rural": ["a farming town in regional Victoria", "outback Queensland"]},
    "japan": {"metro": ["Tokyo", "Osaka", "Yokohama", "Nagoya"], "city": ["Fukuoka", "Sapporo", "Kobe", "Kyoto", "Hiroshima"], "town": ["Kanazawa", "Matsuyama", "Kagoshima", "Aomori"],
              "rural": ["a village in Nagano", "a village in Tohoku"]},
}
ALIASES = {"usa": "united states", "us": "united states", "u.s.": "united states", "america": "united states", "uk": "united kingdom",
           "britain": "united kingdom", "england": "united kingdom", "viet nam": "vietnam", "türkiye": "turkey", "ph": "philippines", "in": "india"}


def country_key(country: str) -> str:
    c = (country or "").strip().lower()
    return ALIASES.get(c, c)


def known(country: str) -> bool:
    return country_key(country) in PLACES


def spread(country: str, given: Sequence[str], n: int, rng: random.Random, mode: str = "auto",
           mix: Optional[Dict[str, float]] = None) -> List[Tuple[str, str]]:
    """n (place, settlement) pairs. mode: 'cities' keeps people in the given cities (settlement 'metro' if listed
    as a metro, else 'city'); 'national' spreads them by `mix`; 'auto' = national when the country is known and
    n >= 12, else cities."""
    table = PLACES.get(country_key(country))
    given = [g for g in given if g]
    if mode == "auto":
        mode = "national" if table and n >= 12 else "cities"
    if mode != "national" or not table:
        pool = given or [""]
        offset = rng.randrange(len(pool))
        metros = {m.lower() for m in (table or {}).get("metro", [])}
        return [(pool[(i + offset) % len(pool)], "metro" if pool[(i + offset) % len(pool)].lower() in metros else ("city" if pool[0] else ""))
                for i in range(n)]
    shares = dict(mix or DEFAULT_MIX)
    tot = sum(max(0.0, v) for v in shares.values()) or 1.0
    counts = {k: int(round(n * max(0.0, shares.get(k, 0)) / tot)) for k in ("metro", "city", "town", "rural")}
    while sum(counts.values()) > n:
        k = max(counts, key=counts.get)
        counts[k] -= 1
    while sum(counts.values()) < n:
        counts["metro"] += 1
    out: List[Tuple[str, str]] = []
    metros = list(given) + [m for m in table["metro"] if m not in given] if given else list(table["metro"])
    for tier, k in counts.items():
        pool = metros if tier == "metro" else list(table.get(tier) or [])
        if not pool:
            pool = metros
        if tier == "metro" and given:
            pool = list(given) * 2 + [m for m in table["metro"] if m not in given]   # the named metros get most of the metro share
        for i in range(k):
            out.append((pool[(i + rng.randrange(len(pool))) % len(pool)], tier))
    rng.shuffle(out)
    return out
