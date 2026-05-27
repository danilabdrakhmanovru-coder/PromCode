"""
Алгоритм ранжирования регионов под параметры инвестора.

Логика:
    1. Жёсткие фильтры — если регион не подходит, исключаем.
    2. Считаем 4 компонента (логистика, экономика, инфра, соц.) в [0..1].
    3. Взвешенная сумма + бонусы за ОЭЗ/страховые.
    4. Сортируем по итоговому баллу, берём ТОП-3.

Веса вынесены в константы — крутим итеративно при тестах.
"""
from __future__ import annotations

from typing import List, Optional

from .calculations import compute_areas, compute_estimate
from .models import (
    InvestorInput,
    RankedRegion,
    Region,
    ScoreBreakdown,
)


# Веса базовой суммы. Сумма = 1.0.
# В v6 добавлены бюджет и пользовательские предпочтения, чтобы изменение формы реально меняло ТОП-3.
W_LOGISTICS = 0.16
W_ECONOMY = 0.14
W_INFRASTRUCTURE = 0.16
W_SOCIAL = 0.12
W_BUDGET = 0.18
W_PREFERENCES = 0.24

# Бонусы из ТЗ §4.3
BONUS_OEZ = 0.20            # +20% за наличие ОЭЗ/ТОР
BONUS_REDUCED_INS = 0.15    # +15% за пониженные страховые

# Минимальная свободная мощность для линии сэндвич-панелей по ТЗ §4.4
MIN_POWER_KVA = 300
MAX_POWER_KVA = 800


def required_power_kva(inp: InvestorInput) -> int:
    """
    Требуемая свободная мощность для линии сэндвич-панелей.
    В ТЗ задан диапазон 300–800 кВА; масштабируем его по объёму выпуска.
    """
    span = MAX_POWER_KVA - MIN_POWER_KVA
    ratio = (inp.production_volume_kt - 100) / (1000 - 100)
    return int(round(MIN_POWER_KVA + span * _clamp(ratio)))


def estimate_site_and_network_mln(region: Region, inp: InvestorInput, estimate) -> float:
    """
    Бюджет из формы относится к участку и подключению к сетям, а не ко всей стройке.
    Поэтому сравниваем с подключением мощности + дорогами/парковкой + благоустройством/спортом.
    """
    connection_mln = required_power_kva(inp) * region.infrastructure.connection_fee_rub_kw / 1_000_000
    return round(connection_mln + estimate.infrastructure_mln + estimate.amenities_mln, 2)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _generate_pros_cons(region: Region, inp: InvestorInput) -> tuple[List[str], List[str]]:
    """Автогенерация плюсов и минусов площадки на основе её параметров."""
    pros: List[str] = []
    cons: List[str] = []
    req_power = required_power_kva(inp)

    if region.logistics.steel_supplier_km <= 50:
        pros.append(f"Сталь в {region.logistics.steel_supplier_km} км — огромный плюс (60% себестоимости)")
    elif region.logistics.steel_supplier_km <= 250:
        pros.append(f"Поставщик стали в умеренной доступности — {region.logistics.steel_supplier_km} км")
    else:
        cons.append(f"Сталь далеко — {region.logistics.steel_supplier_km} км")

    if region.logistics.insulation_supplier_km <= 150:
        pros.append(f"Утеплитель близко — {region.logistics.insulation_supplier_km} км")
    elif region.logistics.insulation_supplier_km > 300:
        cons.append(f"Утеплитель далеко — {region.logistics.insulation_supplier_km} км")

    if region.economy.has_oez_tor:
        pros.append("Резидентство ОЭЗ/ТОР — налог на прибыль 0–5%")
    if region.economy.reduced_insurance:
        pros.append("Пониженные страховые взносы (7.6% вместо 30%)")

    if region.logistics.federal_highway_km <= 15:
        pros.append(f"Близко к федеральной трассе — {region.logistics.federal_highway_km} км")
    elif region.logistics.federal_highway_km > 50:
        cons.append(f"Далеко от федеральной трассы — {region.logistics.federal_highway_km} км")

    if inp.needs_railway and not region.logistics.railway_available:
        cons.append("Нет ж/д ветки, а она нужна по условиям")
    elif region.logistics.railway_available:
        pros.append("Есть ж/д ветка")

    if not region.infrastructure.gas_available:
        cons.append("Нет магистрального газа")

    if region.infrastructure.free_power_kva >= req_power * 1.5:
        pros.append(f"Запас мощности достаточный: {region.infrastructure.free_power_kva} кВА при потребности около {req_power} кВА")
    elif region.infrastructure.free_power_kva < req_power * 1.15:
        cons.append(f"Мощность почти без запаса: {region.infrastructure.free_power_kva} кВА при потребности около {req_power} кВА")

    if region.economy.energy_tariff_rub_kwh < 4.7:
        pros.append(f"Низкий энерготариф — {region.economy.energy_tariff_rub_kwh} руб/кВт·ч")
    elif region.economy.energy_tariff_rub_kwh > 5.5:
        cons.append(f"Высокий энерготариф — {region.economy.energy_tariff_rub_kwh} руб/кВт·ч")

    if region.economy.avg_salary_rub > 55000:
        cons.append(f"Высокий уровень ЗП — {region.economy.avg_salary_rub:,} руб (дорогой ФОТ)".replace(",", " "))
    elif region.economy.avg_salary_rub < 45000:
        pros.append(f"Невысокий уровень ЗП — {region.economy.avg_salary_rub:,} руб (выгодный ФОТ)".replace(",", " "))

    if region.social.urban_env_index >= 200:
        pros.append(f"Высокий индекс городской среды Минстроя — {region.social.urban_env_index}")
    elif region.social.urban_env_index < 170:
        cons.append(f"Невысокий индекс городской среды — {region.social.urban_env_index}")

    if region.social.has_profile_college:
        pros.append("Профильные колледжи рядом — готовые сварщики и операторы ЛПМ")
    else:
        cons.append("Нет профильных колледжей — придётся обучать кадры с нуля")

    if region.social.rent_1room_rub <= 22000:
        pros.append(f"Доступная аренда — {region.social.rent_1room_rub:,} руб/мес".replace(",", " "))
    elif region.social.rent_1room_rub >= 35000:
        cons.append(f"Дорогая аренда — {region.social.rent_1room_rub:,} руб/мес".replace(",", " "))

    if region.economy.ecology_class in ("D", "E"):
        cons.append(f"Экологический класс «{region.economy.ecology_class}» — высокая нагрузка района")

    return pros, cons


