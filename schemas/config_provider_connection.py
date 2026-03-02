from pydantic import BaseModel, Field


class ConfigProviderConnectionData(BaseModel):
    pass


class FileConnectionData(ConfigProviderConnectionData):
    """Schema for file-based config provider connection data."""

    file_path: str = Field(..., description="Path to the JSON configuration file")


class DatabaseConnectionData(ConfigProviderConnectionData):
    """Schema for database-based config provider connection data."""

    db_uri: str = Field(..., description="Database connection URI for the tenant catalog")
