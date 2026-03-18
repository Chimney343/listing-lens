---
applyTo: "**/storage/**,**/db.py,**/photos.py,**/models.py,**/*.sql"
---

# Stage 3 — Storage Layer (PostgreSQL + MinIO)

## Objective

Self-hosted PostgreSQL for structured data (listings, price history, feedback) and MinIO for binary photo storage. Both run on the same Hetzner VPS alongside Scrapy and APScheduler. No managed service caps.

## Dependencies

```
psycopg[binary]>=3.2          # PostgreSQL driver (sync + async)
minio>=7.2                     # S3-compatible client for MinIO
Pillow>=10.4
```

## VPS Setup (Hetzner CX32)

```bash
# Install PostgreSQL
sudo apt update && sudo apt install -y postgresql postgresql-contrib

# Install MinIO (single-node, single-drive — fine for solo project)
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
sudo mv minio /usr/local/bin/
sudo mkdir -p /data/minio

# Create systemd unit for MinIO
sudo tee /etc/systemd/system/minio.service <<EOF
[Unit]
Description=MinIO
After=network.target

[Service]
User=minio-user
Group=minio-user
Environment="MINIO_ROOT_USER=minioadmin"
Environment="MINIO_ROOT_PASSWORD=YOUR_STRONG_PASSWORD"
ExecStart=/usr/local/bin/minio server /data/minio --console-address ":9001"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo useradd -r -s /sbin/nologin minio-user
sudo chown -R minio-user:minio-user /data/minio
sudo systemctl enable minio && sudo systemctl start minio
```

MinIO dashboard: `http://YOUR_VPS_IP:9001` (firewall this — only expose to localhost or via SSH tunnel).

## Configuration

```python
# config/settings.py

from pydantic_settings import BaseSettings

class StorageSettings(BaseSettings):
    # PostgreSQL
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "property"
    pg_password: str = ""
    pg_database: str = "property_pipeline"
    
    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = ""
    minio_bucket: str = "listing-photos"
    minio_secure: bool = False  # True if using HTTPS
    
    # Photo processing
    max_photos_per_listing: int = 20
    photo_quality: int = 85
    max_photo_size_bytes: int = 5 * 1024 * 1024
    
    class Config:
        env_file = ".env"
```

## Database Schema

```sql
-- Run via psql or a migration tool

CREATE DATABASE property_pipeline;
\c property_pipeline

-- Core listings table
CREATE TABLE listings (
    listing_hash    TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    city            TEXT DEFAULT 'Kraków',
    district        TEXT,
    street          TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    price_pln       INTEGER,
    price_per_m2    DOUBLE PRECISION,
    area_m2         DOUBLE PRECISION,
    rooms           INTEGER,
    floor           INTEGER,
    total_floors    INTEGER,
    year_built      INTEGER,
    has_lift        BOOLEAN,
    has_balcony     BOOLEAN,
    has_terrace     BOOLEAN,
    has_storage     BOOLEAN,
    heating_type    TEXT,
    parking         TEXT,
    building_material TEXT,
    market_type     TEXT,
    listing_type    TEXT,
    date_posted     TIMESTAMPTZ,
    photo_count     INTEGER DEFAULT 0,
    description_length INTEGER DEFAULT 0,
    has_floor_plan  BOOLEAN DEFAULT FALSE,
    cross_listing_count INTEGER DEFAULT 1,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    gone_check_count INTEGER DEFAULT 0,
    composite_score DOUBLE PRECISION,
    score_json      JSONB,
    scored_at       TIMESTAMPTZ,
    raw_json        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_listings_district ON listings(district);
CREATE INDEX idx_listings_active ON listings(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_listings_score ON listings(composite_score DESC NULLS LAST);
CREATE INDEX idx_listings_first_seen ON listings(first_seen);

-- Source references (cross-portal tracking)
CREATE TABLE listing_sources (
    id              BIGSERIAL PRIMARY KEY,
    listing_hash    TEXT NOT NULL REFERENCES listings(listing_hash) ON DELETE CASCADE,
    source_portal   TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    price_at_source INTEGER,
    date_first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_last_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    UNIQUE(listing_hash, source_portal, external_id)
);

-- Price history — APPEND ONLY, never overwrite
CREATE TABLE price_history (
    id              BIGSERIAL PRIMARY KEY,
    listing_hash    TEXT NOT NULL REFERENCES listings(listing_hash) ON DELETE CASCADE,
    price_pln       INTEGER NOT NULL,
    price_per_m2    DOUBLE PRECISION,
    source_portal   TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_price_history_listing ON price_history(listing_hash, recorded_at);

-- Photo metadata (files stored in MinIO)
CREATE TABLE listing_photos (
    id              BIGSERIAL PRIMARY KEY,
    listing_hash    TEXT NOT NULL REFERENCES listings(listing_hash) ON DELETE CASCADE,
    photo_index     INTEGER NOT NULL,
    storage_path    TEXT NOT NULL,        -- MinIO object key
    original_url    TEXT,
    width           INTEGER,
    height          INTEGER,
    file_size_bytes INTEGER,
    is_floor_plan   BOOLEAN DEFAULT FALSE,
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(listing_hash, photo_index)
);

-- Feedback
CREATE TABLE feedback (
    id              BIGSERIAL PRIMARY KEY,
    listing_hash    TEXT NOT NULL REFERENCES listings(listing_hash) ON DELETE CASCADE,
    outcome         TEXT NOT NULL,
    notes           TEXT,
    dismissal_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Failed URLs
CREATE TABLE failed_urls (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT NOT NULL,
    portal          TEXT NOT NULL,
    error_type      TEXT,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    last_attempt    TIMESTAMPTZ DEFAULT NOW(),
    resolved        BOOLEAN DEFAULT FALSE
);
```