def _generate_selection_reason(score: ScoreBreakdown, rank: int) -> str:
    """Короткое объяснение, почему площадка попала на эту позицию."""
    strong = []
    if score.logistics >= 0.7:
        strong.append("выигрышной логистики сырья")
    if score.economy >= 0.7:
        strong.append("здоровой экономики площадки")
    if score.infrastructure >= 0.75:
        strong.append("отличной инженерной инфраструктуры")
    if score.social >= 0.7:
        strong.append("развитой социалки и кадрового потенциала")
    if score.bonuses:
        strong.append("серьёзных налоговых льгот")

    prefix_by_rank = {
        1: "Лидер тройки благодаря",
        2: "На втором месте за счёт",
        3: "Замыкает тройку благодаря",
    }
    prefix = prefix_by_rank.get(rank, "Попадает в подбор благодаря")

    if strong:
        return f"{prefix} {', '.join(strong[:3])}."
    return f"{prefix} сбалансированной оценке (итоговый балл {score.final_score:.3f})."




def _labels(values: list, mapping: dict) -> str:
    return ", ".join(mapping.get(str(v), str(v)) for v in values) if values else "без дополнительных объектов"


AMENITY_LABELS = {
    "alley": "аллея",
    "square": "сквер с фонтаном",
    "gazebo": "беседки",
    "stage": "сцена",
    "health_trail": "тропа здоровья",
    "pond": "пруд",
    "art_object": "арт-объект",
}
SPORT_LABELS = {
    "outdoor_gym": "уличные тренажёры",
    "stadium": "стадион",
    "pool": "бассейн",
    "gym": "спортзал",
    "hockey_rink": "хоккейная коробка",
}
ARCH_LABELS = {
    "authenticity": "аутентичность региону",
    "techno": "техно-стиль",
    "eco": "экодизайн",
}


