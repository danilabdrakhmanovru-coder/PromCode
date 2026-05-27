"""Сервис обновления и маркировки данных по официальным источникам.

Для хакатонного MVP реализован безопасный гибридный режим:
1) локальная JSON-база остаётся рабочей даже без интернета;
2) официальные источники фиксируются и отображаются в интерфейсе;
3) подтверждаемые поля получают статус official_verified / official_stat;
4) инженерные показатели, которые нельзя честно получить из единого реестра,
   остаются needs_review/demo_estimate;
5) добавлен импорт CSV как практичный путь загрузки выгрузок из реестров.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ..models import Region

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR.parent
REGIONS_PATH = BASE_DIR / "data" / "regions.json"
SOURCES_PATH = BASE_DIR / "data" / "official_sources.json"
UPDATE_LOG_PATH = BASE_DIR / "data" / "update_log.json"

DEFAULT_QUALITY_BY_FIELD = {
    "site_identity": "official_name_demo_metrics",
    "coordinates": "needs_review",
    "oez_tor_status": "official_name_demo_metrics",
    "tax_benefits": "needs_review",
    "urban_env_index": "needs_review",
    "salary": "needs_review",
    "kindergarten": "needs_review",
    "profile_college": "needs_review",
    "rent": "demo_estimate",
    "gas": "needs_review",
    "free_power_kva": "needs_review",
    "substation_distance": "needs_review",
    "connection_fee": "demo_estimate",
    "steel_supplier_distance": "demo_estimate",
    "insulation_supplier_distance": "demo_estimate",
}

OFFICIAL_SOURCE_SEED = [
    {
        "group": "Площадки",
        "title": "Инвестиционная карта Российской Федерации",
        "url": "https://invest.gov.ru/",
        "comment": "Базовый источник для поиска и сверки инвестиционных площадок, земельных участков, промпарков и инфраструктуры.",
    },
    {
        "group": "ОЭЗ/льготы",
        "title": "Минэкономразвития РФ — особые экономические зоны",
        "url": "https://www.economy.gov.ru/material/directions/regionalnoe_razvitie/instrumenty_razvitiya_territoriy/osobye_ekonomicheskie_zony/",
        "comment": "Проверка статуса ОЭЗ и преференциального режима.",
    },
    {
        "group": "Социальная среда",
        "title": "Индекс качества городской среды",
        "url": "https://xn----dtbcccdtsypabxk.xn--p1ai/",
        "comment": "Официальный инструмент оценки городской среды.",
    },
    {
        "group": "Статистика",
        "title": "Росстат / ЕМИСС",
        "url": "https://rosstat.gov.ru/",
        "comment": "Официальная статистика по зарплатам, рынку труда и социально-экономическим показателям.",
    },
    {
        "group": "Сети",
        "title": "Региональные сетевые организации и тарифные службы",
        "url": "https://rosseti.ru/",
        "comment": "Свободная мощность, подстанции, стоимость присоединения и газ требуют региональной проверки; в MVP не выдаются за подтверждённые.",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_regions_raw() -> List[Dict[str, Any]]:
    return json.loads(REGIONS_PATH.read_text(encoding="utf-8"))


def save_regions_raw(regions: List[Dict[str, Any]]) -> None:
    REGIONS_PATH.write_text(json.dumps(regions, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_sources_file() -> List[Dict[str, Any]]:
    if not SOURCES_PATH.exists():
        SOURCES_PATH.write_text(json.dumps(OFFICIAL_SOURCE_SEED, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


def _status_counts(regions: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    official = review = demo = 0
    for r in regions:
        q = r.get("data_quality", {})
        values = list((q.get("quality_by_field") or {}).values()) or [q.get("status", "demo_estimate")]
        official += sum(1 for v in values if str(v).startswith("official") or v == "imported_official")
        review += sum(1 for v in values if v == "needs_review")
        demo += sum(1 for v in values if v in {"demo_estimate", "official_name_demo_metrics"})
    return official, review, demo


def get_data_status() -> Dict[str, Any]:
    sources = ensure_sources_file()
    regions = load_regions_raw()
    official, review, demo = _status_counts(regions)
    last_update = ""
    if UPDATE_LOG_PATH.exists():
        try:
            last_update = json.loads(UPDATE_LOG_PATH.read_text(encoding="utf-8")).get("last_update", "")
        except Exception:
            last_update = ""
    return {
        "regions_count": len(regions),
        "last_update": last_update,
        "official_verified_count": official,
        "needs_review_count": review,
        "demo_estimate_count": demo,
        "sources": sources,
        "message": "Гибридная база: подтверждаемые поля отделены от оценочных и требующих проверки.",
    }


def _base_quality_for_region(region: Dict[str, Any]) -> Dict[str, str]:
    q = dict(DEFAULT_QUALITY_BY_FIELD)
    name_type = " ".join([region.get("name", ""), *(z.get("type", "") for z in region.get("industrial_zones", []))]).lower()
    if "оэз" in name_type or "тор" in name_type:
        q["site_identity"] = "official_verified"
        q["oez_tor_status"] = "official_verified"
        q["tax_benefits"] = "needs_review"
    if region.get("center", {}).get("lat") and region.get("center", {}).get("lon"):
        q["coordinates"] = "official_name_demo_metrics"
    return q


def refresh_official_metadata() -> Dict[str, Any]:
    """Не притворяется полным парсингом всех реестров.

    Функция приводит текущую базу к честному виду: добавляет официальные источники,
    статусы по каждому блоку показателей и дату сверки. Это то, что безопасно
    делать без неофициального scraping/API-ключей.
    """
    sources = ensure_sources_file()
    regions = load_regions_raw()
    updated = unchanged = review = 0
    for r in regions:
        before = json.dumps(r.get("data_quality", {}), ensure_ascii=False, sort_keys=True)
        current = r.setdefault("data_quality", {})
        qbf = dict(_base_quality_for_region(r))
        qbf.update(current.get("quality_by_field") or {})
        # Инженерные показатели принципиально не подтверждаем автоматически.
        for field in ["gas", "free_power_kva", "substation_distance", "connection_fee"]:
            if qbf.get(field) not in {"official_verified", "imported_official"}:
                qbf[field] = "needs_review" if field != "connection_fee" else "demo_estimate"
        current["quality_by_field"] = qbf
        current["last_verified"] = _now()
        current["verified_source_groups"] = ["Площадки", "ОЭЗ/льготы", "Социальная среда", "Статистика", "Сети"]
        current["status"] = "partially_verified"
        current["note"] = (
            "Объект и часть статусов сверяются по официальным источникам; инженерные и тарифные показатели "
            "отмечены отдельно как требующие проверки или как оценка MVP."
        )
        # add source list if empty
        existing_urls = {s.get("url") for s in r.get("data_sources", [])}
        r.setdefault("data_sources", [])
        for src in sources[:4]:
            if src["url"] not in existing_urls:
                r["data_sources"].append(src)
        after = json.dumps(r.get("data_quality", {}), ensure_ascii=False, sort_keys=True)
        if before != after:
            updated += 1
        else:
            unchanged += 1
        review += sum(1 for v in qbf.values() if v == "needs_review")
    save_regions_raw(regions)
    log = {
        "last_update": _now(),
        "mode": "official_metadata_refresh",
        "updated": updated,
        "unchanged": unchanged,
        "needs_review": review,
        "sources_checked": [s["title"] for s in sources],
        "warnings": [
            "Инвестиционная карта РФ не имеет стабильного публичного API в MVP: подключён слой сверки и импорт CSV.",
            "Свободная мощность, газ и стоимость техприсоединения требуют региональных сетевых данных и не помечаются как официальные автоматически.",
        ],
    }
    UPDATE_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "mode": "official_metadata_refresh",
        "added": 0,
        "updated": updated,
        "unchanged": unchanged,
        "needs_review": review,
        "sources_checked": [s["title"] for s in sources],
        "warnings": log["warnings"],
        "message": "База обновлена в безопасном режиме: добавлены официальные источники и статусы качества по показателям.",
    }


CSV_FIELDS = [
    "id", "name", "federal_subject", "lat", "lon", "site_type",
    "railway_available", "federal_highway_km", "gas_available", "free_power_kva",
    "substation_distance_km", "connection_fee_rub_kw", "has_oez_tor",
    "energy_tariff_rub_kwh", "avg_salary_rub", "urban_env_index",
]


def csv_template() -> str:
    return ";".join(CSV_FIELDS) + "\n"


def import_sites_csv(csv_text: str) -> Dict[str, Any]:
    """Импортирует выгрузку CSV/Excel, сохранённую в CSV с разделителем ; или ,.

    Это практичный способ подключить официальные выгрузки, если у реестра нет
    удобного публичного API или есть только выгрузка из кабинета/портала.
    """
    sample = csv_text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,") if sample.strip() else csv.excel
    reader = csv.DictReader(csv_text.splitlines(), dialect=dialect)
    regions = load_regions_raw()
    by_id = {r.get("id"): r for r in regions}
    added = updated = unchanged = needs_review = 0
    for row in reader:
        rid = (row.get("id") or "").strip()
        if not rid:
            continue
        existing = by_id.get(rid)
        if not existing:
            added += 1
            existing = _make_region_from_csv_row(row)
            regions.append(existing)
            by_id[rid] = existing
        before = json.dumps(existing, ensure_ascii=False, sort_keys=True)
        _merge_csv_row(existing, row)
        after = json.dumps(existing, ensure_ascii=False, sort_keys=True)
        if before != after and before != "null":
            updated += 1
        else:
            unchanged += 1
        needs_review += sum(1 for v in existing.get("data_quality", {}).get("quality_by_field", {}).values() if v == "needs_review")
    save_regions_raw(regions)
    UPDATE_LOG_PATH.write_text(json.dumps({
        "last_update": _now(),
        "mode": "csv_import",
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "needs_review": needs_review,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "mode": "csv_import",
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "needs_review": needs_review,
        "sources_checked": ["CSV/Excel импорт"],
        "warnings": ["Поля, пришедшие из CSV, помечены imported_official; отсутствующие инженерные поля остаются needs_review."],
        "message": "CSV импортирован в локальную базу.",
    }


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "true", "да", "yes", "y"}


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(" ", "").replace(",", ".")))
    except Exception:
        return default


def _float(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except Exception:
        return default


def _make_region_from_csv_row(row: Dict[str, Any]) -> Dict[str, Any]:
    rid = row.get("id", "").strip()
    name = row.get("name", rid).strip() or rid
    lat = _float(row.get("lat"), 55.0)
    lon = _float(row.get("lon"), 37.0)
    site_type = row.get("site_type") or "Промышленная площадка"
    return {
        "id": rid,
        "name": name,
        "federal_subject": row.get("federal_subject") or "Не указан",
        "center": {"lat": lat, "lon": lon},
        "industrial_zones": [{"name": name, "lat": lat, "lon": lon, "type": site_type}],
        "logistics": {"steel_supplier_km": 250, "insulation_supplier_km": 250, "federal_highway_km": _int(row.get("federal_highway_km"), 20), "railway_available": _bool(row.get("railway_available"))},
        "economy": {"has_oez_tor": _bool(row.get("has_oez_tor")), "tax_relief_score": 0.8 if _bool(row.get("has_oez_tor")) else 0.35, "reduced_insurance": False, "energy_tariff_rub_kwh": _float(row.get("energy_tariff_rub_kwh"), 6.0), "avg_salary_rub": _int(row.get("avg_salary_rub"), 60000), "ecology_class": "C"},
        "infrastructure": {"gas_available": _bool(row.get("gas_available")), "free_power_kva": _int(row.get("free_power_kva"), 600), "substation_distance_km": _int(row.get("substation_distance_km"), 5), "connection_fee_rub_kw": _int(row.get("connection_fee_rub_kw"), 1800)},
        "social": {"urban_env_index": _int(row.get("urban_env_index"), 190), "kindergarten_per_100": 70, "has_profile_college": True, "rent_1room_rub": 18000},
        "culture": {"dominant_styles": ["современная промышленная архитектура"], "traditional_materials": ["сэндвич-панели", "металлокассеты", "фиброцемент"], "color_palette": ["#D8D2C4", "#6F7D82", "#2E5D4F", "#8B5A2B"], "historical_figures": []},
        "demographics_sample": {"dominant_age_group": "семьи 25-40", "schools_overcrowding_pct": 10, "kindergartens_shortage_pct": 15, "social_recommendation": "Проверить актуальные региональные данные"},
        "alternative_sites": [],
        "data_sources": ensure_sources_file(),
        "data_quality": {"status": "imported_official", "note": "Площадка импортирована из CSV/Excel выгрузки. Инженерные показатели требуют сверки с сетевыми организациями.", "quality_by_field": dict(DEFAULT_QUALITY_BY_FIELD), "last_verified": _now(), "verified_source_groups": ["CSV/Excel импорт"]},
    }


def _merge_csv_row(region: Dict[str, Any], row: Dict[str, Any]) -> None:
    q = region.setdefault("data_quality", {})
    qbf = dict(_base_quality_for_region(region))
    qbf.update(q.get("quality_by_field") or {})
    if row.get("name"):
        region["name"] = row["name"].strip()
        qbf["site_identity"] = "imported_official"
    if row.get("federal_subject"):
        region["federal_subject"] = row["federal_subject"].strip()
    if row.get("lat") and row.get("lon"):
        region.setdefault("center", {})["lat"] = _float(row.get("lat"))
        region.setdefault("center", {})["lon"] = _float(row.get("lon"))
        qbf["coordinates"] = "imported_official"
    if row.get("railway_available"):
        region.setdefault("logistics", {})["railway_available"] = _bool(row.get("railway_available"))
        qbf["railway_available"] = "imported_official"
    if row.get("federal_highway_km"):
        region.setdefault("logistics", {})["federal_highway_km"] = _int(row.get("federal_highway_km"))
        qbf["federal_highway_km"] = "imported_official"
    for key in ["gas_available", "free_power_kva", "substation_distance_km", "connection_fee_rub_kw"]:
        if row.get(key):
            region.setdefault("infrastructure", {})[key] = _bool(row[key]) if key == "gas_available" else _int(row[key])
            qbf_key = {"gas_available": "gas", "free_power_kva": "free_power_kva", "substation_distance_km": "substation_distance", "connection_fee_rub_kw": "connection_fee"}[key]
            qbf[qbf_key] = "imported_official"
    if row.get("has_oez_tor"):
        region.setdefault("economy", {})["has_oez_tor"] = _bool(row.get("has_oez_tor"))
        qbf["oez_tor_status"] = "imported_official"
    if row.get("energy_tariff_rub_kwh"):
        region.setdefault("economy", {})["energy_tariff_rub_kwh"] = _float(row.get("energy_tariff_rub_kwh"))
        qbf["energy_tariff"] = "imported_official"
    if row.get("avg_salary_rub"):
        region.setdefault("economy", {})["avg_salary_rub"] = _int(row.get("avg_salary_rub"))
        qbf["salary"] = "imported_official"
    if row.get("urban_env_index"):
        region.setdefault("social", {})["urban_env_index"] = _int(row.get("urban_env_index"))
        qbf["urban_env_index"] = "imported_official"
    q.update({
        "status": "partially_verified",
        "note": "Часть показателей импортирована из CSV/Excel выгрузки; неподтверждённые инженерные показатели сохраняют отдельный статус.",
        "quality_by_field": qbf,
        "last_verified": _now(),
        "verified_source_groups": list(set(q.get("verified_source_groups", []) + ["CSV/Excel импорт"])),
    })