## Photo Storage (MinIO)

```python
# storage/photos.py

from minio import Minio
from PIL import Image
from io import BytesIO
import httpx

class PhotoManager:
    def __init__(self, settings=None):
        if settings is None:
            from config.settings import StorageSettings
            settings = StorageSettings()
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket
        self.settings = settings
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
    
    def download_and_store(self, listing_hash: str, photo_urls: list[str]) -> list[dict]:
        """Download photos, validate, optimize, upload to MinIO."""
        results = []
        http = httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"})
        
        for idx, url in enumerate(photo_urls[:self.settings.max_photos_per_listing]):
            try:
                meta = self._process_photo(http, listing_hash, idx, url)
                if meta:
                    results.append(meta)
            except Exception as e:
                print(f"Photo {idx} failed for {listing_hash}: {e}")
        
        http.close()
        return results
    
    def _process_photo(self, http, listing_hash, index, url) -> dict | None:
        resp = http.get(url)
        if resp.status_code != 200:
            return None
        
        # Validate
        try:
            img = Image.open(BytesIO(resp.content))
            img.verify()
            img = Image.open(BytesIO(resp.content))
            width, height = img.size
        except Exception:
            return None
        
        # Re-encode as JPEG
        output = BytesIO()
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output, format="JPEG", quality=self.settings.photo_quality)
        optimized = output.getvalue()
        
        if len(optimized) > self.settings.max_photo_size_bytes:
            output = BytesIO()
            img.save(output, format="JPEG", quality=60)
            optimized = output.getvalue()
        
        # Upload to MinIO
        object_name = f"{listing_hash}/{index:03d}.jpg"
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(optimized),
            length=len(optimized),
            content_type="image/jpeg",
        )
        
        return {
            "listing_hash": listing_hash,
            "photo_index": index,
            "storage_path": object_name,
            "original_url": url,
            "width": width,
            "height": height,
            "file_size_bytes": len(optimized),
            "is_floor_plan": any(kw in (url or "").lower() for kw in ["plan", "rzut", "layout"]),
        }
```

## Database Client

```python
# storage/db.py

import psycopg
from datetime import datetime, timedelta, timezone

class DatabaseClient:
    def __init__(self, settings=None):
        if settings is None:
            from config.settings import StorageSettings
            settings = StorageSettings()
        self.conninfo = (
            f"host={settings.pg_host} port={settings.pg_port} "
            f"dbname={settings.pg_database} user={settings.pg_user} "
            f"password={settings.pg_password}"
        )
    
    def _conn(self):
        return psycopg.connect(self.conninfo, autocommit=True)
    
    def get_listing_by_hash(self, listing_hash: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM listings WHERE listing_hash = %s", (listing_hash,)
            ).fetchone()
            if row:
                return dict(zip([d.name for d in conn.execute("SELECT * FROM listings WHERE FALSE").description], row))
        return None
    
    def insert_listing(self, listing_hash: str, data: dict):
        with self._conn() as conn:
            cols = ", ".join(data.keys())
            placeholders = ", ".join([f"%({k})s" for k in data.keys()])
            conn.execute(
                f"INSERT INTO listings ({cols}) VALUES ({placeholders}) ON CONFLICT (listing_hash) DO NOTHING",
                data,
            )
    
    def record_price_change(self, listing_hash: str, price: int, price_per_m2: float | None, source: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO price_history (listing_hash, price_pln, price_per_m2, source_portal) VALUES (%s, %s, %s, %s)",
                (listing_hash, price, price_per_m2, source),
            )
            conn.execute(
                "UPDATE listings SET price_pln=%s, price_per_m2=%s, updated_at=NOW() WHERE listing_hash=%s",
                (price, price_per_m2, listing_hash),
            )
    
    def close(self):
        pass  # Connections are per-call; nothing to close
```

## Storage Budget (Self-Hosted)

160 GB SSD on Hetzner CX32. Estimated usage:

| Component | Per listing | 5,000 listings |
|-----------|------------|----------------|
| DB row + history + sources | ~5 KB | ~25 MB |
| Photos (10 × 150 KB) | ~1.5 MB | ~7.5 GB |
| **Total** | | **~7.5 GB** |

Plenty of room. No external storage limits to worry about.

## Testing

1. Create the DB and tables via `psql`
2. Insert a test listing → verify row exists
3. Insert a price change → verify `price_history` row created
4. Upload a test photo to MinIO → verify via MinIO console at `:9001`
5. Verify `ON CONFLICT DO NOTHING` doesn't crash on duplicate insert