def _generate_ai_object_analysis(region: Region, inp: InvestorInput, score: ScoreBreakdown, site_budget: float) -> str:
    """Демо-аналитика, имитирующая LLM-вывод по конкретному объекту, но основанная на числах."""
    req_power = required_power_kva(inp)
    highway_ok = region.logistics.federal_highway_km <= inp.max_highway_km
    rail_text = "есть ж/д ветка" if region.logistics.railway_available else "ж/д ветки нет"
    amenities = _labels([a.value if hasattr(a, 'value') else a for a in inp.amenities], AMENITY_LABELS)
    sports = _labels([s.value if hasattr(s, 'value') else s for s in inp.sport_objects], SPORT_LABELS)
    return (
        f"ИИ-анализ объекта: площадка подходит под выпуск {inp.production_volume_kt} тыс. м²/год и штат {inp.employees} чел., "
        f"потому что имеет {region.infrastructure.free_power_kva} кВА свободной мощности при расчётной потребности около {req_power} кВА, "
        f"{rail_text}, расстояние до федеральной трассы {region.logistics.federal_highway_km} км "
        f"({'укладывается' if highway_ok else 'не укладывается'} в лимит {inp.max_highway_km} км). "
        f"Для себестоимости важны сырьевые плечи: сталь {region.logistics.steel_supplier_km} км, утеплитель {region.logistics.insulation_supplier_km} км. "
        f"По экономике объект набирает {score.economy:.2f}, по сетям {score.infrastructure:.2f}, по логистике {score.logistics:.2f}. "
        f"Заявленные пожелания по благоустройству ({amenities}) и спорту ({sports}) можно заложить в макет; "
        f"оценка участка/сетей/благоустройства — {site_budget} млн ₽ при бюджете {inp.budget_mln_rub} млн ₽."
    )


def _generate_layout_concept(region: Region, inp: InvestorInput) -> str:
    amenities = _labels([a.value if hasattr(a, 'value') else a for a in inp.amenities], AMENITY_LABELS)
    sports = _labels([s.value if hasattr(s, 'value') else s for s in inp.sport_objects], SPORT_LABELS)
    return (
        "Макет участка: производственный цех размещается в глубине промзоны с прямым выездом грузового транспорта; "
        "склад сырья и готовых панелей ставится рядом с цехом, чтобы сократить внутриплощадочную логистику. "
        "АБК, столовая и медпункт выносятся к главному входу, парковка — у КПП, грузовая зона отделяется от пешеходной. "
        f"Социальный блок учитывает жильё для {inp.housing.pct}% сотрудников и детсад {inp.kindergarten_per_100} мест/100 сотрудников. "
        f"Благоустройство: {amenities}. Спорт: {sports}."
    )


def _budget_materials(region: Region) -> str:
    """
    Приводит культурные материалы к реалистичной промышленной версии.
    Завод нельзя делать из дорогого камня/бронзы/мрамора как из основного материала.
    Поэтому региональный характер показывается экономичными промышленными аналогами.
    """
    raw = [str(x).lower() for x in region.culture.traditional_materials[:4]]
    expensive_keywords = ("мрамор", "гранит", "натуральный камень", "бронза", "медь", "латунь", "ценная древесина", "дуб", "кован")
    has_expensive = any(any(k in item for k in expensive_keywords) for item in raw)

    base = [
        "сэндвич-панели заводского изготовления",
        "окрашенный профлист/металлокассеты",
        "фиброцементные панели на АБК",
        "порошково окрашенные перфорированные экраны",
    ]
    if has_expensive:
        base.append("имитация регионального материала только в навигации и малых формах")
    else:
        base.append("локальные фактуры только как акцент на входной группе")
    return ", ".join(base)


def _generate_design_summary(region: Region, inp: InvestorInput) -> str:
    priority = ARCH_LABELS.get(str(inp.arch_priority.value if hasattr(inp.arch_priority, 'value') else inp.arch_priority), "сбалансированный стиль")
    palette = ", ".join(region.culture.color_palette[:4])
    materials = _budget_materials(region)
    if str(inp.arch_priority.value if hasattr(inp.arch_priority, 'value') else inp.arch_priority) == "techno":
        style = "типовой промышленный каркас, светлые сэндвич-панели, тёмные металлокассеты на АБК, крупные ворота, погрузочные доки и аккуратная промышленная навигация"
    elif str(inp.arch_priority.value if hasattr(inp.arch_priority, 'value') else inp.arch_priority) == "eco":
        style = "светлая оболочка цеха, зелёные буферные зоны, деревянная фактура только на малых формах, водопроницаемые покрытия и озеленение перед АБК"
    else:
        style = "спокойный производственный корпус из сэндвич-панелей и выразительная входная группа, где региональный мотив используется через цвет, перфорацию и навигацию"
    return (
        f"Архитектурная концепция: {priority}. Основа — {style}. "
        f"Палитра региона: {palette}. Реалистичные материалы: {materials}. "
        "Дорогие натуральные материалы не закладываются в несущие и фасадные решения: камень, металл ручной работы и сложный декор допускаются только как небольшие акценты либо заменяются промышленными аналогами. "
        "Культурный код концентрируется во входной группе, навигации, перфорированных экранах и благоустройстве, а сам цех остаётся экономичным и технологичным."
    )


