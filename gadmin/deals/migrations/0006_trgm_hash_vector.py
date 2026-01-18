from django.db import migrations

DIM = 1024

SQL = f"""
-- trigram(text[])을 해시해서 vector({DIM}) 생성
CREATE OR REPLACE FUNCTION trgm_hash_vec_{DIM}(p_text text)
RETURNS vector({DIM})
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  tri text;
  idx int;
  v float8[];
  norm float8;
BEGIN
  v := array_fill(0::float8, ARRAY[{DIM}]);

  -- show_trgm(text) -> text[]
  FOREACH tri IN ARRAY show_trgm(p_text) LOOP
    -- md5 앞 8 hex를 int로 바꿔 버킷 지정
    idx := (abs(('x' || substr(md5(tri), 1, 8))::bit(32)::int) % {DIM}) + 1;
    v[idx] := v[idx] + 1.0;
  END LOOP;

  -- L2 normalize
  SELECT sqrt(sum(x*x)) INTO norm FROM unnest(v) AS x;
  IF norm > 0 THEN
    SELECT array_agg(x / norm ORDER BY ord) INTO v
    FROM unnest(v) WITH ORDINALITY AS t(x, ord);
  END IF;

  RETURN ('[' || array_to_string(v, ',') || ']')::vector({DIM});
END;
$$;

-- title이 바뀔 때마다 벡터 자동 갱신
CREATE OR REPLACE FUNCTION hotdeal_set_title_trgm_vec()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.subject_trgm_vector := trgm_hash_vec_{DIM}(NEW.subject);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS hotdeal_title_trgm_vec_biu ON deals;

CREATE TRIGGER hotdeal_title_trgm_vec_biu
BEFORE INSERT OR UPDATE OF subject ON deals
FOR EACH ROW
EXECUTE FUNCTION hotdeal_set_title_trgm_vec();
"""

class Migration(migrations.Migration):
    dependencies = [
        ("deals", "0005_deal_write_at_alter_deal_create_at"),
    ]
    operations = [
        migrations.RunSQL(SQL),
    ]
