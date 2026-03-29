-- Shared trigger: keeps updated_at current on every UPDATE.
-- Must be created before any table that references it.

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;