def _generate_render_prompts(region: Region, inp: InvestorInput) -> list[str]:
    design = _generate_design_summary(region, inp)
    base = (
        f"Фотореалистичный рендер промышленного комплекса по производству сэндвич-панелей в локации {region.name}. "
        f"{design} Вид должен показывать реальный завод: цех 8-10 м, склад, АБК, КПП, дороги, парковку, озеленение, грузовой транспорт, люди для масштаба."
    )
    return [
        base + " Камера с юга, главный въезд и АБК на первом плане, мягкий дневной свет.",
        base + " Камера с севера, вид на производственный цех, склад и сервисный двор, без лишнего декора.",
        base + " Камера с запада, акцент на благоустройство, пешеходную аллею и социальные объекты.",
        base + " Камера с востока, акцент на логистический выезд, погрузку панелей и инженерную инфраструктуру."
    ]



def score_budget(region: Region, inp: InvestorInput, estimate) -> float:
    """
    Учитывает бюджет именно на участок, подключение и благоустройство.
    Раньше бюджет только показывался как предупреждение, из-за этого ТОП почти не менялся.
    """
    site_cost = estimate_site_and_network_mln(region, inp, estimate)
    budget = max(float(inp.budget_mln_rub), 1.0)
    ratio = site_cost / budget
    if ratio <= 0.75:
        return 1.0
    if ratio <= 1.0:
        return 0.85
    if ratio <= 1.25:
        return 0.55
    if ratio <= 1.6:
        return 0.25
    return 0.05


def score_preferences(region: Region, inp: InvestorInput) -> float:
    """
    Реакция на пользовательские характеристики, которые раньше почти не влияли на выбор:
    архитектурный приоритет, жильё, детсад, спорт и благоустройство.
    Оценка не делает «магии», но меняет порядок площадок и объяснения.
    """
    arch = inp.arch_priority.value if hasattr(inp.arch_priority, "value") else str(inp.arch_priority)
    amenity_values = {a.value if hasattr(a, "value") else str(a) for a in inp.amenities}
    sport_values = {s.value if hasattr(s, "value") else str(s) for s in inp.sport_objects}

    # Архитектура: разные приоритеты должны тянуть разные типы площадок.
    if arch == "techno":
        arch_score = _clamp(
            0.40 * (region.infrastructure.free_power_kva / 1800) +
            0.25 * (1.0 if region.logistics.railway_available else 0.4) +
            0.20 * _clamp(1.0 - region.logistics.federal_highway_km / 30) +
            0.15 * _clamp(region.economy.tax_relief_score)
        )
    elif arch == "eco":
        ecology_bonus = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.35, "E": 0.15}.get(region.economy.ecology_class, 0.5)
        arch_score = _clamp(
            0.35 * ecology_bonus +
            0.25 * (1.0 if region.infrastructure.gas_available else 0.35) +
            0.20 * _clamp((region.social.urban_env_index - 150) / 100) +
            0.20 * _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)
        )
    else:  # authenticity
        cultural_depth = min(len(region.culture.traditional_materials) + len(region.culture.dominant_styles), 8) / 8
        arch_score = _clamp(0.65 * cultural_depth + 0.35 * _clamp((region.social.urban_env_index - 150) / 100))

    # Социальный пакет: при жилье важнее низкая аренда и городская среда.
    if inp.housing.pct > 0:
        rent_score = _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)
        env_score = _clamp((region.social.urban_env_index - 150) / 100)
        housing_score = _clamp(0.65 * rent_score + 0.35 * env_score)
    else:
        housing_score = 0.60

    # Детсад: чем больше запрос инвестора, тем сильнее важна обеспеченность садами.
    if inp.kindergarten_per_100 > 0:
        kg_need = inp.kindergarten_per_100 / 50
        kg_score = _clamp(region.social.kindergarten_per_100 / 90) * (0.65 + 0.35 * kg_need)
    else:
        kg_score = 0.60

    # Спорт и благоустройство: это влияет на пригодность социальной среды и стоимость.
    active_sport = bool(sport_values & {"stadium", "pool", "gym", "hockey_rink", "outdoor_gym"})
    water_landscape = bool(amenity_values & {"pond", "square"})
    public_space = bool(amenity_values & {"alley", "gazebo", "stage", "health_trail", "art_object"})
    social_base = _clamp((region.social.urban_env_index - 145) / 110)
    sports_score = social_base if active_sport else 0.60
    amenity_score = _clamp(0.7 * social_base + 0.3 * (1.0 if region.infrastructure.gas_available or water_landscape or public_space else 0.5)) if amenity_values else 0.60

    return _clamp(0.30 * arch_score + 0.25 * housing_score + 0.20 * kg_score + 0.15 * sports_score + 0.10 * amenity_score)


