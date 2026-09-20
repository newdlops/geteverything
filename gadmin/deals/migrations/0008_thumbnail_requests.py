"""Persist image work in the same transaction as a newly crawled deal."""
from django.db import migrations


SQL = """
CREATE TABLE public.thumbnail_requests (
    deal_id bigint PRIMARY KEY REFERENCES public.deals(id) ON DELETE CASCADE,
    revision bigint GENERATED ALWAYS AS IDENTITY,
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX thumbnail_requests_requested ON public.thumbnail_requests(requested_at, deal_id);

CREATE FUNCTION public.enqueue_thumbnail_request() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.shop_url_1 IS NOT DISTINCT FROM OLD.shop_url_1
           AND NEW.shop_url_2 IS NOT DISTINCT FROM OLD.shop_url_2
           AND NEW.origin_url IS NOT DISTINCT FROM OLD.origin_url THEN
            RETURN NEW;
        END IF;
    END IF;
    INSERT INTO public.thumbnail_requests(deal_id) VALUES (NEW.id)
    ON CONFLICT (deal_id) DO UPDATE SET revision=DEFAULT, requested_at=clock_timestamp();
    PERFORM pg_notify('geteverything_thumbnail_requests', '');
    RETURN NEW;
END;
$$;

CREATE TRIGGER deals_thumbnail_request
AFTER INSERT OR UPDATE OF shop_url_1, shop_url_2, origin_url ON public.deals
FOR EACH ROW EXECUTE FUNCTION public.enqueue_thumbnail_request();
"""

REVERSE_SQL = """
DROP TRIGGER deals_thumbnail_request ON public.deals;
DROP FUNCTION public.enqueue_thumbnail_request();
DROP TABLE public.thumbnail_requests;
"""


class Migration(migrations.Migration):
    dependencies = [('deals', '0007_deal_subject_trgm_vector_and_more')]
    operations = [migrations.RunSQL(SQL, REVERSE_SQL)]
