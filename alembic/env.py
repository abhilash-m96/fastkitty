from logging.config import fileConfig

from alembic import context
from db.migrations import run_migrations_offline, run_migrations_online

# Alembic Config object
config = context.config

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if context.is_offline_mode():
    run_migrations_offline(context)
else:
    run_migrations_online(context)