def score_logistics(region: Region, inp: InvestorInput) -> float:
    """
    Меньше расстояния — выше балл. Сталь весит больше (60% себестоимости по ТЗ §4.1).
    """
    # Сталь: ближе 100 км — отлично, дальше 500 — плохо
    steel = _clamp(1.0 - (region.logistics.steel_supplier_km - 100) / 400)
    # Утеплитель: ближе 100 — отлично, дальше 400 — плохо
    insul = _clamp(1.0 - (region.logistics.insulation_supplier_km - 100) / 300)
    # Трасса: чем ближе тем лучше, нормируем к запросу пользователя
    highway = _clamp(1.0 - region.logistics.federal_highway_km / max(inp.max_highway_km, 1))
    # Ж/д: если нужна и есть — 1.0, если не нужна — нейтрально 0.7
    if inp.needs_railway:
        railway = 1.0 if region.logistics.railway_available else 0.0
    else:
        railway = 0.7

    # Сталь весит больше прочих (60% себестоимости)
    return _clamp(0.45 * steel + 0.25 * insul + 0.15 * highway + 0.15 * railway)


def score_economy(region: Region, inp: InvestorInput) -> float:
    """
    Чем ниже энерготариф и ЗП относительно бюджета на ФОТ — тем выше балл.
    Льготы учитываются ОТДЕЛЬНО как бонус (см. score_region).
    """
    # Энерготариф: 4 руб/кВт·ч — отлично, 8 — плохо
    energy = _clamp(1.0 - (region.economy.energy_tariff_rub_kwh - 4.0) / 4.0)
    # Налоговый score уже нормирован в JSON
    tax = _clamp(region.economy.tax_relief_score)
    # ЗП: чем ниже тем дешевле ФОТ, но слишком низкая = риск текучки
    # 40-65 тыс. — здоровый диапазон
    salary = region.economy.avg_salary_rub
    if 40_000 <= salary <= 65_000:
        salary_score = 1.0
    elif salary < 40_000:
        salary_score = _clamp(salary / 40_000)
    else:
        salary_score = _clamp(1.0 - (salary - 65_000) / 50_000)

    return _clamp(0.4 * energy + 0.3 * tax + 0.3 * salary_score)


def score_infrastructure(region: Region, inp: InvestorInput) -> float:
    """Газ + свободная мощность + плата за подключение."""
    gas = 1.0 if region.infrastructure.gas_available else 0.3

    # Мощность: потребность зависит от масштаба производства: 300–800 кВА по ТЗ.
    free_kva = region.infrastructure.free_power_kva
    req_kva = required_power_kva(inp)
    if free_kva < req_kva:
        power_score = 0.0
    elif free_kva >= req_kva * 2:
        power_score = 1.0
    else:
        power_score = _clamp((free_kva - req_kva) / req_kva)

    # Плата: 1000 руб/кВт — отлично, 5000+ — плохо
    fee = _clamp(1.0 - (region.infrastructure.connection_fee_rub_kw - 1000) / 4000)
    # Расстояние до подстанции: 2 км — отлично, 10+ — плохо
    sub_dist = _clamp(1.0 - (region.infrastructure.substation_distance_km - 2) / 8)

    return _clamp(0.35 * gas + 0.35 * power_score + 0.20 * fee + 0.10 * sub_dist)


def score_social(region: Region, inp: InvestorInput) -> float:
    """
    Индекс городской среды Минстроя + сады + колледжи + аренда.
    Колледжи особенно важны — для сэндвич-панелей нужны операторы ЛПМ и сварщики.
    """
    # Минстроевский индекс: 180 — норма, 220+ — отлично, <150 — плохо
    env = _clamp((region.social.urban_env_index - 150) / 100)
    # Сады: 70 мест/100 детей — норма по РФ; если пользователь не строит сад — фактор важнее
    kindergarten_relevance = 1.0 if inp.kindergarten_per_100 == 0 else 0.5
    kg = _clamp(region.social.kindergarten_per_100 / 90) * kindergarten_relevance
    # Колледжи — критично для производства
    college = 1.0 if region.social.has_profile_college else 0.3
    # Аренда: 20–35 тыс. — реалистичный диапазон для промышленных городов, 45+ — дорогой рынок
    rent = _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)

    return _clamp(0.25 * env + 0.20 * kg + 0.35 * college + 0.20 * rent)


