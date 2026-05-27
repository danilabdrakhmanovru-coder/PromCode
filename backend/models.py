"""
Pydantic-модели проекта «ПромКод».

Здесь живут все типы данных, которыми обмениваются фронт и бэк.
Если поле появляется в форме — оно появляется в `InvestorInput`.
Если поле появляется в JSON-базе регионов — оно появляется в `Region`.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================
#  ВХОД ФОРМЫ (10 ПОЛЕЙ ИЗ ТЗ §3)
# ============================================================

class ArchPriority(str, Enum):
    AUTHENTICITY = "authenticity"   # Аутентичность региону
    TECHNO = "techno"                # Техно-стиль
    ECO = "eco"                      # Экодизайн


class HousingType(str, Enum):
    DORMITORY = "dormitory"   # Общежитие, 25 м²/чел
    APARTMENT = "apartment"   # Квартиры, 40 м²/чел


class Amenity(str, Enum):
    ALLEY = "alley"             # Аллея
    SQUARE = "square"           # Сквер с фонтаном
    GAZEBO = "gazebo"           # Беседки
    STAGE = "stage"             # Сцена
    HEALTH_TRAIL = "health_trail"  # Тропа здоровья
    POND = "pond"               # Пруд
    ART_OBJECT = "art_object"   # Арт-объект


class SportObject(str, Enum):
    OUTDOOR_GYM = "outdoor_gym"        # Уличные тренажёры
    STADIUM = "stadium"                # Стадион
    POOL = "pool"                      # Бассейн
    GYM = "gym"                        # Спортзал
    HOCKEY_RINK = "hockey_rink"        # Хоккейная коробка


class Housing(BaseModel):
    """Поле «обеспечение жильём». Если pct=0, type игнорируется."""
    pct: int = Field(..., ge=0, le=70, description="Процент сотрудников: 0/30/50/70")
    type: HousingType = HousingType.DORMITORY

    @field_validator("pct")
    @classmethod
    def validate_pct(cls, value: int) -> int:
        allowed = {0, 30, 50, 70}
        if value not in allowed:
            raise ValueError("Доля жилья должна быть одним из значений: 0, 30, 50, 70")
        return value


class InvestorInput(BaseModel):
    """
    10 полей формы. Точно соответствует §3 ТЗ.
    Эта модель — единственный источник правды для входа.
    """
    # 1-3: Производство
    production_volume_kt: int = Field(..., ge=100, le=1000,
                                       description="Объём выпуска, тыс. м² панелей/год")
    employees: int = Field(..., ge=10, le=200, description="Количество сотрудников")
    budget_mln_rub: int = Field(..., ge=10, le=300,
                                  description="Бюджет на участок и подключение к сетям, млн руб")

    # 4-5: Логистика
    needs_railway: bool = Field(..., description="Необходима ж/д ветка")
    max_highway_km: int = Field(..., ge=1, le=100,
                                 description="Макс. расстояние до федеральной трассы, км")

    # 6-7: Архитектура и стиль
    arch_priority: ArchPriority
    amenities: List[Amenity] = Field(default_factory=list,
                                       description="Элементы благоустройства. В демо можно выбрать любое количество, чтобы проверить полный пакет пожеланий инвестора")

    # 8-10: Социальные приоритеты
    housing: Housing
    kindergarten_per_100: int = Field(..., ge=0, le=50,
                                        description="Мест в саду на 100 сотрудников: 0/15/30/50")
    sport_objects: List[SportObject] = Field(default_factory=list,
                                               description="Спортобъекты. В демо можно выбрать любое количество")

    @field_validator("kindergarten_per_100")
    @classmethod
    def validate_kindergarten(cls, value: int) -> int:
        allowed = {0, 15, 30, 50}
        if value not in allowed:
            raise ValueError("Детский сад должен быть одним из значений: 0, 15, 30, 50 мест на 100 сотрудников")
        return value

    @field_validator("amenities")
    @classmethod
    def validate_unique_amenities(cls, value: List[Amenity]) -> List[Amenity]:
        if len(set(value)) != len(value):
            raise ValueError("Благоустройство не должно содержать повторяющиеся пункты")
        return value

    @field_validator("sport_objects")
    @classmethod
    def validate_unique_sport_objects(cls, value: List[SportObject]) -> List[SportObject]:
        if len(set(value)) != len(value):
            raise ValueError("Спортобъекты не должны повторяться")
        return value

    @model_validator(mode="after")
    def normalize_housing(self):
        # При 0% тип жилья не влияет на расчёты, но оставляем дефолт для единого JSON.
        if self.housing.pct == 0:
            self.housing.type = HousingType.DORMITORY
        return self


# ============================================================
#  МОДЕЛЬ РЕГИОНА (JSON-БАЗА)
# ============================================================

class Coord(BaseModel):
    lat: float
    lon: float


class IndustrialZone(BaseModel):
    name: str
    lat: float
    lon: float
    type: str  # "ОЭЗ", "ТОР", "Индустриальный парк"


class RegionLogistics(BaseModel):
    steel_supplier_km: int
    insulation_supplier_km: int
    federal_highway_km: int
    railway_available: bool


class RegionEconomy(BaseModel):
    has_oez_tor: bool
    tax_relief_score: float  # 0..1
    reduced_insurance: bool
    energy_tariff_rub_kwh: float
    avg_salary_rub: int
    ecology_class: str  # "A".."E"


class RegionInfrastructure(BaseModel):
    gas_available: bool
    free_power_kva: int
    substation_distance_km: int
    connection_fee_rub_kw: int


class RegionSocial(BaseModel):
    urban_env_index: int          # Минстрой, обычно 150-260
    kindergarten_per_100: int     # Мест на 100 детей, среднее по РФ ~70
    has_profile_college: bool     # Колледжи: сварщики, операторы ЛПМ
    rent_1room_rub: int           # Средняя аренда однушки


class HistoricalFigure(BaseModel):
    """Killer-feature: историческая личность региона для нарратива и концепт-борда."""
    name: str
    role: str
    era: str
    design_hint: str
    color_accent: str  # hex


class AlternativeSite(BaseModel):
    """Альтернативная точка внутри города для размещения площадки."""
    id: str
    name: str
    lat: float
    lon: float
    type: str  # "Индустриальный парк", "Гринфилд", "Промзона", "ТОР"
    description: str   # Короткое описание плюсов точки


class RegionCulture(BaseModel):
    dominant_styles: List[str]
    traditional_materials: List[str]
    color_palette: List[str]
    historical_figures: List[HistoricalFigure] = Field(default_factory=list)


class DemographicsSample(BaseModel):
    """
    Сэмпл по району, где может располагаться промплощадка.
    Используется для рекомендаций по соц. инфраструктуре (фишка 2).
    """
    dominant_age_group: str        # "семьи 25-40", "пенсионеры", "молодёжь 18-30"
    schools_overcrowding_pct: int
    kindergartens_shortage_pct: int
    social_recommendation: str


class DataSource(BaseModel):
    """Источник данных для конкретной площадки/показателей."""
    group: str
    title: str
    url: str
    comment: str = ""


class DataQuality(BaseModel):
    """Маркировка качества данных: официально / демо-оценка / требует проверки."""
    status: str = "demo_estimate"
    note: str = "Числовые значения в MVP являются демонстрационной нормализованной базой и требуют финальной сверки с первоисточниками перед промышленным использованием."
    quality_by_field: Dict[str, str] = Field(
        default_factory=dict,
        description="Статусы по группам показателей: official_verified / official_stat / imported_official / demo_estimate / needs_review"
    )
    last_verified: str = ""
    verified_source_groups: List[str] = Field(default_factory=list)


class Region(BaseModel):
    id: str
    name: str
    federal_subject: str = Field("Не указан", description="Субъект РФ. Нужен, чтобы выдавать ТОП-3 именно регионов, а не три соседние площадки одного субъекта")
    center: Coord
    industrial_zones: List[IndustrialZone]
    logistics: RegionLogistics
    economy: RegionEconomy
    infrastructure: RegionInfrastructure
    social: RegionSocial
    culture: RegionCulture
    demographics_sample: DemographicsSample
    alternative_sites: List[AlternativeSite] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    data_sources: List[DataSource] = Field(default_factory=list)


# ============================================================
#  ОТВЕТ /rank
# ============================================================

class ScoreBreakdown(BaseModel):
    """Разбивка итогового балла по компонентам для прозрачности."""
    logistics: float
    economy: float
    infrastructure: float
    social: float
    bonuses: List[str] = Field(default_factory=list)  # ["+20% за ОЭЗ", ...]
    final_score: float


class AreasComputed(BaseModel):
    """Расчётные площади (см. ТЗ §6.2)."""
    workshop_m2: float
    warehouse_m2: float
    office_m2: float
    parking_m2: float
    roads_m2: float
    housing_m2: float
    kindergarten_m2: float
    canteen_m2: float
    medical_m2: float
    total_m2: float


class EstimateComputed(BaseModel):
    """Укрупнённая смета (см. ТЗ §6.3), млн руб."""
    construction_mln: float          # цех, склад, АБК
    housing_mln: float
    social_mln: float                # сад, столовая, медпункт
    infrastructure_mln: float        # дороги, парковка
    amenities_mln: float             # благоустройство + спорт
    total_mln: float


class RankedRegion(BaseModel):
    region: Region
    score: ScoreBreakdown
    areas: AreasComputed
    estimate: EstimateComputed
    site_and_network_mln: float = Field(0.0, description="Оценка затрат на участок, подключение к сетям, дороги/парковку и благоустройство, млн руб")
    required_power_kva: int = Field(300, description="Расчётная потребность линии в свободной мощности, кВА")
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    selection_reason: str = ""
    ai_object_analysis: str = Field("", description="Краткий ИИ-анализ: почему конкретная площадка подходит под введённые характеристики")
    layout_concept: str = Field("", description="Практичная схема размещения производственных и социальных объектов на участке")
    design_summary: str = Field("", description="Короткая архитектурная идея без странных/оторванных от производства формулировок")
    render_prompts: List[str] = Field(default_factory=list, description="Промпты для 4 фотореалистичных рендеров: юг/север/запад/восток")




class DataStatusResponse(BaseModel):
    regions_count: int
    last_update: str = ""
    official_verified_count: int = 0
    needs_review_count: int = 0
    demo_estimate_count: int = 0
    sources: List[DataSource] = Field(default_factory=list)
    message: str = ""


class DataRefreshResponse(BaseModel):
    mode: str
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    needs_review: int = 0
    sources_checked: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    message: str = ""

class RankResponse(BaseModel):
    """Ответ POST /rank."""
    top3: List[RankedRegion]
    input_echo: InvestorInput   # для отладки и логирования


# ============================================================
#  ОТВЕТ LLM (АНАЛИТИЧЕСКАЯ СПРАВКА)
# ============================================================

class RegionBrief(BaseModel):
    """
    Структурированный ответ LLM по справке региона.
    Жёсткая Pydantic-схема для Structured Output.
    """
    intro_narrative: str = Field(..., description="Нарратив региона, 2-4 предложения без чрезмерной художественности")
    site_specific_analysis: str = Field(..., description="Анализ конкретной площадки под введённые параметры: почему она хороша и где риски")
    social_passport: str = Field(..., description="Социальный паспорт: индекс среды, сады, колледжи, аренда")
    economy_summary: str = Field(..., description="Экономика: льготы, энерготариф, ЗП")
    infrastructure_summary: str = Field(..., description="Сети: газ, мощность, плата за подключение")
    logistics_summary: str = Field(..., description="Логистика сырья: сталь, утеплитель, трассы")
    hr_retention_tips: str = Field(..., description="Рекомендации по удержанию персонала")
    layout_concept: str = Field(..., description="Макет предприятия: как расположить цех, склад, АБК, дороги, соц.объекты и благоустройство")
    design_concept: str = Field(..., description="Реалистичный архитектурный концепт с палитрой, материалами, фасадом и благоустройством")
    render_prompts: List[str] = Field(default_factory=list, description="4 промпта для рендеров: юг, север, запад, восток")


class RegionDetailResponse(BaseModel):
    """Ответ GET /region/{id}/brief."""
    region: Region
    brief: RegionBrief
