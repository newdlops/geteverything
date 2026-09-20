INSERT INTO deals(id,subject,community_name,category,shop_name,view_count)
VALUES (1,'새로운 게임 제목','ARCA','기타','네이버',0);
DO $$ BEGIN
  ASSERT (SELECT request_revision FROM deal_classifications WHERE deal_id=1)=1;
END $$;
UPDATE deals SET view_count=1,subject=subject,category=category WHERE id=1;
DO $$ BEGIN
  ASSERT (SELECT request_revision FROM deal_classifications WHERE deal_id=1)=1;
END $$;
UPDATE deal_classifications SET category='food',source='rule',status='ready',lease_until=now()+interval '2 minutes' WHERE deal_id=1;
UPDATE deals SET category='SW/게임' WHERE id=1;
DO $$ BEGIN
  ASSERT EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=1 AND request_revision=2 AND category='' AND status='pending' AND lease_until IS NULL);
END $$;
UPDATE deal_classifications SET category='food',status='ready' WHERE deal_id=1 AND request_revision=1;
DO $$ BEGIN
  ASSERT (SELECT category FROM deal_classifications WHERE deal_id=1)='';
END $$;
UPDATE deals SET shop_url_1='https://store.steampowered.com/app/123' WHERE id=1;
UPDATE deals SET shop_url_2='https://store.epicgames.com/a' WHERE id=1;
UPDATE deals SET shop_name='스팀' WHERE id=1;
UPDATE deals SET community_name='FMKOREA' WHERE id=1;
DO $$ BEGIN
  ASSERT (SELECT request_revision FROM deal_classifications WHERE deal_id=1)=6;
END $$;
UPDATE deal_classifications SET category='games',source='manual',status='ready',manual_override=true WHERE deal_id=1;
UPDATE deals SET category=NULL,shop_name=NULL,subject='수정한 제목' WHERE id=1;
DO $$ BEGIN
  ASSERT EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=1 AND request_revision=7 AND category='games' AND source='manual' AND manual_override AND status='ready' AND input_title='수정한 제목');
END $$;
SAVEPOINT source_rollback;
UPDATE deals SET shop_name='롤백할 판매처' WHERE id=1;
INSERT INTO deals(id,subject) VALUES(2,'롤백할 크롤링');
ROLLBACK TO SAVEPOINT source_rollback;
DO $$ BEGIN
  ASSERT (SELECT request_revision FROM deal_classifications WHERE deal_id=1)=7;
  ASSERT NOT EXISTS(SELECT 1 FROM deal_classifications WHERE deal_id=2);
END $$;