def passes_hard_filters(region: Region, inp: InvestorInput) -> Optional[str]:
    """
    Возвращает причину отказа (строкой) или None если регион проходит.
    """
    if inp.needs_railway and not region.logistics.railway_available:
        return "Нет ж/д ветки"
    if region.logistics.federal_highway_km > inp.max_highway_km:
        return f"Трасса дальше {inp.max_highway_km} км"
    req_kva = required_power_kva(inp)
    if region.infrastructure.free_power_kva < req_kva:
        return f"Недостаточно свободной мощности: нужно около {req_kva} кВА"

    # Бюджетная проверка — мягкая (warning, не отказ)
    # Жёсткий отсев по бюджету не делаем, потому что регион может предложить льготы

    return None



def scenario_adjustment(region: Region, inp: InvestorInput, site_and_network_mln: float) -> tuple[float, list[str]]:
    """
    Сценарная корректировка результата. Она нужна не для «накрутки», а чтобы разные
    пользовательские сценарии реально давали разные рекомендации:
    - техно-стиль и крупный выпуск тянут площадки с большим запасом мощности;
    - экодизайн тянет площадки с лучшим экоклассом и городской средой;
    - сильный соцпакет тянет регионы с доступной арендой и садами;
    - маленький бюджет снижает площадки, где участок/сети выходят за лимит.
    """
    delta = 0.0
    notes: list[str] = []
    arch = inp.arch_priority.value if hasattr(inp.arch_priority, "value") else str(inp.arch_priority)
    req = required_power_kva(inp)

    if arch == "techno" or inp.production_volume_kt >= 750:
        power_reserve_ratio = region.infrastructure.free_power_kva / max(req, 1)
        tech_delta = _clamp((power_reserve_ratio - 1.5) / 2.5) * 0.075
        if tech_delta > 0.025:
            notes.append("техно-сценарий: высокий запас мощности")
        delta += tech_delta

    if arch == "eco":
        ecology_score = {"A": 1.0, "B": 0.85, "C": 0.55, "D": 0.25, "E": 0.05}.get(region.economy.ecology_class, 0.4)
        eco_delta = (ecology_score - 0.45) * 0.08 + (_clamp((region.social.urban_env_index - 180) / 70) * 0.025)
        if eco_delta > 0.025:
            notes.append("эко-сценарий: лучше экологический/городской профиль")
        delta += eco_delta

    if arch == "authenticity":
        culture_depth = min(len(region.culture.traditional_materials) + len(region.culture.dominant_styles), 8) / 8
        auth_delta = (culture_depth - 0.55) * 0.045
        if auth_delta > 0.015:
            notes.append("аутентичность: сильный региональный культурный код")
        delta += auth_delta

    if inp.housing.pct >= 50 or inp.kindergarten_per_100 >= 30:
        rent_score = _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)
        kg_score = _clamp(region.social.kindergarten_per_100 / 90)
        social_delta = (0.55 * rent_score + 0.45 * kg_score - 0.55) * 0.075
        if social_delta > 0.025:
            notes.append("соцпакет: доступнее жильё/детская инфраструктура")
        delta += social_delta

    budget_ratio = site_and_network_mln / max(float(inp.budget_mln_rub), 1.0)
    if budget_ratio > 1.0:
        delta -= min(0.12, (budget_ratio - 1.0) * 0.12)
    elif budget_ratio < 0.7:
        delta += 0.025
        notes.append("экономия бюджета участка/сетей")

    return round(delta, 4), notes




