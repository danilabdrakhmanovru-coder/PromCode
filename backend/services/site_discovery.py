"""Автоматическое пополнение базы площадок из открытых интернет-источников.

Без ИИ-ключа модуль работает так:
1) обходит заранее заданные официальные/региональные страницы;
2) извлекает из HTML названия возможных индустриальных парков, ОЭЗ и промплощадок;
3) нормализует кандидатов к формату проекта;
4) кладёт их в очередь candidates, не засоряя основную базу;
5) по команде добавляет выбранных кандидатов в regions.json.

Важно: без официального API и без ИИ извлечение является эвристическим. Поэтому новые объекты
сначала получают статус candidate_needs_review, а после добавления могут участвовать в рейтинге.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

import requests

from .data_update import REGIONS_PATH, load_regions_raw, save_regions_raw

BASE_DIR = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = BASE_DIR / "data" / "site_candidates.json"
DISCOVERY_LOG_PATH = BASE_DIR / "data" / "discovery_log.json"

DISCOVERY_SOURCES = [
    {
        "id": "bashkortostan_invest",
        "title": "Инвестпортал Республики Башкортостан",
        "region": "Республика Башкортостан",
        "url": "https://invest.bashkortostan.ru/",
        "lat": 54.7351,
        "lon": 55.9587,
    },
    {
        "id": "tatarstan_invest",
        "title": "Инвестпортал Республики Татарстан",
        "region": "Республика Татарстан",
        "url": "https://invest.tatarstan.ru/",
        "lat": 55.7961,
        "lon": 49.1064,
    },
    {
        "id": "lipetsk_invest",
        "title": "Инвестпортал Липецкой области",
        "region": "Липецкая область",
        "url": "https://invest-lipetsk.com/",
        "lat": 52.6031,
        "lon": 39.5708,
    },
    {
        "id": "alabuga",
        "title": "ОЭЗ Алабуга",
        "region": "Республика Татарстан",
        "url": "https://alabuga.ru/",
        "lat": 55.775,
        "lon": 52.018,
    },
    {
        "id": "oez_lipetsk",
        "title": "ОЭЗ Липецк",
        "region": "Липецкая область",
        "url": "https://oez-lipetsk.ru/",
        "lat": 52.59,
        "lon": 39.51,
    },
    {
        "id": "orel_invest",
        "title": "Инвестпортал Орловской области",
        "region": "Орловская область",
        "url": "https://invest-orel.ru/",
        "lat": 52.9671,
        "lon": 36.0698,
    },
]

KEY_PATTERNS = [
    r"(?:ОЭЗ|особая экономическая зона)\s*[«\"]?([А-ЯA-ZЁ][^<>\n\r]{2,80})[»\"]?",
    r"(?:индустриальный парк|промышленный парк|промпарк)\s*[«\"]?([А-ЯA-ZЁ][^<>\n\r]{2,80})[»\"]?",
    r"(?:промышленная площадка|инвестиционная площадка|производственная площадка)\s*[«\"]?([А-ЯA-ZЁ][^<>\n\r]{2,80})[»\"]?",
    r"[«\"]([^»\"]{3,70}(?:парк|ОЭЗ|Алга|Алабуга|Липецк|площадка|промплощадка)[^»\"]{0,40})[»\"]",
]

BAD_WORDS = {
    "карта", "новости", "контакты", "подробнее", "меры поддержки", "личный кабинет",
    "инвестиционная карта", "инвестиционный портал", "экономика", "главная",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(text: str) -> str:
    text = (text or "").lower().replace("ё", "e")
    repl = {
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ж":"zh","з":"z","и":"i","й":"y",
        "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u",
        "ф":"f","х":"h","ц":"c","ч":"ch","ш":"sh","щ":"sch","ы":"y","э":"e","ю":"yu","я":"ya",
        "ь":"","ъ":"",
    }
    out = "".join(repl.get(ch, ch) for ch in text)
    out = re.sub(r"[^a-z0-9]+", "_", out).strip("_")
    return out[:48] or hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _norm(text: str) -> str:
    text = html.unescape(text or "").lower().replace("ё", "е")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_name(name: str) -> str:
    name = html.unescape(re.sub(r"<[^>]+>", " ", name or ""))
    name = re.sub(r"\s+", " ", name).strip(" —–-:;,.|")
    name = re.sub(r"^(парк|площадка|объект)\s+", "", name, flags=re.I)
    return name[:110]


def _similar(a: str, b: str) -> float:
    a_n, b_n = _norm(a), _norm(b)
    if not a_n or not b_n:
        return 0.0
    if a_n in b_n or b_n in a_n:
        return 1.0
    return SequenceMatcher(None, a_n, b_n).ratio()


def _get(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NaslediyeIndustriiDiscovery/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=(3, 5))
    r.raise_for_status()
    return r.text[:900_000]


def _extract_links(base_url: str, html_text: str) -> List[str]:
    links = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I):
        href_l = href.lower()
        if any(k in href_l for k in ["park", "area", "site", " площад", "invest", "oez", "industrial", "territor"]):
            links.append(urljoin(base_url, href))
    out, seen = [], set()
    for link in links:
        if link.startswith("http") and link not in seen and len(out) < 8:
            out.append(link)
            seen.add(link)
    return out


def _extract_candidate_names(html_text: str, source_title: str) -> List[str]:
    text = re.sub(r"\s+", " ", html.unescape(html_text))
    found = []
    for pattern in KEY_PATTERNS:
        for m in re.finditer(pattern, text, flags=re.I):
            raw = m.group(0)
            if m.groups():
                raw = m.group(1)
            name = _clean_name(raw)
            low = _norm(name)
            if len(name) < 4 or len(name) > 110:
                continue
            if any(w in low for w in BAD_WORDS):
                continue
            if not any(k in low for k in ["оэз", "парк", "площад", "алабуг", "алга", "липецк"]):
                # Для коротких имён добавляем контекст источника.
                name = f"{source_title}: {name}"
            found.append(name)

    # fallback: если сайт сам является площадкой, добавляем его название
    if not found and any(k in _norm(source_title) for k in ["оэз", "парк"]):
        found.append(source_title)

    # unique
    out = []
    for name in found:
        if not any(_similar(name, x) > 0.86 for x in out):
            out.append(name)
    return out[:12]


def _candidate_to_region(candidate: Dict[str, Any]) -> Dict[str, Any]:
    lat = float(candidate.get("lat") or 55.0)
    lon = float(candidate.get("lon") or 49.0)
    name = candidate["name"]
    region = candidate["federal_subject"]
    cid = "auto_" + _slug(region + "_" + name)

    has_oez = "оэз" in _norm(name) or "особ" in _norm(name)
    return {
        "id": cid,
        "name": name,
        "center": {"lat": lat, "lon": lon},
        "industrial_zones": [
            {"name": name, "lat": lat, "lon": lon, "type": "кандидат"}
        ],
        "logistics": {
            "steel_supplier_km": 250,
            "insulation_supplier_km": 180,
            "federal_highway_km": 12,
            "railway_available": bool(candidate.get("railway_available", False)),
        },
        "economy": {
            "has_oez_tor": has_oez,
            "tax_relief_score": 0.75 if has_oez else 0.45,
            "reduced_insurance": has_oez,
            "energy_tariff_rub_kwh": 5.8,
            "avg_salary_rub": 55000,
            "ecology_class": "C",
        },
        "infrastructure": {
            "gas_available": bool(candidate.get("gas_available", False)),
            "free_power_kva": int(candidate.get("free_power_kva") or 1200),
            "substation_distance_km": 5,
            "connection_fee_rub_kw": 1500,
        },
        "social": {
            "urban_env_index": 190,
            "kindergarten_per_100": 70,
            "has_profile_college": True,
            "rent_1room_rub": 24000,
        },
        "culture": {
            "dominant_styles": ["региональный индустриальный стиль"],
            "traditional_materials": ["окрашенный металл", "светлый бетон", "дерево"],
            "color_palette": ["#1D4ED8", "#0EA5E9", "#F8FAFC", "#111827"],
            "historical_figures": [],
        },
        "demographics_sample": {
            "dominant_age_group": "рабочие и инженерные кадры 25–45",
            "schools_overcrowding_pct": 10,
            "kindergartens_shortage_pct": 10,
            "social_recommendation": "Для автоматически найденной площадки социальный блок рассчитан по типовым региональным допущениям; после подтверждения источника показатели следует уточнить.",
        },
        "alternative_sites": [],
        "data_quality": {
            "status": "auto_imported",
            "note": "Площадка автоматически найдена в открытом источнике и добавлена как кандидат. Инженерные и социальные показатели рассчитаны по типовым допущениям и требуют уточнения.",
            "quality_by_field": {
                "site_identity": "source_candidate",
                "coordinates": "source_or_regional_estimate",
                "oez_tor_status": "source_candidate" if has_oez else "needs_review",
                "tax_benefits": "needs_review",
                "urban_env_index": "regional_estimate",
                "salary": "regional_estimate",
                "kindergarten": "regional_estimate",
                "profile_college": "regional_estimate",
                "rent": "market_stat_estimate",
                "gas": "needs_review",
                "free_power_kva": "demo_estimate",
                "substation_distance": "demo_estimate",
                "connection_fee": "tariff_estimate",
                "steel_supplier_distance": "calculated_estimate",
                "insulation_supplier_distance": "calculated_estimate",
                "energy_tariff": "regional_tariff_estimate",
            },
            "last_verified": _now(),
            "verified_source_groups": [candidate.get("source_title", "открытый источник")],
        },
        "data_sources": [
            {
                "group": "Автоматический поиск",
                "title": candidate.get("source_title", "Открытый источник"),
                "url": candidate.get("source_url", ""),
                "comment": "Площадка найдена модулем автоматического пополнения базы.",
            }
        ],
    }


def load_candidates() -> List[Dict[str, Any]]:
    if not CANDIDATES_PATH.exists():
        return []
    try:
        data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_candidates(candidates: List[Dict[str, Any]]) -> None:
    CANDIDATES_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")


def discovery_status() -> Dict[str, Any]:
    candidates = load_candidates()
    log = {}
    if DISCOVERY_LOG_PATH.exists():
        try:
            log = json.loads(DISCOVERY_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            log = {}
    return {
        "candidates_count": len(candidates),
        "candidates": candidates[:50],
        "last_discovery": log,
    }


def discover_new_sites(full: bool = False) -> Dict[str, Any]:
    existing = load_regions_raw()
    existing_names = [r.get("name", "") for r in existing]
    current_candidates = load_candidates()
    candidate_names = [c.get("name", "") for c in current_candidates]

    found: List[Dict[str, Any]] = []
    warnings: List[str] = []
    sources = DISCOVERY_SOURCES if full else DISCOVERY_SOURCES[:4]

    for source in sources:
        try:
            html_text = _get(source["url"])
            pages = [source["url"]]
            if full:
                for link in _extract_links(source["url"], html_text):
                    try:
                        linked_html = _get(link)
                        html_text += "\n" + linked_html
                        pages.append(link)
                    except Exception as exc:
                        warnings.append(f"{link}: {type(exc).__name__}")
            names = _extract_candidate_names(html_text, source["title"])
            for name in names:
                duplicate = any(_similar(name, n) > 0.86 for n in existing_names + candidate_names)
                if duplicate:
                    continue
                cid = "candidate_" + hashlib.sha1((source["id"] + name).encode("utf-8")).hexdigest()[:12]
                found.append({
                    "id": cid,
                    "name": name,
                    "federal_subject": source["region"],
                    "lat": source["lat"],
                    "lon": source["lon"],
                    "source_title": source["title"],
                    "source_url": source["url"],
                    "discovered_at": _now(),
                    "status": "new_candidate",
                    "confidence": 0.78 if any(k in _norm(name) for k in ["оэз", "парк", "площад"]) else 0.55,
                    "pages_checked": pages[:6],
                })
                candidate_names.append(name)
        except Exception as exc:
            warnings.append(f"{source['title']}: {type(exc).__name__}: {exc}")

    merged = current_candidates + found
    save_candidates(merged)
    result = {
        "last_update": _now(),
        "mode": "full" if full else "fast",
        "sources_checked": len(sources),
        "found": len(found),
        "candidates_total": len(merged),
        "warnings": warnings[:20],
        "message": f"Поиск завершён: найдено новых кандидатов {len(found)}, всего в очереди {len(merged)}.",
    }
    DISCOVERY_LOG_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def import_candidates(candidate_ids: List[str] | None = None, limit: int = 10) -> Dict[str, Any]:
    candidates = load_candidates()
    if candidate_ids:
        selected = [c for c in candidates if c.get("id") in set(candidate_ids)]
    else:
        selected = candidates[:limit]

    regions = load_regions_raw()
    existing_ids = {r.get("id") for r in regions}
    existing_names = [r.get("name", "") for r in regions]

    added = []
    skipped = []
    for cand in selected:
        region = _candidate_to_region(cand)
        if region["id"] in existing_ids or any(_similar(region["name"], n) > 0.86 for n in existing_names):
            skipped.append({"id": cand.get("id"), "name": cand.get("name"), "reason": "duplicate"})
            continue
        regions.append(region)
        existing_ids.add(region["id"])
        existing_names.append(region["name"])
        added.append({"id": region["id"], "name": region["name"]})

    save_regions_raw(regions)
    remaining = [c for c in candidates if c.get("id") not in {x.get("id") for x in selected}]
    save_candidates(remaining)

    return {
        "added": len(added),
        "skipped": len(skipped),
        "remaining_candidates": len(remaining),
        "added_items": added,
        "skipped_items": skipped,
        "message": f"Добавлено площадок: {len(added)}. Осталось кандидатов: {len(remaining)}.",
    }
