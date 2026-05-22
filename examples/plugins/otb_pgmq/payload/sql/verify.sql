DO $$
DECLARE
    first_msg pgmq.message_record;
    second_msg pgmq.message_record;
    archived_ok boolean;
    deleted_ok boolean;
    q_count integer;
    a_count integer;
BEGIN
    PERFORM pgmq.drop_queue('otb_pluginctl_smoke');
    PERFORM pgmq.create('otb_pluginctl_smoke');

    PERFORM pgmq.send('otb_pluginctl_smoke', '{"hello":"world"}'::jsonb);
    PERFORM pgmq.send('otb_pluginctl_smoke', '{"hello":"again"}'::jsonb);

    SELECT * INTO first_msg FROM pgmq.read('otb_pluginctl_smoke', 0, 1);
    IF first_msg.msg_id IS DISTINCT FROM 1 OR first_msg.message IS DISTINCT FROM '{"hello":"world"}'::jsonb THEN
        RAISE EXCEPTION 'unexpected first message: %', first_msg;
    END IF;

    archived_ok := pgmq.archive('otb_pluginctl_smoke', first_msg.msg_id);
    IF archived_ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'archive failed for msg_id %', first_msg.msg_id;
    END IF;

    SELECT * INTO second_msg FROM pgmq.read('otb_pluginctl_smoke', 0, 1);
    IF second_msg.msg_id IS DISTINCT FROM 2 OR second_msg.message IS DISTINCT FROM '{"hello":"again"}'::jsonb THEN
        RAISE EXCEPTION 'unexpected second message: %', second_msg;
    END IF;

    deleted_ok := pgmq.delete('otb_pluginctl_smoke', second_msg.msg_id);
    IF deleted_ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'delete failed for msg_id %', second_msg.msg_id;
    END IF;

    EXECUTE 'SELECT count(*) FROM pgmq.q_otb_pluginctl_smoke' INTO q_count;
    EXECUTE 'SELECT count(*) FROM pgmq.a_otb_pluginctl_smoke' INTO a_count;
    IF q_count <> 0 OR a_count <> 1 THEN
        RAISE EXCEPTION 'unexpected queue/archive counts: q=%, a=%', q_count, a_count;
    END IF;

    PERFORM pgmq.drop_queue('otb_pluginctl_smoke');
END $$;

SELECT 'ok';