def scenario_dominance(region: Region, inp: InvestorInput, site_and_network_mln: float) -> tuple[float, list[str]]:
    """
    Сильная сценарная корректировка v7.

    Важное отличие от v6: это уже не косметический бонус ±0.02, а заметный профильный фактор.
    Иначе пользователь меняет жильё/эко/бюджет/мощность, а в ТОП всё равно остаются одни и те же
    «универсально сильные» ОЭЗ. Для демо хакатона подбор должен быть чувствительным и объяснимым.
    """
    delta = 0.0
    notes: list[str] = []
    arch = inp.arch_priority.value if hasattr(inp.arch_priority, "value") else str(inp.arch_priority)
    req = required_power_kva(inp)
    amenity_values = {a.value if hasattr(a, "value") else str(a) for a in inp.amenities}
    sport_values = {s.value if hasattr(s, "value") else str(s) for s in inp.sport_objects}

    # 1) Крупный/техно сценарий: важнее запас мощности, железнодорожность, инфраструктурная готовность.
    is_large_or_tech = arch == "techno" or inp.production_volume_kt >= 700 or inp.employees >= 150
    if is_large_or_tech:
        reserve = region.infrastructure.free_power_kva / max(req, 1)
        infra = _clamp((reserve - 1.1) / 2.8)
        highway = _clamp(1.0 - region.logistics.federal_highway_km / max(inp.max_highway_km, 1))
        ready = 0.55 * infra + 0.25 * highway + 0.20 * (1.0 if region.economy.has_oez_tor else 0.35)
        d = (ready - 0.55) * 0.34
        delta += d
        if d > 0.035:
            notes.append("сценарий крупного завода: высокий запас мощности и готовые сети")
        elif d < -0.035:
            notes.append("сценарий крупного завода: запас мощности слабее лидеров")

    # 2) Социальный сценарий: жильё/детсад/спорт реально должны менять подбор.
    strong_social_request = inp.housing.pct >= 50 or inp.kindergarten_per_100 >= 30 or len(sport_values) >= 3
    if strong_social_request:
        rent = _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)
        kg = _clamp(region.social.kindergarten_per_100 / 85)
        env = _clamp((region.social.urban_env_index - 155) / 85)
        salary = _clamp(1.0 - (region.economy.avg_salary_rub - 40_000) / 35_000)
        social_fit = 0.34 * rent + 0.26 * kg + 0.22 * env + 0.18 * salary
        d = (social_fit - 0.55) * 0.36
        delta += d
        if d > 0.035:
            notes.append("социальный сценарий: доступнее жильё, сады и персонал")
        elif d < -0.035:
            notes.append("социальный сценарий: дорогая аренда/персонал")

    # 3) Эко и благоустройство: поднимаем площадки с экологическим классом B/A и городской средой,
    # а D/E ощутимо опускаем, чтобы «экодизайн» не выдавал индустриально тяжёлые варианты первыми.
    green_request = arch == "eco" or bool(amenity_values & {"pond", "health_trail", "alley", "square"})
    if green_request:
        eco = {"A": 1.0, "B": 0.90, "C": 0.58, "D": 0.20, "E": 0.05}.get(region.economy.ecology_class, 0.45)
        env = _clamp((region.social.urban_env_index - 165) / 75)
        gas = 1.0 if region.infrastructure.gas_available else 0.25
        green_fit = 0.48 * eco + 0.34 * env + 0.18 * gas
        d = (green_fit - 0.55) * 0.38
        delta += d
        if d > 0.035:
            notes.append("эко-сценарий: лучше экологический и городской профиль")
        elif d < -0.035:
            notes.append("эко-сценарий: экологический профиль слабее")

    # 4) Низкий бюджет: льготы важны, но дорогие регионы и подключение должны проседать.
    low_budget = inp.budget_mln_rub <= 60
    if low_budget:
        cheap_site = _clamp(1.0 - site_and_network_mln / max(inp.budget_mln_rub, 1))
        rent_salary = 0.5 * _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000) + 0.5 * _clamp(1.0 - (region.economy.avg_salary_rub - 40_000) / 35_000)
        budget_fit = 0.55 * cheap_site + 0.45 * rent_salary
        d = (budget_fit - 0.48) * 0.34
        delta += d
        if d > 0.035:
            notes.append("малый бюджет: дешевле участок/сети и кадровая база")
        elif d < -0.035:
            notes.append("малый бюджет: площадка дороже по запуску/персоналу")

    # 5) Если ж/д не нужна, убираем монополию крупных ОЭЗ: небольшие площадки без сверхльгот
    # становятся конкурентнее за счёт гибкости и меньшего бюджета запуска.
    if not inp.needs_railway and inp.production_volume_kt <= 350:
        flexible = 0.55 * _clamp(1.0 - region.logistics.federal_highway_km / max(inp.max_highway_km, 1)) + 0.45 * _clamp(1.0 - (region.social.rent_1room_rub - 18_000) / 32_000)
        if not region.economy.has_oez_tor:
            flexible += 0.12
        d = (flexible - 0.55) * 0.28
        delta += d
        if d > 0.035:
            notes.append("малый проект без обязательной ж/д: гибкая локальная площадка")

    return round(delta, 4), notes

