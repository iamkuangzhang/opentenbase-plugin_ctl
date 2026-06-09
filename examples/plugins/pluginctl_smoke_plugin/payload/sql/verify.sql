SELECT CASE
    WHEN pluginctl_smoke_plugin.version() = '0.1.0'
     AND EXISTS (SELECT 1 FROM pluginctl_smoke_plugin.sample_data WHERE id = 1 AND note = 'installed')
    THEN 'ok'
    ELSE 'invalid'
END;
