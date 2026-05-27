"""
LLM-клиент для генерации аналитической справки.

Поддерживает любой OpenAI-совместимый API (OpenAI, OpenRouter, локальный Ollama).
Если LLM_USE_MOCK=true или ключ не задан — возвращает моки. Это позволяет
разрабатывать без оплаты API и иметь рабочее демо на случай отказа сервиса.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from .models import InvestorInput, Region, RegionBrief

load_dotenv()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class LLMClient:
    def __init__(self):
        self.api_base = os.getenv("LLM_API_BASE", "https://openrouter.ai/api/v1")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "anthropic/claude-3.5-sonnet")
        self.use_mock = (
            os.getenv("LLM_USE_MOCK", "false").lower() == "true"
            or not self.api_key
            or "замени-меня" in self.api_key
        )

    def generate_region_brief(self, region: Region, inp: InvestorInput) -> RegionBrief:
        if self.use_mock:
            return self._mock_brief(region, inp)
        try:
            return self._real_brief(region, inp)
        except Exception as exc:
            print(f"[llm] real call failed: {exc}; fallback to mock")
            return self._mock_brief(region, inp)

    # ------------------------------------------------------------------
    #  Реальный вызов LLM
    # ------------------------------------------------------------------

    def _real_brief(self, region: Region, inp: InvestorInput) -> RegionBrief:
        system_prompt = (PROMPTS_DIR / "region_brief.txt").read_text(encoding="utf-8")
        user_payload = {
            "region": region.model_dump(),
            "investor_input": inp.model_dump(),
            "response_schema": RegionBrief.model_json_schema(),
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=60.0) as client:
            r = client.post(f"{self.api_base}/chat/completions",
                            json=body, headers=headers)
            r.raise_for_status()
            data = r.json()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return RegionBrief(**parsed)

    # ------------------------------------------------------------------
    #  Мок — нарратив "хранителя памяти", использует JSON-данные региона
    # ------------------------------------------------------------------

    def _mock_brief(self, region: Region, inp: InvestorInput) -> RegionBrief:
        figure = region.culture.historical_figures[0] if region.culture.historical_figures else None
        figure_name = figure.name if figure else "местные мастера"
        figure_role = figure.role if figure else "промышленники"
        design_hint = figure.design_hint if figure else "региональная архитектурная традиция"

        intro = (
            f"{region.name} рассматривается как промышленная площадка для завода сэндвич-панелей, "
            f"где важно совместить логистику, инженерные сети и спокойный региональный образ. "
            f"Культурная привязка используется не как декоративная перегрузка цеха, а как аккуратный акцент в АБК, входной группе и общественных пространствах."
        )

        social = (
            f"Индекс городской среды Минстроя — {region.social.urban_env_index} баллов. "
            f"Обеспеченность садами {region.social.kindergarten_per_100} мест на 100 детей. "
            f"Профильные колледжи (сварщики, операторы ЛПМ): "
            f"{'есть' if region.social.has_profile_college else 'нет'}. "
            f"Средняя аренда однушки — {region.social.rent_1room_rub:,} руб/мес.".replace(",", " ")
        )

        bonuses = []
        if region.economy.has_oez_tor:
            bonuses.append("резидентство ОЭЗ/ТОР")
        if region.economy.reduced_insurance:
            bonuses.append("пониженные страховые взносы (7.6% вместо 30%)")
        bonus_text = ", ".join(bonuses) if bonuses else "без специальных льгот"

        economy = (
            f"Льготы: {bonus_text}. "
            f"Энерготариф для промышленности — {region.economy.energy_tariff_rub_kwh} руб/кВт·ч. "
            f"Средняя ЗП — {region.economy.avg_salary_rub:,} руб/мес. ".replace(",", " ") +
            f"Экологический класс — {region.economy.ecology_class}."
        )

        infra = (
            f"Магистральный газ на площадке: {'есть' if region.infrastructure.gas_available else 'нет'}. "
            f"Свободная мощность на подстанции — {region.infrastructure.free_power_kva} кВА "
            f"(для линии нужно 300–800 кВА). "
            f"Расстояние до подстанции — {region.infrastructure.substation_distance_km} км. "
            f"Плата за техприсоединение — {region.infrastructure.connection_fee_rub_kw:,} руб/кВт.".replace(",", " ")
        )

        logistics = (
            f"Сталь — главный материал (60% себестоимости). До поставщика рулонной стали "
            f"{region.logistics.steel_supplier_km} км. До поставщика утеплителя "
            f"{region.logistics.insulation_supplier_km} км. До федеральной трассы "
            f"{region.logistics.federal_highway_km} км. "
            f"Ж/д ветка: {'доступна' if region.logistics.railway_available else 'отсутствует'}."
        )

        # Killer-feature 2: социальный анализ района
        demo = region.demographics_sample
        hr = (
            f"Демография района: преобладают {demo.dominant_age_group}. "
            f"Переполненность школ {demo.schools_overcrowding_pct}%, нехватка садов "
            f"{demo.kindergartens_shortage_pct}%. {demo.social_recommendation}"
        )
        if inp.kindergarten_per_100 > 0:
            hr += f" Запланированный детсад на {inp.kindergarten_per_100} мест/100 сотрудников полностью отвечает этой потребности."
        if inp.housing.pct > 0:
            hr += f" Обеспечение {inp.housing.pct}% сотрудников жильём (тип: {inp.housing.type.value}) дополнительно снижает текучку."

        # Killer-feature 1: концепт с привязкой к личности
        if figure:
            design = (
                f"Архитектурный концепт строится вокруг наследия {figure.name} ({figure.role}, {figure.era}). "
                f"Стилистика: {design_hint}. "
                f"Палитра: {', '.join(region.culture.color_palette[:3])}. "
                f"Материалы фасада и АБК: {', '.join(region.culture.traditional_materials[:3])}. "
                f"Завод не выглядит «безликой коробкой» — он становится точкой притяжения, "
                f"в которой считывается культурный код места."
            )
        else:
            design = (
                f"Стилистика: {', '.join(region.culture.dominant_styles)}. "
                f"Палитра: {', '.join(region.culture.color_palette[:3])}. "
                f"Материалы: {', '.join(region.culture.traditional_materials[:3])}."
            )

        site_specific = (
            f"Под параметры инвестора площадка интересна сочетанием логистики и инженерной готовности: "
            f"свободная мощность {region.infrastructure.free_power_kva} кВА, трасса {region.logistics.federal_highway_km} км, "
            f"сталь {region.logistics.steel_supplier_km} км, утеплитель {region.logistics.insulation_supplier_km} км. "
            f"Для штата {inp.employees} человек важны аренда {region.social.rent_1room_rub:,} руб/мес и наличие профильных колледжей: "
            f"{'есть' if region.social.has_profile_college else 'нет'}."
        ).replace(",", " ")

        amenities = ", ".join([str(x.value) for x in inp.amenities]) if inp.amenities else "без дополнительных объектов"
        sports = ", ".join([str(x.value) for x in inp.sport_objects]) if inp.sport_objects else "без спортобъектов"
        layout = (
            "Практичный макет: цех и склад объединяются в производственное ядро, грузовой двор располагается со стороны трассы/ж-д ветки, "
            "АБК и КПП — у главного входа, парковка — до проходной, пешеходные маршруты отделены от грузовых. "
            f"Социальные объекты выносятся в тихую зону: жильё {inp.housing.pct}% сотрудников, детсад {inp.kindergarten_per_100} мест/100 сотрудников. "
            f"Благоустройство: {amenities}; спорт: {sports}."
        )

        design = (
            f"Реалистичный концепт: {', '.join(region.culture.dominant_styles[:2])}; "
            f"материалы — {', '.join(region.culture.traditional_materials[:3])}; "
            f"палитра — {', '.join(region.culture.color_palette[:4])}. "
            "Главный принцип — не превращать завод в музейный объект: культурный код размещается в входной группе, навигации, перфорированных фасадных экранах АБК, малых архитектурных формах и благоустройстве. "
            "Производственный корпус остаётся современным, технологичным и легко обслуживаемым."
        )

        base_render = (
            f"Фотореалистичный рендер завода сэндвич-панелей, {region.name}. "
            f"{design} Показать цех 8-10 м, склад, АБК, КПП, дороги, парковку, озеленение, людей и грузовой транспорт."
        )
        renders = [
            base_render + " Вид с юга: главный вход, АБК и общественная зона.",
            base_render + " Вид с севера: производственный цех, склад и инженерная часть.",
            base_render + " Вид с запада: благоустройство, пешеходная аллея и социальные объекты.",
            base_render + " Вид с востока: грузовой выезд, погрузка панелей, связь с трассой/ж-д."
        ]

        return RegionBrief(
            intro_narrative=intro,
            site_specific_analysis=site_specific,
            social_passport=social,
            economy_summary=economy,
            infrastructure_summary=infra,
            logistics_summary=logistics,
            hr_retention_tips=hr,
            layout_concept=layout,
            design_concept=design,
            render_prompts=renders,
        )


_llm_singleton: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = LLMClient()
    return _llm_singleton
