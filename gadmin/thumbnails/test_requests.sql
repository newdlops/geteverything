-- Run with 0008's SQL installed in an isolated schema, inside a rollback-only transaction.
INSERT INTO deals(id, shop_url_1, thumbnail) VALUES (1, 'https://shop.example.com/p/1', '');
DO $$
DECLARE original bigint; changed bigint; after_delete bigint;
BEGIN
    SELECT revision INTO original FROM thumbnail_requests WHERE deal_id=1;
    IF original IS NULL THEN RAISE EXCEPTION 'insert did not queue work'; END IF;
    UPDATE deals SET view_count=1,thumbnail='http://static.example.com/1.jpg' WHERE id=1;
    IF (SELECT revision FROM thumbnail_requests WHERE deal_id=1) <> original THEN
        RAISE EXCEPTION 'thumbnail publication or counter update caused a loop';
    END IF;
    UPDATE deals SET shop_url_1=shop_url_1 WHERE id=1;
    IF (SELECT revision FROM thumbnail_requests WHERE deal_id=1) <> original THEN
        RAISE EXCEPTION 'unchanged link queued duplicate work';
    END IF;
    UPDATE deals SET shop_url_1='https://shop.example.com/p/2' WHERE id=1;
    SELECT revision INTO changed FROM thumbnail_requests WHERE deal_id=1;
    IF changed <= original THEN RAISE EXCEPTION 'changed product did not advance revision'; END IF;
    DELETE FROM thumbnail_requests WHERE deal_id=1 AND revision=original;
    IF NOT EXISTS (SELECT 1 FROM thumbnail_requests WHERE deal_id=1 AND revision=changed) THEN
        RAISE EXCEPTION 'old acknowledgement removed newer work';
    END IF;
    DELETE FROM thumbnail_requests WHERE deal_id=1 AND revision=changed;
    UPDATE deals SET shop_url_2='https://shop.example.com/p/3' WHERE id=1;
    SELECT revision INTO after_delete FROM thumbnail_requests WHERE deal_id=1;
    IF after_delete <= changed THEN RAISE EXCEPTION 'revision reused after acknowledgement'; END IF;
    DELETE FROM deals WHERE id=1;
    IF EXISTS (SELECT 1 FROM thumbnail_requests WHERE deal_id=1) THEN
        RAISE EXCEPTION 'deleted deal left orphaned work';
    END IF;
END;
$$;
SAVEPOINT crawl_rollback;
INSERT INTO deals(id) VALUES (2);
ROLLBACK TO crawl_rollback;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM thumbnail_requests WHERE deal_id=2) THEN
        RAISE EXCEPTION 'rolled-back crawl left a job';
    END IF;
END; $$;
