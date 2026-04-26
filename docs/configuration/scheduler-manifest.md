# scheduler manifest

The scheduler reads a YAML or JSON manifest that defines search profiles and jobs.

Default path used by `main.py`:

- `config/spider_jobs.yaml`

Reference template:

- `config/spider_jobs.example.yaml`

## Top-level shape

```yaml
search_profiles:
  profile_name:
    city: krakow
    ...filters...

jobs:
  - job_id: otodom-krakow-slugs-daily
    enabled: true
    portal: otodom
    spider_kind: slugs
    search_profile: profile_name
    schedule:
      type: cron
      expression: "15 6 * * *"
```

## search_profiles

`search_profiles` stores reusable filter sets. A job can reference a profile by name
through `search_profile`.

Supported filter fields map directly to spider args, including:

- `city`, `voivodeship`, `powiat`, `gmina`, `property_type`
- `districts`
- `price_*`, `area_*`, `terrain_area_*`, `price_per_meter_*`, `build_year_*`
- `rooms_number`, `building_material`, `extras`
- `max_pages`

## jobs

Each item in `jobs` defines one scheduled spider command.

Required fields:

- `job_id`
- `portal` (`otodom`, `gratka`, `morizon`)
- `spider_kind` (`slugs`, `detail`)
- `schedule`

Optional fields:

- `enabled` (default `true`)
- `search_profile`
- `use_db_slug_queue` (adds `-a use_db_slug_queue=1`)
- `extra_args` (key-value spider arguments)

## schedule types

### cron

```yaml
schedule:
  type: cron
  expression: "15 6 * * *"
```

### interval

```yaml
schedule:
  type: interval
  hours: 8
  jitter_seconds: 1800
```

At least one interval unit (`seconds`, `minutes`, `hours`, or `days`) is required.

## current mapping status

Job-to-spider mapping is currently implemented for:

- `(otodom, slugs) -> otodom_slugs`
- `(otodom, detail) -> otodom_detail`

Other portal mappings are scaffolded but not yet wired in command generation.
