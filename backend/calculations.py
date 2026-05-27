"""
Расчёт площадей и сметы.
Все формулы — строго из ТЗ §6.

Площади возвращаются в м², смета — в млн руб.
"""
from __future__ import annotations

from .models import (
    AreasComputed,
    EstimateComputed,
    HousingType,
    InvestorInput,
    Region,
    SportObject,
)


# Нормативы из ТЗ §6.1
WORKSHOP_PER_KT = 0.4              # м²/тыс. м² панелей в год
WAREHOUSE_RATIO = 0.35
OFFICE_RATIO = 0.02
PARKING_RATE = 0.5                 # машино-мест на сотрудника
PARKING_M2_PER_SPOT = 25
ROADS_RATIO = 0.25                 # от (цех + склад)
CANTEEN_PER_EMP = 0.5
MEDICAL_PER_EMP = 0.1
MEDICAL_MIN_M2 = 20
KINDERGARTEN_M2_PER_SEAT = 15
HOUSING_M2 = {
    HousingType.DORMITORY: 25,
    HousingType.APARTMENT: 40,
}

# Сметные нормативы из ТЗ §6.3 (руб/м²)
COST_PER_M2 = {
    "workshop": 35_000,
    "warehouse": 35_000,
    "office": 55_000,
    "housing_dormitory": 70_000,
    "housing_apartment": 90_000,
    "kindergarten": 50_000,
    "canteen": 35_000,
    "medical": 45_000,
    "roads_parking": 5_000,
    "amenities": 2_000,   # на м² участка
}

# Спортобъекты — штучно (млн руб)
SPORT_OBJECT_COST_MLN = {
    SportObject.STADIUM: 5.0,
    SportObject.POOL: 8.0,
    SportObject.GYM: 3.0,
    SportObject.HOCKEY_RINK: 2.0,
    SportObject.OUTDOOR_GYM: 0.5,    # уличные тренажёры — оценка
}


def compute_areas(inp: InvestorInput) -> AreasComputed:
    """Все площади по формулам §6.2 ТЗ."""
    workshop = inp.production_volume_kt * WORKSHOP_PER_KT
    warehouse = workshop * WAREHOUSE_RATIO
    office = workshop * OFFICE_RATIO
    parking = inp.employees * PARKING_RATE * PARKING_M2_PER_SPOT
    roads = (workshop + warehouse) * ROADS_RATIO

    housing = inp.employees * (inp.housing.pct / 100) * HOUSING_M2[inp.housing.type]
    kindergarten = (inp.employees / 100) * inp.kindergarten_per_100 * KINDERGARTEN_M2_PER_SEAT
    canteen = inp.employees * CANTEEN_PER_EMP
    medical = max(inp.employees * MEDICAL_PER_EMP, MEDICAL_MIN_M2)

    total = (workshop + warehouse + office + parking + roads
             + housing + kindergarten + canteen + medical)

    return AreasComputed(
        workshop_m2=round(workshop, 1),
        warehouse_m2=round(warehouse, 1),
        office_m2=round(office, 1),
        parking_m2=round(parking, 1),
        roads_m2=round(roads, 1),
        housing_m2=round(housing, 1),
        kindergarten_m2=round(kindergarten, 1),
        canteen_m2=round(canteen, 1),
        medical_m2=round(medical, 1),
        total_m2=round(total, 1),
    )


def compute_estimate(areas: AreasComputed, inp: InvestorInput) -> EstimateComputed:
    """
    Укрупнённая смета §6.3 ТЗ.
    Возвращает суммы по блокам в млн руб.
    """
    construction = (
        areas.workshop_m2 * COST_PER_M2["workshop"]
        + areas.warehouse_m2 * COST_PER_M2["warehouse"]
        + areas.office_m2 * COST_PER_M2["office"]
    )

    housing_cost_per_m2 = (
        COST_PER_M2["housing_apartment"]
        if inp.housing.type == HousingType.APARTMENT
        else COST_PER_M2["housing_dormitory"]
    )
    housing = areas.housing_m2 * housing_cost_per_m2

    social = (
        areas.kindergarten_m2 * COST_PER_M2["kindergarten"]
        + areas.canteen_m2 * COST_PER_M2["canteen"]
        + areas.medical_m2 * COST_PER_M2["medical"]
    )

    infrastructure = (areas.roads_m2 + areas.parking_m2) * COST_PER_M2["roads_parking"]

    # Благоустройство (на м² участка, считаем 30% от полной территории).
    # Точная площадь участка зависит от планировки; для прикидки берём 1.3 × total_m2.
    amenities_area = areas.total_m2 * 0.3
    amenities = amenities_area * COST_PER_M2["amenities"]

    # Спортобъекты — штучно
    sport_total_mln = sum(SPORT_OBJECT_COST_MLN.get(s, 0) for s in inp.sport_objects)
    amenities += sport_total_mln * 1_000_000

    total = construction + housing + social + infrastructure + amenities

    def to_mln(x: float) -> float:
        return round(x / 1_000_000, 2)

    return EstimateComputed(
        construction_mln=to_mln(construction),
        housing_mln=to_mln(housing),
        social_mln=to_mln(social),
        infrastructure_mln=to_mln(infrastructure),
        amenities_mln=to_mln(amenities),
        total_mln=to_mln(total),
    )


def estimate_fits_budget(inp: InvestorInput, region: Region) -> bool:
    """
    Грубая проверка: укладывается ли проект в бюджет инвестора.
    Не учитывает региональные различия в стоимости — это в финале.
    """
    areas = compute_areas(inp)
    estimate = compute_estimate(areas, inp)
    # +20% запас на подключение к сетям и непредвиденные
    return estimate.total_mln * 1.2 <= inp.budget_mln_rub
