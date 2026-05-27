"""
FastAPI приложение.

Эндпоинты:
    GET  /                              — главная страница (HTML)
    GET  /static/*                      — статика (CSS, JS, картинки)
    GET  /api/health                    — проверка
    GET  /api/regions                   — все регионы
    POST /api/rank                      — топ-3 под параметры инвестора
    GET  /api/region/{id}               — детали региона
    GET  /api/region/{id}/brief         — детали + LLM-справка под последний вход
    GET  /api/config                    — публичный конфиг (ключ карты)

Запуск:
    uvicorn backend.main:app --reload

Открыть в браузере:
    http://localhost:8000
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .llm_client import get_llm
from .models import (
    InvestorInput,
    RankResponse,
    Region,
    RegionDetailResponse,
    DataStatusResponse,
    DataRefreshResponse,
)
from .ranking import rank_regions
from .services.data_update import get_data_status, refresh_official_metadata, csv_template, import_sites_csv
from .services.verification import run_verification, verification_status
from .services.site_discovery import discover_new_sites, discovery_status, import_candidates
from .services.report_generator import build_investment_report_docx, build_project_passport_docx
from .services.render_generator import generate_project_renders, generate_site_plan, generate_concept_board, normalize_layout_key
from .services.presentation_generator import build_administration_presentation_pptx

# ----------------------------------------------------------------------
#  Пути
# ----------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
# Загружаем .env строго из корня проекта, а не из текущей папки запуска.
# Так ключи подтянутся и при запуске из корня, и при запуске из backend.
load_dotenv(PROJECT_DIR / ".env")
DATA_PATH = BASE_DIR / "data" / "regions.json"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def _load_regions() -> List[Region]:
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [Region(**item) for item in raw]


REGIONS: List[Region] = _load_regions()
REGIONS_BY_ID: Dict[str, Region] = {r.id: r for r in REGIONS}

# Кэш последнего инвестор-ввода (для /brief). В проде заменим на сессии.
LAST_INPUT: Optional[InvestorInput] = None

# ----------------------------------------------------------------------
#  Приложение
# ----------------------------------------------------------------------

app = FastAPI(
    title="ПромКод",
    description="Подбор региона для завода сэндвич-панелей",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ----------------------------------------------------------------------
#  Страница
# ----------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Главная страница приложения."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "dgis_key": os.getenv("DGIS_API_KEY", ""),
            "regions_count": len(REGIONS),
        },
    )


# ----------------------------------------------------------------------
#  API
# ----------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "regions_loaded": len(REGIONS)}


@app.get("/api/config")
def config():
    dgis_key = os.getenv("DGIS_API_KEY", "").strip()
    yandex_key = os.getenv("YANDEX_MAPS_API_KEY", "").strip()
    llm_key = os.getenv("LLM_API_KEY", "").strip()
    return {
        "has_dgis_key": bool(dgis_key),
        "dgis_key_prefix": dgis_key[:8] + "…" if dgis_key else "",
        "has_yandex_key": bool(yandex_key),
        "has_llm_key": bool(llm_key),
        "regions_count": len(REGIONS),
    }




@app.get("/api/data/status", response_model=DataStatusResponse)
def data_status():
    """Сводка по источникам, статусам качества данных и последнему обновлению."""
    return get_data_status()


@app.post("/api/data/refresh", response_model=DataRefreshResponse)
def data_refresh():
    """Безопасное обновление метаданных источников и статусов качества.

    В MVP не притворяемся, что скачали все инженерные показатели автоматически: 
    добавляем официальные источники, дату сверки и пометки по каждому показателю.
    """
    global REGIONS, REGIONS_BY_ID
    result = refresh_official_metadata()
    REGIONS = _load_regions()
    REGIONS_BY_ID = {r.id: r for r in REGIONS}
    return result


@app.get("/api/data/template", response_class=PlainTextResponse)
def data_template():
    """CSV-шаблон для импорта официальных выгрузок."""
    return csv_template()


@app.post("/api/data/import-csv", response_model=DataRefreshResponse)
async def data_import_csv(request: Request):
    """Импорт CSV/Excel-выгрузки, сохранённой в CSV."""
    global REGIONS, REGIONS_BY_ID
    body = (await request.body()).decode("utf-8-sig")
    result = import_sites_csv(body)
    REGIONS = _load_regions()
    REGIONS_BY_ID = {r.id: r for r in REGIONS}
    return result


@app.get("/api/verification/status")
def get_verification_status():
    """Возвращает последний отчёт автоматической верификации данных."""
    return verification_status()


@app.post("/api/verification/run")
def run_data_verification(
    use_llm: bool = Query(False, description="Использовать ИИ только как extractor, не как источник факта"),
    mode: str = Query("fast", description="fast — быстрая сверка, full — полный обход источников"),
):
    """Запускает автоматизированную сверку данных.

    fast: быстрая сверка по локальной базе, координатам, типам показателей и источникам.
    full: полный обход официальных и региональных сайтов.
    """
    global REGIONS, REGIONS_BY_ID
    mode = "full" if mode == "full" else "fast"
    result = run_verification(use_llm_extractor=use_llm, mode=mode)
    REGIONS = _load_regions()
    REGIONS_BY_ID = {r.id: r for r in REGIONS}
    return result



@app.get("/api/discovery/status")
def get_discovery_status():
    """Возвращает очередь найденных кандидатов на добавление в базу."""
    return discovery_status()


@app.post("/api/discovery/run")
def run_site_discovery(mode: str = Query("fast", description="fast — быстрый поиск, full — больше источников и внутренних ссылок")):
    """Ищет новые площадки в открытых источниках без ИИ-ключа."""
    return discover_new_sites(full=(mode == "full"))


@app.post("/api/discovery/import")
async def import_discovered_sites(request: Request, limit: int = Query(10)):
    """Добавляет найденные площадки из очереди кандидатов в основную базу."""
    global REGIONS, REGIONS_BY_ID
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    candidate_ids = payload.get("candidate_ids") if isinstance(payload, dict) else None
    result = import_candidates(candidate_ids=candidate_ids, limit=limit)
    REGIONS = _load_regions()
    REGIONS_BY_ID = {r.id: r for r in REGIONS}
    return result



@app.get("/api/investor-package/{region_id}.zip")
def download_investor_package_zip(region_id: str, layout: Optional[str] = Query(None)):
    """Формирует единый пакет инвестора: основные документы и материалы по площадке."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked_list = rank_regions(REGIONS, LAST_INPUT)
    ranked = next((item for item in ranked_list if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    layout = normalize_layout_key(layout, region.id)
    out_dir = Path(tempfile.mkdtemp(prefix=f"investor_package_{region_id}_"))
    zip_path = out_dir / f"investor_package_{region_id}.zip"

    files_to_add = []
    warnings = []

    def add_generated(label: str, arcname: str, fn):
        try:
            path = fn()
            if path and Path(path).exists():
                files_to_add.append((Path(path), arcname))
            else:
                warnings.append(f"{label}: файл не создан")
        except Exception as exc:
            warnings.append(f"{label}: {type(exc).__name__}: {exc}")

    add_generated("Word-отчёт", "01_word_report.docx",
                  lambda: build_investment_report_docx(region, ranked, LAST_INPUT, brief))
    add_generated("Паспорт проекта", "02_project_passport.docx",
                  lambda: build_project_passport_docx(region, ranked, LAST_INPUT, brief))
    add_generated("Презентация", "03_presentation.pptx",
                  lambda: build_administration_presentation_pptx(region, ranked, LAST_INPUT, brief, layout))
    add_generated("План участка", "04_site_plan.png",
                  lambda: generate_site_plan(region, ranked, LAST_INPUT, layout))

    # Рендеры и концепт-борд — вспомогательные материалы. Если один из них не собрался,
    # пакет всё равно скачивается с основными документами.
    try:
        renders = generate_project_renders(region, ranked, LAST_INPUT, brief, layout)
        for name, path in (renders or {}).items():
            if path and Path(path).exists():
                files_to_add.append((Path(path), f"renders/{name}.png"))
    except Exception as exc:
        warnings.append(f"Рендеры: {type(exc).__name__}: {exc}")

    try:
        concept = generate_concept_board(region, ranked, LAST_INPUT, brief)
        if concept and Path(concept).exists():
            files_to_add.append((Path(concept), "05_concept_board.png"))
    except Exception as exc:
        warnings.append(f"Концепт-борд: {type(exc).__name__}: {exc}")

    comparison = []
    for i, item in enumerate(ranked_list[:3], start=1):
        components = [
            float(item.score.logistics),
            float(item.score.infrastructure),
            float(item.score.economy),
            float(item.score.social),
        ]
        avg_score = sum(components) / len(components)
        comparison.append({
            "place": i,
            "id": item.region.id,
            "name": item.region.name,
            "subject": item.region.federal_subject,
            "ranking_score": round(item.score.final_score, 4),
            "average_component_score": round(avg_score, 4),
            "logistics": round(item.score.logistics, 4),
            "infrastructure": round(item.score.infrastructure, 4),
            "economy": round(item.score.economy, 4),
            "social": round(item.score.social, 4),
            "site_and_network_mln": round(item.site_and_network_mln, 2),
            "free_power_kva": item.region.infrastructure.free_power_kva,
            "highway_km": item.region.logistics.federal_highway_km,
            "railway": item.region.logistics.railway_available,
        })

    readme_text = (
        "Пакет инвестора сформирован автоматически.\\n\\n"
        "Состав: основные документы, презентация, план участка, рендеры при наличии, "
        "а также comparison_top3.json со сравнением площадок.\\n"
        "Если отдельные визуальные материалы не сформировались, основные документы всё равно включаются в архив.\\n"
    )
    if warnings:
        readme_text += "\\nПредупреждения при сборке:\\n" + "\\n".join(f"- {w}" for w in warnings)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arcname in files_to_add:
            z.write(path, arcname)
        z.writestr("comparison_top3.json", json.dumps(comparison, ensure_ascii=False, indent=2))
        z.writestr("README.txt", readme_text)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"investor_package_{region_id}.zip",
    )

@app.get("/api/report/{region_id}.docx")
def download_report_docx(region_id: str, layout: Optional[str] = Query(None)):
    """Формирует Word-отчёт по выбранной площадке и последним параметрам инвестора."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    path = build_investment_report_docx(region, ranked, LAST_INPUT, brief)
    filename = f"investment_report_{region_id}.docx"
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@app.get("/api/passport/{region_id}.docx")
def download_project_passport_docx(region_id: str):
    """Формирует официальный паспорт проекта в строгом ГОСТ-ориентированном оформлении."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    path = build_project_passport_docx(region, ranked, LAST_INPUT, brief)
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"project_passport_{region_id}.docx",
    )



