"""Collecting data from devices. The modules form a pipeline:

``targets``      which devices, and how to reach them (address, driver, credentials)
``connection``   one CLI session per device -> raw ``show`` output   (no database access)
``parsers``      raw output -> ParsedDevice / ParsedInterface        (pure functions)
``sanitize``     remove secrets from the running config before it is stored
``netbox_sync``  ParsedDevice -> NetBox objects, with a SyncReport of what changed
``runner``       drives a whole run: threads for device I/O, then sync, storage,
                 git commit, compliance and the webhook; writes the job log
"""
