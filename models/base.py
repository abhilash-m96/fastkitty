from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import declarative_base


class TimestampedModel:
    __abstract__ = True

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.timezone("UTC", func.now()),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.timezone("UTC", func.now()),
        onupdate=func.timezone("UTC", func.now()),
    )


class TenantScopedModel:
    __abstract__ = True

    tenant_id = Column(String(255), nullable=False, index=True)


Base = declarative_base()