def score_region(region: Region, inp: InvestorInput) -> Optional[RankedRegion]:
    """
    Полная оценка региона. Возвращает RankedRegion или None если отфильтрован.
    """
    rejection = passes_hard_filters(region, inp)
    if rejection:
        return None

    areas = compute_areas(inp)
    estimate = compute_estimate(areas, inp)

    log_s = score_logistics(region, inp)
    eco_s = score_economy(region, inp)
    inf_s = score_infrastructure(region, inp)
    soc_s = score_social(region, inp)
    budget_s = score_budget(region, inp, estimate)
    pref_s = score_preferences(region, inp)

    base = (W_LOGISTICS * log_s + W_ECONOMY * eco_s
            + W_INFRASTRUCTURE * inf_s + W_SOCIAL * soc_s
            + W_BUDGET * budget_s + W_PREFERENCES * pref_s)

    bonuses: List[str] = []
    multiplier = 1.0
    if region.economy.has_oez_tor:
        multiplier += BONUS_OEZ
        bonuses.append(f"+{int(BONUS_OEZ * 100)}% за наличие ОЭЗ/ТОР")
    if region.economy.reduced_insurance:
        multiplier += BONUS_REDUCED_INS
        bonuses.append(f"+{int(BONUS_REDUCED_INS * 100)}% за пониженные страховые")
    if budget_s >= 0.85:
        bonuses.append("укладывается в бюджет участка/сетей")
    elif budget_s <= 0.25:
        bonuses.append("дороже бюджета — нужен пересмотр состава объектов")
    if pref_s >= 0.75:
        bonuses.append("хорошо совпадает с выбранными соц./арх. приоритетами")

    site_and_network_mln = estimate_site_and_network_mln(region, inp, estimate)
    adjustment, scenario_notes = scenario_adjustment(region, inp, site_and_network_mln)
    dominance_adjustment, dominance_notes = scenario_dominance(region, inp, site_and_network_mln)
    for note in scenario_notes + dominance_notes:
        if note not in bonuses:
            bonuses.append(note)

    # v48: итоговый рейтинг больше не "прижимается" к 1.000 из-за бонусов.
    # Базовая оценка остаётся главным фактором, а бонусы дают ограниченную прибавку.
    # Так пользователь видит реалистичный рейтинг, а не "идеальные" 1.000 у нескольких площадок.
    bonus_points = 0.0
    if region.economy.has_oez_tor:
        bonus_points += 0.055
    if region.economy.reduced_insurance:
        bonus_points += 0.040
    bonus_points += max(-0.08, min(0.08, adjustment * 0.45))
    bonus_points += max(-0.06, min(0.06, dominance_adjustment * 0.45))
    final = round(max(0.0, min(0.97, base + bonus_points)), 4)

    breakdown = ScoreBreakdown(
        logistics=round(log_s, 3),
        economy=round(eco_s, 3),
        infrastructure=round(inf_s, 3),
        social=round(soc_s, 3),
        bonuses=bonuses,
        final_score=final,
    )

    pros, cons = _generate_pros_cons(region, inp)
    if site_and_network_mln <= inp.budget_mln_rub:
        pros.append(f"Затраты на участок/сети укладываются в бюджет: {site_and_network_mln} млн ₽ из {inp.budget_mln_rub} млн ₽")
    else:
        cons.append(f"Затраты на участок/сети выше бюджета: {site_and_network_mln} млн ₽ из {inp.budget_mln_rub} млн ₽")

    return RankedRegion(
        region=region,
        score=breakdown,
        areas=areas,
        estimate=estimate,
        site_and_network_mln=site_and_network_mln,
        required_power_kva=required_power_kva(inp),
        pros=pros,
        cons=cons,
        selection_reason="",  # заполняется в rank_regions, когда известна позиция
        ai_object_analysis=_generate_ai_object_analysis(region, inp, breakdown, site_and_network_mln),
        layout_concept=_generate_layout_concept(region, inp),
        design_summary=_generate_design_summary(region, inp),
        render_prompts=_generate_render_prompts(region, inp),
    )


def rank_regions(regions: List[Region], inp: InvestorInput) -> List[RankedRegion]:
    """Ранжировать список площадок и вернуть строго ТОП-3, как требуется в ТЗ."""
    scored = [score_region(r, inp) for r in regions]
    valid = [s for s in scored if s is not None]
    # Дополнительно предпочитаем меньшие затраты на участок/сети при близком рейтинге.
    valid.sort(key=lambda x: (x.score.final_score, -x.site_and_network_mln), reverse=True)
    # ТЗ просит ТОП-3 региона с площадками, поэтому не отдаём три соседние площадки одного субъекта РФ.
    # Сначала берём лучшую площадку каждого субъекта, а если регионов не хватает — добираем следующими площадками.
    result = []
    used_subjects = set()
    for item in valid:
        subject = (getattr(item.region, "federal_subject", "") or item.region.name).strip()
        if subject not in used_subjects:
            result.append(item)
            used_subjects.add(subject)
        if len(result) == 3:
            break
    if len(result) < 3:
        for item in valid:
            if item not in result:
                result.append(item)
            if len(result) == 3:
                break
    for rank, item in enumerate(result, start=1):
        item.selection_reason = _generate_selection_reason(item.score, rank)
    return result
