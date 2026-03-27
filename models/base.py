from sqlalchemy import Column, DateTime, Uuid, func
from sqlalchemy.orm import declarative_base, declared_attr


class TenantAwareModel:
    __abstract__ = True

    @declared_attr
    def tenant_id(cls):  # type: ignore[no-untyped-def]
        return Column(Uuid(as_uuid=False), nullable=False, index=True)

    @declared_attr
    def created_at(cls):  # type: ignore[no-untyped-def]
        return Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.timezone("UTC", func.now()),
        )

    @declared_attr
    def updated_at(cls):  # type: ignore[no-untyped-def]
        return Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.timezone("UTC", func.now()),
            onupdate=func.timezone("UTC", func.now()),
        )


Base = declarative_base()
