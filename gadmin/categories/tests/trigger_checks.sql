INSERT INTO deals(id,subject,category,view_count) VALUES (1,'아이폰 케이스','원본',0);
DO $$ BEGIN
  IF (SELECT count(*) FROM deal_classifications WHERE deal_id=1 AND status='pending' AND request_revision=1) <> 1 THEN RAISE EXCEPTION 'insert_request'; END IF;
END $$;
UPDATE deals SET view_count=1,category='원본 변경' WHERE id=1;
UPDATE deals SET subject=subject WHERE id=1;
DO $$ BEGIN
  IF (SELECT request_revision FROM deal_classifications WHERE deal_id=1) <> 1 THEN RAISE EXCEPTION 'unchanged_subject'; END IF;
END $$;
UPDATE deal_classifications SET category='mobile',source='rule',status='ready',lease_until=now()+interval '2 minute' WHERE deal_id=1;
UPDATE deals SET subject='쌀 10kg' WHERE id=1;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=1 AND request_revision=2 AND input_title='쌀 10kg' AND category='' AND status='pending' AND lease_until IS NULL) THEN RAISE EXCEPTION 'changed_subject'; END IF;
END $$;
UPDATE deal_classifications SET category='mobile' WHERE deal_id=1 AND request_revision=1;
DO $$ BEGIN
  IF (SELECT category FROM deal_classifications WHERE deal_id=1) <> '' THEN RAISE EXCEPTION 'stale_result'; END IF;
END $$;
UPDATE deal_classifications SET category='food',source='manual',status='ready',manual_override=true WHERE deal_id=1;
UPDATE deals SET subject='제목 정정' WHERE id=1;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=1 AND category='food' AND source='manual' AND status='ready' AND request_revision=3 AND input_title='제목 정정') THEN RAISE EXCEPTION 'manual_preserved'; END IF;
END $$;
SAVEPOINT crawler_rollback;
INSERT INTO deals(id,subject) VALUES (2,'롤백할 크롤링');
ROLLBACK TO crawler_rollback;
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=2) THEN RAISE EXCEPTION 'rollback_orphan'; END IF;
END $$;
SELECT 'classification_trigger_checks_passed';