@app.get("/api/renders/{region_id}")
def generate_renders(region_id: str, layout: Optional[str] = Query(None)):
    """Генерирует 4 процедурных PNG-рендера и план участка без внешних API."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    layout = normalize_layout_key(layout, region_id)
    renders = generate_project_renders(region, ranked, LAST_INPUT, brief, layout)
    plan = generate_site_plan(region, ranked, LAST_INPUT, layout)
    concept_board = generate_concept_board(region, ranked, LAST_INPUT, brief)
    return {
        "mode": "procedural",
        "message": "Визуальные материалы сформированы.",
        "layout": layout,
        "renders": {key: f"/api/renders/{region_id}/{key}.png?layout={layout}" for key in renders.keys()},
        "site_plan": f"/api/renders/{region_id}/site_plan.png?layout={layout}",
        "concept_board": f"/api/renders/{region_id}/concept_board.png",
        "presentation": f"/api/presentation/{region_id}.pptx?layout={layout}",
    }


@app.get("/api/renders/{region_id}/{name}.png")
def download_render_png(region_id: str, name: str, layout: Optional[str] = Query(None)):
    """Отдаёт один из сгенерированных PNG: south/north/west/east/site_plan."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")
    allowed = {"south", "north", "west", "east", "site_plan", "concept_board"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Неизвестный вид рендера")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    if name == "site_plan":
        path = generate_site_plan(region, ranked, LAST_INPUT, layout)
    elif name == "concept_board":
        path = generate_concept_board(region, ranked, LAST_INPUT, brief)
    else:
        path = generate_project_renders(region, ranked, LAST_INPUT, brief, layout)[name]
    return FileResponse(
        path=path,
        media_type="image/png",
        filename=f"{region_id}_{name}.png",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/presentation/{region_id}.pptx")
def download_presentation_pptx(region_id: str, layout: Optional[str] = Query(None)):
    """Формирует презентацию для администрации на 6 слайдов с 4 рендерами и планом участка."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    region = REGIONS_BY_ID[region_id]
    layout = normalize_layout_key(layout, region_id)
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    path = build_administration_presentation_pptx(region, ranked, LAST_INPUT, brief, layout)
    filename = f"administration_presentation_{region_id}.pptx"
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )


@app.post("/api/presentation/{region_id}/from-shots.pptx")
async def download_presentation_from_3d_shots(region_id: str, request: Request, layout: Optional[str] = Query(None)):
    """Формирует PPTX с клиентскими скриншотами 3D-модели вместо серверных процедурных PNG."""
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(status_code=412, detail="Сначала выполните подбор площадок через POST /api/rank.")

    ranked = next((item for item in rank_regions(REGIONS, LAST_INPUT) if item.region.id == region_id), None)
    if ranked is None:
        raise HTTPException(status_code=422, detail="Площадка не входит в текущую подборку под заданные параметры.")

    payload = await request.json()
    shots = payload.get("shots") or {}
    required = ["south", "north", "west", "east"]
    if not all(k in shots for k in required):
        raise HTTPException(status_code=422, detail="Не переданы все 4 скриншота 3D-модели.")

    layout = normalize_layout_key(layout or payload.get("layout"), region_id)
    out_dir = Path(tempfile.gettempdir()) / "naslediye_industrii_generated" / "client_3d_shots" / f"{region_id}_{layout}"
    out_dir.mkdir(parents=True, exist_ok=True)

    render_paths: Dict[str, Path] = {}
    for key in required:
        data_url = str(shots[key])
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        try:
            raw = base64.b64decode(data_url)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Некорректный PNG для {key}") from exc
        path = out_dir / f"render_{key}.png"
        path.write_bytes(raw)
        render_paths[key] = path

    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    path = build_administration_presentation_pptx(region, ranked, LAST_INPUT, brief, layout, custom_renders=render_paths)
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=f"administration_presentation_{region_id}_3dshots.pptx",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/api/regions", response_model=List[Region])
def list_regions():
    return REGIONS


@app.post("/api/rank", response_model=RankResponse)
def rank(inp: InvestorInput):
    global LAST_INPUT
    LAST_INPUT = inp

    top3 = rank_regions(REGIONS, inp)
    if not top3:
        raise HTTPException(
            status_code=422,
            detail="Под заданные параметры ни один регион не подошёл. "
                   "Попробуйте ослабить требования к ж/д ветке или расстоянию до трассы.",
        )
    return RankResponse(top3=top3, input_echo=inp)


@app.get("/api/region/{region_id}", response_model=Region)
def get_region(region_id: str):
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    return REGIONS_BY_ID[region_id]


@app.get("/api/region/{region_id}/brief", response_model=RegionDetailResponse)
def get_region_brief(region_id: str):
    if region_id not in REGIONS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Регион '{region_id}' не найден")
    if LAST_INPUT is None:
        raise HTTPException(
            status_code=412,
            detail="Сначала вызовите POST /api/rank, чтобы зафиксировать параметры инвестора.",
        )
    region = REGIONS_BY_ID[region_id]
    brief = get_llm().generate_region_brief(region, LAST_INPUT)
    return RegionDetailResponse(region=region, brief=brief)
