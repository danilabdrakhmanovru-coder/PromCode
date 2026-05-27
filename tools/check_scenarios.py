"""Быстрая проверка логики ранжирования для демо-сценариев.
Запуск из корня проекта: python tools/check_scenarios.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import REGIONS
from backend.models import InvestorInput, Housing, HousingType
from backend.ranking import rank_regions

SCENARIOS = {
    "Базовый инвестор": dict(
        production_volume_kt=500,
        employees=80,
        budget_mln_rub=150,
        needs_railway=True,
        max_highway_km=20,
        arch_priority="authenticity",
        amenities=["alley", "square"],
        housing=Housing(pct=30, type=HousingType.DORMITORY),
        kindergarten_per_100=30,
        sport_objects=["outdoor_gym", "stadium"],
    ),
    "Крупное производство, строгая трасса": dict(
        production_volume_kt=1000,
        employees=200,
        budget_mln_rub=300,
        needs_railway=True,
        max_highway_km=5,
        arch_priority="eco",
        amenities=["pond", "health_trail", "art_object"],
        housing=Housing(pct=70, type=HousingType.APARTMENT),
        kindergarten_per_100=50,
        sport_objects=["pool", "gym"],
    ),
    "Минимальный проект без ж/д": dict(
        production_volume_kt=100,
        employees=10,
        budget_mln_rub=10,
        needs_railway=False,
        max_highway_km=100,
        arch_priority="techno",
        amenities=[],
        housing=Housing(pct=0, type=HousingType.DORMITORY),
        kindergarten_per_100=0,
        sport_objects=[],
    ),
}

for name, payload in SCENARIOS.items():
    inp = InvestorInput(**payload)
    ranked = rank_regions(REGIONS, inp)
    print(f"\n{name}: {len(ranked)} площадки")
    for i, item in enumerate(ranked, 1):
        print(
            f"{i}. {item.region.name} | рейтинг={item.score.final_score:.4f} | "
            f"мощность≈{item.required_power_kva} кВА | участок/сети={item.site_and_network_mln} млн ₽ | "
            f"полная смета={item.estimate.total_mln} млн ₽"
        )
