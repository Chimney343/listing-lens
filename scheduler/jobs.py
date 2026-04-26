"""Command generation for scheduled spider jobs."""

from __future__ import annotations

from pathlib import Path

from scheduler.config import SearchProfile, SpiderJob, SpiderJobManifest


SCRAPY_DIR = Path(__file__).resolve().parent.parent / "scrapy_project"


_SPIDER_MAP: dict[tuple[str, str], str] = {
    ("otodom", "slugs"): "otodom_slugs",
    ("otodom", "detail"): "otodom_detail",
}


def _append_arg(command: list[str], key: str, value: str) -> None:
    command.extend(["-a", f"{key}={value}"])


def _append_setting(command: list[str], key: str, value: str) -> None:
    command.extend(["-s", f"{key}={value}"])


def _stringify_arg_value(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _profile_args(profile: SearchProfile) -> list[tuple[str, str]]:
    args: list[tuple[str, str]] = [("city", profile.city)]

    optional_values: list[tuple[str, object | None]] = [
        ("voivodeship", profile.voivodeship),
        ("powiat", profile.powiat),
        ("gmina", profile.gmina),
        ("property_type", profile.property_type),
        ("price_min", profile.price_min),
        ("price_max", profile.price_max),
        ("area_min", profile.area_min),
        ("area_max", profile.area_max),
        ("terrain_area_min", profile.terrain_area_min),
        ("terrain_area_max", profile.terrain_area_max),
        ("price_per_meter_min", profile.price_per_meter_min),
        ("price_per_meter_max", profile.price_per_meter_max),
        ("build_year_min", profile.build_year_min),
        ("build_year_max", profile.build_year_max),
        ("max_pages", profile.max_pages),
    ]

    for key, value in optional_values:
        if value is None:
            continue
        args.append((key, _stringify_arg_value(value)))

    if profile.districts:
        args.append(("districts", ",".join(profile.districts)))
    if profile.rooms_number:
        args.append(("rooms_number", ",".join(profile.rooms_number)))
    if profile.building_material:
        args.append(("building_material", ",".join(profile.building_material)))
    if profile.extras:
        args.append(("extras", ",".join(profile.extras)))

    return args


def resolve_spider_name(job: SpiderJob) -> str:
    """Resolve a spider name from portal + spider kind."""

    spider_name = _SPIDER_MAP.get((job.portal, job.spider_kind))
    if spider_name is None:
        raise NotImplementedError(
            f"Unsupported job mapping for portal='{job.portal}', spider_kind='{job.spider_kind}'"
        )
    return spider_name


def build_spider_command(
    *,
    job: SpiderJob,
    manifest: SpiderJobManifest,
    correlation_id: str | None = None,
) -> list[str]:
    """Build a scrapy command for one scheduled job."""

    command = ["poetry", "run", "scrapy", "crawl", resolve_spider_name(job)]

    if job.search_profile:
        profile = manifest.search_profiles[job.search_profile]
        for key, value in _profile_args(profile):
            _append_arg(command, key, value)

    if job.use_db_slug_queue:
        _append_arg(command, "use_db_slug_queue", "1")
        _append_setting(command, "USE_DB_SLUG_QUEUE", "1")

    if correlation_id:
        _append_arg(command, "correlation_id", correlation_id)

    for key, value in job.extra_args.items():
        _append_arg(command, key, value)

    return command
