INSERT INTO deals (id,subject,price,currency,delivery_price,numeric_evidence,write_at,create_at,view_count)
VALUES (900001,'콜라 355ml 24캔',12000,'WON',0,'{}',clock_timestamp(),clock_timestamp(),0);
DO $$ BEGIN
 IF (SELECT count(*) FROM product_prices)<>1 THEN RAISE EXCEPTION 'insert_snapshot'; END IF;
END $$;
UPDATE deal_products SET product_id='00000000-0000-0000-0000-000000000001',status='ready' WHERE deal_id=900001;
UPDATE product_prices SET product_id='00000000-0000-0000-0000-000000000001';
UPDATE deals SET view_count=5 WHERE id=900001;
UPDATE deals SET price=12000 WHERE id=900001;
UPDATE deals SET price=10000 WHERE id=900001;
UPDATE deals SET price=12000 WHERE id=900001;
DO $$ BEGIN
 IF (SELECT count(*) FROM product_prices)<>3 THEN RAISE EXCEPTION 'price_ABA_or_view_count'; END IF;
 IF (SELECT identity_revision FROM deal_products WHERE deal_id=900001)<>1 THEN RAISE EXCEPTION 'price_changed_identity'; END IF;
 IF (SELECT input->>'price' FROM product_prices WHERE price_revision=2)<>'10000' THEN RAISE EXCEPTION 'price_mutated'; END IF;
 IF EXISTS(SELECT 1 FROM product_prices WHERE product_id IS NULL) THEN RAISE EXCEPTION 'price_only_lost_link'; END IF;
END $$;
UPDATE deals SET subject='다른 상품 500ml 12개',price=9000 WHERE id=900001;
DO $$ BEGIN
 IF (SELECT identity_revision FROM deal_products WHERE deal_id=900001)<>2 THEN RAISE EXCEPTION 'title_generation'; END IF;
 IF (SELECT status FROM deal_products WHERE deal_id=900001)<>'pending' THEN RAISE EXCEPTION 'title_not_pending'; END IF;
 IF (SELECT product_id FROM product_prices WHERE price_revision=4) IS NOT NULL THEN RAISE EXCEPTION 'new_title_old_product'; END IF;
 IF (SELECT count(*) FROM product_prices WHERE product_id IS NOT NULL)<>3 THEN RAISE EXCEPTION 'old_prices_moved'; END IF;
END $$;
UPDATE deal_products SET manual_override=true,status='ready',product_id='00000000-0000-0000-0000-000000000002' WHERE deal_id=900001;
UPDATE deals SET subject='다른 상품 1L 12개' WHERE id=900001;
DO $$ BEGIN
 IF (SELECT status FROM deal_products WHERE deal_id=900001)<>'review' THEN RAISE EXCEPTION 'manual_title_not_reconfirmed'; END IF;
 IF (SELECT product_id FROM product_prices WHERE price_revision=5) IS NOT NULL THEN RAISE EXCEPTION 'manual_old_product_leak'; END IF;
 IF (SELECT request_revision FROM deal_products WHERE deal_id=900001)<>3 THEN RAISE EXCEPTION 'stale_revision'; END IF;
END $$;
